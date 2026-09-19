#!/usr/bin/env python3
"""
SatQuery AI — VLM Evaluation Script
Evaluates fine-tuned PaliGemma LoRA checkpoint on BigEarthNet VQA validation split.
Computes Exact Match (EM), Label Recall, Label Precision, and Label F1 metrics.

Usage:
  # Quick dry run on 5 samples (no GPU / model load needed):
  python scripts/evaluate_vlm.py --dataset_name bigearthnet-mini --max_samples 5 --dry_run

  # Full evaluation on bigearthnet-medium validation split:
  python scripts/evaluate_vlm.py --dataset_name bigearthnet-medium
"""

import argparse
import json
import logging
import os
import pathlib
import sys
import time
from typing import Any, Dict, List, Set

project_root = pathlib.Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from datasets import load_from_disk
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# BigEarthNet 43-class labels
BIGEARTHNET_LABELS_43 = [
    "Agro-forestry areas",
    "Airports",
    "Annual crops associated with permanent crops",
    "Bare rock",
    "Beaches, dunes, sands",
    "Broad-leaved forest",
    "Burnt areas",
    "Coastal lagoons",
    "Complex cultivation patterns",
    "Coniferous forest",
    "Construction sites",
    "Continuous urban fabric",
    "Discontinuous urban fabric",
    "Dump sites",
    "Estuaries",
    "Fruit trees and berry plantations",
    "Green urban areas",
    "Industrial or commercial units",
    "Inland marshes",
    "Intertidal flats",
    "Land principally occupied by agriculture, with significant areas of natural vegetation",
    "Mineral extraction sites",
    "Mixed forest",
    "Moors and heathland",
    "Natural grassland",
    "Non-irrigated arable land",
    "Olive groves",
    "Pastures",
    "Peatbogs",
    "Permanently irrigated land",
    "Port areas",
    "Rice fields",
    "Road and rail networks and associated land",
    "Salines",
    "Salt marshes",
    "Sclerophyllous vegetation",
    "Sea and ocean",
    "Sparsely vegetated areas",
    "Sport and leisure facilities",
    "Transitional woodland/shrub",
    "Vineyards",
    "Water bodies",
    "Water courses",
]


def extract_labels_from_text(text: str, candidate_labels: List[str]) -> Set[str]:
    """Finds all candidate class labels mentioned in the text (case-insensitive)."""
    text_lower = text.lower()
    matched = set()
    for lbl in candidate_labels:
        if lbl.lower() in text_lower:
            matched.add(lbl)
    return matched


def compute_sample_metrics(ground_truth: str, prediction: str, candidate_labels: List[str]) -> Dict[str, Any]:
    """
    Computes Exact Match (EM), Precision, Recall, and F1 for a single sample.
    """
    # Normalize strings for EM
    norm_gt = ground_truth.strip().lower()
    norm_pred = prediction.strip().lower()
    exact_match = 1.0 if (norm_gt == norm_pred or norm_gt in norm_pred) else 0.0

    gt_labels = extract_labels_from_text(ground_truth, candidate_labels)
    pred_labels = extract_labels_from_text(prediction, candidate_labels)

    if not gt_labels:
        # Ground truth had no specific land cover
        precision = 1.0 if not pred_labels else 0.0
        recall = 1.0
        f1 = 1.0 if not pred_labels else 0.0
    else:
        true_positives = len(gt_labels & pred_labels)
        recall = true_positives / len(gt_labels) if len(gt_labels) > 0 else 0.0
        precision = true_positives / len(pred_labels) if len(pred_labels) > 0 else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "exact_match": exact_match,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "gt_labels": sorted(list(gt_labels)),
        "pred_labels": sorted(list(pred_labels)),
    }


def evaluate(
    dataset_name: str = "bigearthnet-medium",
    checkpoint_dir: str = None,
    max_samples: int = None,
    output_file: str = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Runs evaluation on the validation split and returns metrics dictionary.
    """
    from app.core.config import get_settings
    settings = get_settings()

    val_data_path = project_root / "data" / "derived" / f"{dataset_name}_vqa" / "val"
    if not val_data_path.exists():
        raise FileNotFoundError(
            f"Validation dataset not found at {val_data_path}. "
            f"Please run scripts/build_vlm_dataset.py --dataset_name {dataset_name} first."
        )

    logger.info(f"Loading validation dataset from {val_data_path} ...")
    val_ds = load_from_disk(str(val_data_path))
    total_val = len(val_ds)
    if max_samples:
        val_ds = val_ds.select(range(min(max_samples, total_val)))
    eval_count = len(val_ds)
    logger.info(f"Evaluating on {eval_count} samples (out of {total_val} available)...")

    processor = None
    model = None

    if not dry_run:
        if checkpoint_dir:
            os.environ["VLM_MODEL_NAME"] = str(checkpoint_dir)
        else:
            default_weights = project_root / "data" / "weights" / "satquery-paligemma-lora"
            if default_weights.exists():
                os.environ["VLM_MODEL_NAME"] = str(default_weights)

        from app.core.model_provider import load_vlm, generate_vlm_answer
        logger.info(f"Loading VLM model (configured as {os.environ.get('VLM_MODEL_NAME')}) ...")
        processor, model = load_vlm()
    else:
        logger.info("Dry run enabled: skipping model load, using simulated predictions.")

    sample_results = []
    em_scores = []
    precisions = []
    recalls = []
    f1_scores = []

    t0 = time.time()
    for idx, sample in enumerate(val_ds):
        prompt = sample["prompt"]
        ground_truth = sample["text"]
        image = sample["image"]

        if dry_run:
            prediction = ground_truth  # In dry run, return ground truth as prediction
        else:
            prediction = generate_vlm_answer(processor, model, image, prompt, max_new_tokens=64)

        metrics = compute_sample_metrics(ground_truth, prediction, BIGEARTHNET_LABELS_43)

        em_scores.append(metrics["exact_match"])
        precisions.append(metrics["precision"])
        recalls.append(metrics["recall"])
        f1_scores.append(metrics["f1"])

        sample_results.append({
            "sample_index": idx,
            "prompt": prompt,
            "ground_truth": ground_truth,
            "prediction": prediction,
            "exact_match": metrics["exact_match"],
            "precision": metrics["precision"],
            "recall": metrics["recall"],
            "f1": metrics["f1"],
            "gt_labels": metrics["gt_labels"],
            "pred_labels": metrics["pred_labels"],
        })

        if (idx + 1) % 50 == 0 or (idx + 1) == eval_count:
            elapsed = time.time() - t0
            logger.info(
                f"  [{idx + 1}/{eval_count}] Mean F1 so far: "
                f"{(sum(f1_scores)/len(f1_scores)):.4f} | "
                f"Elapsed: {elapsed:.1f}s"
            )

    elapsed_total = time.time() - t0

    overall_metrics = {
        "dataset_name": dataset_name,
        "checkpoint_dir": str(checkpoint_dir or "default"),
        "dry_run": dry_run,
        "evaluated_samples": eval_count,
        "total_available_val_samples": total_val,
        "elapsed_seconds": round(elapsed_total, 2),
        "mean_exact_match": round(sum(em_scores) / len(em_scores), 4) if em_scores else 0.0,
        "mean_label_precision": round(sum(precisions) / len(precisions), 4) if precisions else 0.0,
        "mean_label_recall": round(sum(recalls) / len(recalls), 4) if recalls else 0.0,
        "mean_label_f1": round(sum(f1_scores) / len(f1_scores), 4) if f1_scores else 0.0,
        "sample_preview": sample_results[:5],
    }

    # Save report
    out_path = pathlib.Path(output_file) if output_file else (
        project_root / "data" / "reports" / "vlm_evaluation_results.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(overall_metrics, f, indent=2)

    logger.info(f"Evaluation report saved to {out_path}")
    logger.info("=== Overall Evaluation Results ===")
    logger.info(f"Mean Exact Match:     {overall_metrics['mean_exact_match']:.4f}")
    logger.info(f"Mean Label Precision: {overall_metrics['mean_label_precision']:.4f}")
    logger.info(f"Mean Label Recall:    {overall_metrics['mean_label_recall']:.4f}")
    logger.info(f"Mean Label F1:        {overall_metrics['mean_label_f1']:.4f}")
    logger.info("==================================")

    return overall_metrics


def main():
    parser = argparse.ArgumentParser(description="Evaluate Fine-Tuned VLM on BigEarthNet VQA")
    parser.add_argument(
        "--dataset_name",
        type=str,
        default="bigearthnet-medium",
        help="Dataset name under data/derived (e.g., bigearthnet-medium, bigearthnet-mini)",
    )
    parser.add_argument(
        "--checkpoint_dir",
        type=str,
        default=None,
        help="Directory containing trained LoRA adapter weights",
    )
    parser.add_argument(
        "--max_samples",
        type=int,
        default=None,
        help="Limit number of validation samples to evaluate",
    )
    parser.add_argument(
        "--output_file",
        type=str,
        default=None,
        help="Path to write evaluation results JSON",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Run without loading weights to test evaluation pipeline logic",
    )
    args = parser.parse_args()

    evaluate(
        dataset_name=args.dataset_name,
        checkpoint_dir=args.checkpoint_dir,
        max_samples=args.max_samples,
        output_file=args.output_file,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
