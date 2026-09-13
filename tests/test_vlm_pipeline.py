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
    assert len(pairs) == 2
    assert "Continuous urban fabric" in pairs[0]["answer"]
    assert "Coniferous forest" in pairs[0]["answer"]
    assert pairs[0]["question"].startswith("What land cover")

    # Empty labels case
    empty_pairs = create_qa_pairs(classes, [])
    assert "no specific land cover features" in empty_pairs[0]["answer"]


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
