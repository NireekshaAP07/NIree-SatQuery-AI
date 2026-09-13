#!/usr/bin/env python3
"""
SatQuery AI — VLM Fine-tuning Script (Optimized for 6GB VRAM)
Uses QLoRA (4-bit quantization + LoRA) to fine-tune Google's PaliGemma 3B
on the generated BigEarthNet VQA dataset.

Usage:
  python scripts/finetune_vlm.py --dataset_name bigearthnet-mini
"""

import argparse
import logging
import os
import pathlib
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
    parser.add_argument("--test_run", action="store_true", help="Run for only 10 steps to test pipeline")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN")

    project_root = pathlib.Path(__file__).parent.parent.resolve()
    data_dir = project_root / "data" / "derived" / f"{args.dataset_name}_vqa"
    output_dir = project_root / "data" / "weights" / "satquery-paligemma-lora"

    if not (data_dir / "train").exists():
        logger.error(f"Dataset not found at {data_dir}. Run build_vlm_dataset.py first.")
        return

    logger.info("Loading dataset...")
    train_ds = load_from_disk(str(data_dir / "train"))
    val_ds = load_from_disk(str(data_dir / "val"))
    
    if args.test_run:
        logger.info("Test run enabled: restricting to 50 samples.")
        train_ds = train_ds.select(range(min(50, len(train_ds))))
        val_ds = val_ds.select(range(min(10, len(val_ds))))

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
        r=8, 
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"], # targeting attention layers
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM"
    )
    
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 3. Formatting / Collating function for PaliGemma
    def collate_fn(examples):
        """Collator for PaliGemma: pairs prompt with target suffix and processes images."""
        texts = [example["prompt"] for example in examples]
        labels = [example["text"] for example in examples]
        images = [example["image"].convert("RGB") for example in examples]

        # PaliGemma processor automatically creates input_ids, attention_mask, pixel_values,
        # and labels (with prompt masked to -100) when suffix is provided.
        batch = processor(
            text=texts,
            images=images,
            suffix=labels,
            return_tensors="pt",
            padding="longest",
        )
        return batch

    # 4. Training Arguments
    # Aggressive VRAM saving settings for 6GB RTX 4050
    training_args = TrainingArguments(
        output_dir=str(project_root / "data" / "tmp" / "checkpoints"),
        per_device_train_batch_size=1,      # Crucial for 6GB VRAM
        gradient_accumulation_steps=8,      # Effectively batch_size=8
        gradient_checkpointing=True,        # Saves memory by recomputing activations
        optim="paged_adamw_32bit",
        save_steps=100 if not args.test_run else 5,
        logging_steps=10 if not args.test_run else 2,
        learning_rate=2e-4,
        max_steps=10 if args.test_run else -1,
        num_train_epochs=args.epochs,
        fp16=True,                          # Mixed precision
        remove_unused_columns=False,        # Important for multimodal
        eval_strategy="steps" if len(val_ds) > 0 else "no",
        eval_steps=100 if not args.test_run else 5,
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
    trainer.model.save_pretrained(str(output_dir))
    processor.save_pretrained(str(output_dir))
    
    logger.info("Done. To use this model in SatQuery, set VLM_MODEL_NAME in .env to:")
    logger.info(f"VLM_MODEL_NAME=./data/weights/satquery-paligemma-lora")

if __name__ == "__main__":
    main()
