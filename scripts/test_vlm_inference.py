#!/usr/bin/env python3
"""
SatQuery AI — VLM Inference Test Script
Tests loading the Vision-Language Model and running inference on a satellite image.
Validates that memory usage fits safely within 6GB VRAM.

Usage:
  python scripts/test_vlm_inference.py
  python scripts/test_vlm_inference.py --image data/previews/optical_asset_preview.png --prompt "Describe the land cover and water bodies in this satellite image."
"""

import argparse
import logging
import os
import pathlib
import sys
import time

project_root = pathlib.Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from PIL import Image
from app.core.config import get_settings
from app.core.model_provider import load_vlm, generate_vlm_answer

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Test VLM Inference on Satellite Imagery")
    parser.add_argument(
        "--image",
        type=str,
        default="data/previews/optical_asset_preview.png",
        help="Path to image file (PNG/JPEG/TIFF)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="What land cover types and structures are visible in this satellite image?",
        help="Question or prompt for the VLM",
    )
    parser.add_argument(
        "--max_tokens",
        type=int,
        default=64,
        help="Maximum new tokens to generate",
    )
    args = parser.parse_args()

    settings = get_settings()
    logger.info("=== SatQuery AI VLM Inference Test ===")
    logger.info(f"Configured Model: {settings.vlm_model_name}")
    logger.info(f"Configured Device: {settings.vlm_device}")

    # Check image
    img_path = project_root / args.image if not pathlib.Path(args.image).is_absolute() else pathlib.Path(args.image)
    if not img_path.exists():
        logger.warning(f"Image not found at {img_path}. Generating a synthetic RGB satellite test tile...")
        img = Image.new("RGB", (224, 224), color=(34, 139, 34)) # Forest green
    else:
        logger.info(f"Loading image from {img_path}")
        img = Image.open(str(img_path)).convert("RGB")

    # Measure load time and VRAM
    t0 = time.time()
    logger.info("Loading VLM (processor + model)...")
    processor, model = load_vlm()
    load_time = time.time() - t0
    logger.info(f"VLM loaded in {load_time:.2f}s")

    # Check GPU memory
    try:
        import torch
        if torch.cuda.is_available():
            allocated_mb = torch.cuda.memory_allocated() / (1024 ** 2)
            reserved_mb = torch.cuda.memory_reserved() / (1024 ** 2)
            logger.info(f"CUDA VRAM Allocated: {allocated_mb:.1f} MB | Reserved: {reserved_mb:.1f} MB")
            if reserved_mb > 5500:
                logger.warning("HIGH VRAM WARNING: Reserved memory exceeds 5.5 GB on 6GB GPU!")
            else:
                logger.info("VRAM is well within safe 6GB GPU boundaries.")
    except Exception as e:
        logger.debug(f"Could not read CUDA memory: {e}")

    # Run inference
    logger.info(f"Running inference with prompt: '{args.prompt}'")
    t1 = time.time()
    answer = generate_vlm_answer(processor, model, img, args.prompt, max_new_tokens=args.max_tokens)
    infer_time = time.time() - t1

    logger.info("=== Inference Result ===")
    logger.info(f"Answer: {answer}")
    logger.info(f"Inference Time: {infer_time:.2f}s")
    logger.info("=========================")


if __name__ == "__main__":
    main()
