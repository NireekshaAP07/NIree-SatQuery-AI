"""
SatQuery AI — VLM Functionality & Pipeline Tests
Validates the VLM loader, inference helper, dataset generator, and QLoRA configuration.
"""

import pytest
import numpy as np
from PIL import Image
from unittest.mock import MagicMock, patch

from app.core.model_provider import load_vlm, generate_vlm_answer, _StubProcessor, _StubModel
from scripts.build_vlm_dataset import create_qa_pairs


def test_stub_vlm_fallback():
    """Verify that when VLM checkpoint is missing or stubbed, graceful stubs are returned."""
    with patch("app.core.model_provider.settings.vlm_model_name", "PLACEHOLDER_SET_WHEN_MODEL_IS_CHOSEN"):
        # Clear lru_cache for test
        load_vlm.cache_clear()
        processor, model = load_vlm()
        assert isinstance(processor, _StubProcessor)
        assert isinstance(model, _StubModel)
        load_vlm.cache_clear()


def test_missing_local_checkpoint_returns_stub():
    """Verify that a nonexistent local weights path gracefully returns stub instead of crashing."""
    with patch("app.core.model_provider.settings.vlm_model_name", "./data/weights/nonexistent-model"):
        load_vlm.cache_clear()
        processor, model = load_vlm()
        assert isinstance(processor, _StubProcessor)
        assert isinstance(model, _StubModel)
        load_vlm.cache_clear()


def test_generate_vlm_answer_mock():
    """Test the VLM inference helper with mock processor and model."""
    import torch

    mock_processor = MagicMock()
    mock_model = MagicMock()
    # device must be a real string so tensor .to(device) works
    mock_model.device = "cpu"

    # Simulate processor output (real tensors so .to("cpu") works)
    dummy_input_ids = torch.tensor([[1, 2, 3]])
    mock_processor.return_value = {
        "input_ids": dummy_input_ids,
        "pixel_values": torch.zeros((1, 3, 224, 224)),
    }

    # Simulate model generating 2 new tokens [4, 5]
    mock_model.generate.return_value = torch.tensor([[1, 2, 3, 4, 5]])
    mock_processor.batch_decode.return_value = ["Dense forest, Water bodies"]

    test_img = Image.new("RGB", (224, 224), color="green")
    answer = generate_vlm_answer(mock_processor, mock_model, test_img, "What is in this image?")

    assert answer == "Dense forest, Water bodies"
    mock_processor.assert_called_once()
    mock_model.generate.assert_called_once()


def test_create_qa_pairs():
    """Verify BigEarthNet VQA question-answer pair synthesis."""
    classes = [
        "Continuous urban fabric",
        "Discontinuous urban fabric",
        "Industrial or commercial units",
        "Arable land",
        "Coniferous forest"
    ]
    present = [0, 4] # Urban + Coniferous forest

    pairs = create_qa_pairs(classes, present)
    assert len(pairs) == 4
    assert "Continuous urban fabric" in pairs[0]["answer"]
    assert "Coniferous forest" in pairs[0]["answer"]
    assert pairs[0]["question"].startswith("What land cover")

    # Empty labels case
    empty_pairs = create_qa_pairs(classes, [])
    assert "no specific land cover features" in empty_pairs[0]["answer"]


def test_evaluate_vlm_metrics():
    """Verify metrics computation in evaluate_vlm."""
    from scripts.evaluate_vlm import compute_sample_metrics, extract_labels_from_text

    candidates = ["Continuous urban fabric", "Coniferous forest", "Water bodies"]
    text = "The image shows Continuous urban fabric and Coniferous forest."
    extracted = extract_labels_from_text(text, candidates)
    assert "Continuous urban fabric" in extracted
    assert "Coniferous forest" in extracted
    assert "Water bodies" not in extracted

    # Sample metrics: perfect match
    gt = "Continuous urban fabric, Coniferous forest"
    pred = "Continuous urban fabric, Coniferous forest"
    metrics = compute_sample_metrics(gt, pred, candidates)
    assert metrics["exact_match"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0

    # Sample metrics: partial match
    gt = "Continuous urban fabric, Coniferous forest"
    pred = "The area contains Coniferous forest and Water bodies"
    metrics = compute_sample_metrics(gt, pred, candidates)
    assert metrics["exact_match"] == 0.0
    assert metrics["recall"] == 0.5  # 1 out of 2 ground truth labels found
    assert metrics["precision"] == 0.5  # 1 out of 2 predicted labels is correct
    assert metrics["f1"] == 0.5


def test_vlm_6gb_vram_quantization_config():
    """Verify that 4-bit BitsAndBytesConfig is correctly configured for 6GB VRAM."""
    from transformers import BitsAndBytesConfig
    import torch

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    assert bnb_config.load_in_4bit is True
    assert bnb_config.bnb_4bit_quant_type == "nf4"
    assert bnb_config.bnb_4bit_use_double_quant is True
    assert bnb_config.bnb_4bit_compute_dtype == torch.float16
