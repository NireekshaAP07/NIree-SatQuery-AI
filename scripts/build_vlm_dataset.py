#!/usr/bin/env python3
"""
SatQuery AI — BigEarthNet VQA Dataset Builder
Loads the extracted BigEarthNet dataset and converts it into a HuggingFace VQA dataset
suitable for fine-tuning PaliGemma.

Usage:
  python scripts/build_vlm_dataset.py --dataset_name bigearthnet-mini
  python scripts/build_vlm_dataset.py --dataset_name bigearthnet-medium
  python scripts/build_vlm_dataset.py --dataset_name bigearthnet-medium --diversify
"""

import argparse
import json
import logging
import os
import pathlib
import random
import tarfile
import time

import gdown
import numpy as np
from datasets import Dataset, Features, Image as HFImage, Value
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# BigEarthNet Google Drive URLs (from jerpint/bigearthnet reference)
GDRIVE_URLS = {
    "bigearthnet-mini": "https://drive.google.com/file/d/1X2-NpZ4ExUooAi8tkCBWAlmHZAG_N3Ux/view?usp=sharing",
    "bigearthnet-medium": "https://drive.google.com/file/d/1YW4ugRQTl-YF_ZpLO7gIRSlHnB2Cwslz/view?usp=sharing",
    "bigearthnet-full": "https://drive.google.com/file/d/1isUcPQvCn1xc5GWEmPDOqj_l24QH2ZtA/view?usp=sharing",
}

# BigEarthNet 43-class labels (official list from jerpint/bigearthnet class_list.json)
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

# 19-class Corine Land Cover agglomerated labels (fallback)
BIGEARTHNET_LABELS_19 = [
    "Urban fabric",
    "Industrial or commercial units",
    "Arable land",
    "Permanent crops",
    "Pastures",
    "Complex cultivation patterns",
    "Agriculture + natural vegetation",
    "Agro-forestry areas",
    "Broad-leaved forest",
    "Coniferous forest",
    "Mixed forest",
    "Natural grassland and sparsely vegetated areas",
    "Moors, heathland and sclerophyllous vegetation",
    "Transitional woodland/shrub",
    "Beaches, dunes, sands",
    "Inland wetlands",
    "Coastal wetlands",
    "Inland waters",
    "Marine waters",
]


def download_data(dataset_dir: str, dataset_name: str) -> pathlib.Path:
    """Download and extract the specified dataset to dataset_dir if not already present."""
    assert dataset_name in GDRIVE_URLS, f"dataset_name '{dataset_name}' isn't available."
    dataset_path = pathlib.Path(os.path.join(dataset_dir, dataset_name))
    tar_fname = str(dataset_path.resolve()) + ".tar"

    if os.path.isdir(dataset_path):
        logger.info(f"Dataset already present at {dataset_path}, skipping download.")
        return dataset_path

    os.makedirs(dataset_dir, exist_ok=True)

    if not os.path.isfile(tar_fname):
        logger.info(f"Downloading {dataset_name} dataset to {tar_fname} ...")
        url = GDRIVE_URLS[dataset_name]
        gdown.download(url=url, output=str(tar_fname))

    logger.info(f"Extracting {tar_fname} to {dataset_dir} ...")
    with tarfile.open(tar_fname, "r") as tar:
        try:
            tar.extractall(path=dataset_dir, filter="data")
        except TypeError:
            tar.extractall(path=dataset_dir)

    logger.info(f"Successfully extracted {dataset_name} to {dataset_path}")
    return dataset_path


def create_qa_pairs(class_names: list, present_labels: list) -> list:
    """Generate question-answer pairs for the given labels for VLM fine-tuning.

    Returns a list of 4 QA dicts, one per template. Each has 'question' and 'answer' keys.
    """
    valid_labels = [class_names[i] for i in present_labels if 0 <= i < len(class_names)]
    if not valid_labels:
        labels_str = "no specific land cover features"
    else:
        labels_str = ", ".join(valid_labels)

    count = len(valid_labels)

    # Template 3: how many distinct land types?
    count_answer = (
        "no identifiable land cover types"
        if count == 0
        else f"{count} land cover type{'s' if count != 1 else ''}: {labels_str}"
    )

    # Template 4: is there urban land?
    urban_keywords = ("urban", "industrial", "road", "rail", "construction", "airport", "port", "sport", "leisure")
    has_urban = any(
        any(kw in lbl.lower() for kw in urban_keywords)
        for lbl in valid_labels
    )
    urban_answer = (
        f"Yes, this image contains urban or built-up areas including: {labels_str}."
        if has_urban
        else "No, this image does not contain significant urban or built-up land cover."
    )

    return [
        {
            "question": "What land cover types are visible in this satellite image?",
            "answer": labels_str,
        },
        {
            "question": "Describe the terrain and land cover features in this image.",
            "answer": f"The image shows {labels_str}.",
        },
        {
            "question": "How many distinct land cover types are present in this satellite image?",
            "answer": count_answer,
        },
        {
            "question": "Is there any urban or built-up land in this satellite image?",
            "answer": urban_answer,
        },
    ]


def process_split(split_path: pathlib.Path, max_samples: int = None, diversify: bool = False):
    """
    Load a BigEarthNet split directly from the extracted Deep Lake format
    and yield {'image': PIL.Image, 'prompt': str, 'text': str} dicts.

    Args:
        split_path: Path to the split directory (e.g., data/raw/bigearthnet/bigearthnet-medium/train).
        max_samples: Maximum number of source samples to process.
        diversify: If True, emit all 4 QA pairs per sample instead of a random one.
                   This multiplies effective dataset size by 4.
    """
    import deeplake

    # Check for Deep Lake version compatibility
    dl_ver = getattr(deeplake, "__version__", "unknown")
    try:
        major_ver = int(dl_ver.split(".")[0])
        if major_ver >= 4:
            raise RuntimeError(
                f"Installed deeplake version {dl_ver} is not compatible with BigEarthNet's lz4-compressed dataset. "
                f"Please install deeplake 3.x by running: pip install 'deeplake<4'"
            )
    except (ValueError, IndexError):
        pass

    logger.info(f"Loading split from {split_path} with deeplake {dl_ver}...")
    try:
        ds = deeplake.load(str(split_path), read_only=True, verbose=False)
    except Exception as e:
        logger.error(f"Failed to load dataset split at {split_path}: {e}")
        raise RuntimeError(
            f"Unable to load BigEarthNet split at {split_path}. "
            f"Ensure the dataset is fully extracted and deeplake<4 is installed: {e}"
        ) from e

    # Determine class taxonomy
    class_names = BIGEARTHNET_LABELS_43
    dataset_info_file = split_path / "dataset_info.json"
    if dataset_info_file.exists():
        try:
            with open(dataset_info_file, "r") as f:
                info = json.load(f)
            if "class_names" in info and info["class_names"]:
                class_names = list(info["class_names"])
                logger.info(f"Loaded {len(class_names)} class names from {dataset_info_file.name}")
        except Exception as e:
            logger.warning(f"Could not read {dataset_info_file}: {e}. Using BIGEARTHNET_LABELS_43.")
    elif hasattr(ds, "info") and hasattr(ds.info, "class_names") and ds.info.class_names:
        class_names = list(ds.info.class_names)

    total_samples = len(ds)
    n_samples = min(total_samples, max_samples) if max_samples else total_samples

    mode_str = "diversify (all 4 QA templates)" if diversify else "random QA template"
    logger.info(f"  Processing {n_samples} real BigEarthNet samples from {split_path.name} [{mode_str}]...")

    t0 = time.time()
    for idx, item in enumerate(ds):
        if max_samples and idx >= max_samples:
            break

        raw = item["data"].numpy()  # (3, 120, 120) uint16 in BGR order

        # Transpose (C, H, W) -> (H, W, C)
        if raw.ndim == 3 and raw.shape[0] == 3:
            raw = np.transpose(raw, (1, 2, 0))
            # BGR -> RGB conversion
            raw = raw[:, :, ::-1]

        # Contrast stretch 2% to 98% percentile into uint8 RGB
        p2, p98 = np.percentile(raw, (2, 98))
        if p98 > p2:
            norm = np.clip((raw - p2) / (p98 - p2) * 255.0, 0, 255).astype(np.uint8)
        else:
            norm = np.zeros_like(raw, dtype=np.uint8)

        pil_img = Image.fromarray(norm).convert("RGB")
        raw_labels = item["labels"].numpy().flatten().tolist()
        present_labels = [int(lbl) for lbl in raw_labels]

        qa_pairs = create_qa_pairs(class_names, present_labels)

        if diversify:
            for qa in qa_pairs:
                yield {"image": pil_img, "text": qa["answer"], "prompt": qa["question"]}
        else:
            qa = random.choice(qa_pairs)
            yield {"image": pil_img, "text": qa["answer"], "prompt": qa["question"]}

        # Progress logging every 2500 samples or final
        if (idx + 1) % 2500 == 0 or (idx + 1) == n_samples:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed if elapsed > 0 else 0
            eta = (n_samples - idx - 1) / rate if rate > 0 else 0
            logger.info(
                f"    [{idx + 1}/{n_samples}] {elapsed:.0f}s elapsed | "
                f"{rate:.1f} samples/s | ETA: {eta:.0f}s"
            )


def main():
    parser = argparse.ArgumentParser(description="Build BigEarthNet VQA Dataset for PaliGemma fine-tuning")
    parser.add_argument(
        "--dataset_name",
        type=str,
        default="bigearthnet-medium",
        choices=["bigearthnet-mini", "bigearthnet-medium", "bigearthnet-full"],
        help="Which version of BigEarthNet to process.",
    )
    parser.add_argument("--max_train", type=int, default=None, help="Max train samples (for debugging/testing).")
    parser.add_argument("--max_val", type=int, default=None, help="Max val samples (for debugging/testing).")
    parser.add_argument(
        "--diversify",
        action="store_true",
        help=(
            "Emit all 4 QA templates per sample instead of a random one. "
            "Multiplies effective dataset size by 4 at the cost of longer build time."
        ),
    )
    args = parser.parse_args()

    project_root = pathlib.Path(__file__).parent.parent.resolve()
    raw_dir = project_root / "data" / "raw" / "bigearthnet"
    out_dir = project_root / "data" / "derived" / f"{args.dataset_name}_vqa"

    if args.diversify:
        logger.info("--diversify enabled: all 4 QA templates will be emitted per sample (4× data size).")

    # 1. Check / extract dataset path (skips download if directory already exists)
    dataset_path = download_data(str(raw_dir), args.dataset_name)

    # 2. Process splits
    splits = ["train", "val"]

    features = Features({
        "image": HFImage(),
        "text": Value("string"),
        "prompt": Value("string"),
    })

    for split in splits:
        split_path = dataset_path / split
        if not split_path.exists():
            logger.warning(f"Split '{split}' not found at {split_path}, skipping.")
            continue

        limit = args.max_train if split == "train" else args.max_val
        logger.info(f"Building HF dataset for '{split}' split (limit={limit})...")

        def gen(s_path=split_path, s_limit=limit, s_diversify=args.diversify):
            yield from process_split(s_path, max_samples=s_limit, diversify=s_diversify)

        hf_ds = Dataset.from_generator(gen, features=features)
        out_split_dir = out_dir / split
        out_split_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Saving {len(hf_ds)} real BigEarthNet examples to {out_split_dir}")
        hf_ds.save_to_disk(str(out_split_dir))

    logger.info(f"Done! Real BigEarthNet VQA dataset successfully saved to {out_dir}")


if __name__ == "__main__":
    main()
