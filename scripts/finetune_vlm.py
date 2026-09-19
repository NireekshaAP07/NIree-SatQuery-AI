#!/usr/bin/env python3
"""
SatQuery AI — VLM Fine-tuning Script (Optimized for 6GB VRAM)
Uses QLoRA (4-bit quantization + LoRA) to fine-tune Google's PaliGemma 3B
on the generated BigEarthNet VQA dataset.

Usage:
  # Smoke-test (10 steps)
  python scripts/finetune_vlm.py --dataset_name bigearthnet-mini --test_run

  # Medium-scale training (recommended for RTX 4050 6 GB)
  python scripts/finetune_vlm.py \\
    --dataset_name bigearthnet-medium \\
    --lora_r 16 \\
    --lora_alpha 32 \\
    --gradient_accumulation_steps 16 \\
    --epochs 3
"""

import argparse
import json
import logging
import os
import pathlib
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
import torch

from datasets import load_from_disk
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoProcessor,
    BitsAndBytesConfig,
    PaliGemmaForConditionalGeneration,
    TrainingArguments,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Fine-tune PaliGemma with QLoRA")
    parser.add_argument("--dataset_name", type=str, default="bigearthnet-mini")
    parser.add_argument("--model_id", type=str, default="google/paligemma-3b-pt-224", help="HuggingFace model ID")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lora_r", type=int, default=8, help="LoRA rank. Use 16 for medium-scale training.")
    parser.add_argument("--lora_alpha", type=int, default=None, help="LoRA alpha. Defaults to 2×lora_r if not set.")
    parser.add_argument(
        "--gradient_accumulation_steps",
        type=int,
        default=8,
        help="Gradient accumulation steps (effective batch size = steps × per_device_batch). "
             "Use 16 for medium-scale training on 6 GB VRAM.",
    )
    parser.add_argument(
        "--save_dir",
        type=str,
        default=None,
        help="Directory to save LoRA weights. Defaults to data/weights/satquery-paligemma-lora.",
    )
    parser.add_argument("--test_run", action="store_true", help="Run for only 10 steps to test pipeline")
    args = parser.parse_args()

    # Resolve lora_alpha default
    if args.lora_alpha is None:
        args.lora_alpha = args.lora_r * 2

    from dotenv import load_dotenv
    load_dotenv()
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")

    project_root = pathlib.Path(__file__).parent.parent.resolve()
    data_dir = project_root / "data" / "derived" / f"{args.dataset_name}_vqa"
    output_dir = pathlib.Path(args.save_dir) if args.save_dir else (
        project_root / "data" / "weights" / "satquery-paligemma-lora"
    )
    checkpoint_dir = project_root / "data" / "tmp" / "checkpoints"

    if not (data_dir / "train").exists():
        logger.error(f"Dataset not found at {data_dir}. Run build_vlm_dataset.py first.")
        return

    logger.info("Loading dataset...")
    train_ds = load_from_disk(str(data_dir / "train"))
    val_ds = load_from_disk(str(data_dir / "val"))

    if args.test_run:
        logger.info("Test run enabled: restricting to 50 train / 10 val samples.")
        train_ds = train_ds.select(range(min(50, len(train_ds))))
        val_ds = val_ds.select(range(min(10, len(val_ds))))

    logger.info(
        f"Dataset loaded — train: {len(train_ds)} samples, val: {len(val_ds)} samples\n"
        f"LoRA config: r={args.lora_r}, alpha={args.lora_alpha}, "
        f"grad_accum={args.gradient_accumulation_steps}"
    )

    # 1. Setup 4-bit Quantization Config (Crucial for 6GB VRAM)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    model_id = args.model_id
    logger.info(f"Loading Base Model ({model_id}) in 4-bit...")

    try:
        processor = AutoProcessor.from_pretrained(model_id, token=hf_token)
        model = PaliGemmaForConditionalGeneration.from_pretrained(
            model_id,
            quantization_config=bnb_config,
            device_map="auto",
            token=hf_token,
        )
    except Exception as e:
        if "gated repo" in str(e) or "401" in str(e) or "restricted" in str(e):
            logger.error(
                f"\n{'='*70}\n"
                f"AUTHENTICATION REQUIRED FOR '{model_id}':\n"
                f"1. Visit https://huggingface.co/{model_id} and click 'Acknowledge license'.\n"
                f"2. Get your User Access Token at https://huggingface.co/settings/tokens\n"
                f"3. Add HF_TOKEN=your_token in .env or run: export HF_TOKEN=your_token\n"
                f"{'='*70}\n"
            )
            return
        raise

    # 2. Setup LoRA Config
    # We freeze the vision encoder and language model, and only train small adapter layers
    # PaliGemma's target modules for LoRA typically include self-attention layers
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        target_modules=["q_proj", "v_proj"],  # targeting attention layers
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 3. Formatting / Collating function for PaliGemma
    def collate_fn(examples):
        """Collator for PaliGemma: pairs prompt with target suffix and processes images."""
        texts = [
            f"<image>{example['prompt']}" if not example["prompt"].startswith("<image>") else example["prompt"]
            for example in examples
        ]
        labels = [example["text"] for example in examples]
        images = [example["image"].convert("RGB") for example in examples]

        # PaliGemma processor automatically creates input_ids, attention_mask, pixel_values,
        # and labels (with prompt masked to -100) when suffix is provided.
        # Enforce max_length=384 and truncation=True to prevent sequence blowup on 6GB VRAM.
        batch = processor(
            text=texts,
            images=images,
            suffix=labels,
            return_tensors="pt",
            padding="longest",
            max_length=384,
            truncation=True,
        )
        return batch

    # 4. Training Arguments
    # Aggressive VRAM saving settings for 6GB RTX 4050
    eval_steps = 200 if not args.test_run else 5
    save_steps = 200 if not args.test_run else 5

    training_args = TrainingArguments(
        output_dir=str(checkpoint_dir),
        per_device_train_batch_size=1,          # Crucial for 6GB VRAM
        per_device_eval_batch_size=1,           # Crucial for 6GB VRAM (prevents 8-batch OOM during eval)
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        gradient_checkpointing=True,            # Saves memory by recomputing activations
        gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="paged_adamw_32bit",
        save_steps=save_steps,
        save_total_limit=3,                     # Keep only the 3 best checkpoints
        logging_steps=10 if not args.test_run else 2,
        learning_rate=2e-4,
        max_steps=10 if args.test_run else -1,
        num_train_epochs=args.epochs,
        fp16=True,                              # Mixed precision
        remove_unused_columns=False,            # Important for multimodal
        eval_strategy="steps" if len(val_ds) > 0 else "no",
        eval_steps=eval_steps if len(val_ds) > 0 else None,
        eval_accumulation_steps=1,              # Offload evaluation tensors to host CPU to save VRAM
        load_best_model_at_end=True if len(val_ds) > 0 and not args.test_run else False,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        dataloader_num_workers=2,
        report_to="none",
    )

    logger.info("Starting training...")
    # 5. Trainer
    from transformers import Trainer
    trainer = Trainer(
        model=model,
        train_dataset=train_ds,
        eval_dataset=val_ds if len(val_ds) > 0 else None,
        data_collator=collate_fn,
        args=training_args,
    )

    trainer.train()

    logger.info(f"Training complete! Saving LoRA weights to {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.model.save_pretrained(str(output_dir))
    processor.save_pretrained(str(output_dir))

    # 6. Write training summary JSON
    log_history = trainer.state.log_history
    train_losses = [e["loss"] for e in log_history if "loss" in e]
    eval_losses = [e["eval_loss"] for e in log_history if "eval_loss" in e]

    summary = {
        "dataset_name": args.dataset_name,
        "model_id": model_id,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "epochs": args.epochs,
        "test_run": args.test_run,
        "train_samples": len(train_ds),
        "val_samples": len(val_ds),
        "final_train_loss": train_losses[-1] if train_losses else None,
        "best_eval_loss": min(eval_losses) if eval_losses else None,
        "total_steps": trainer.state.global_step,
        "output_dir": str(output_dir),
    }

    summary_path = output_dir / "training_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Training summary written to {summary_path}")
    logger.info(f"Summary: {json.dumps(summary, indent=2)}")

    logger.info("Done. To use this model in SatQuery, set VLM_MODEL_NAME in .env to:")
    logger.info(f"VLM_MODEL_NAME=./data/weights/satquery-paligemma-lora")


if __name__ == "__main__":
    main()
