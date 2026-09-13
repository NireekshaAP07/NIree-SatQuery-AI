# Generic VLM and LLM loader functions.
# ════════════════════════════════════════════════════════════════════════════════
# ██████████████████████████████████████████████████████████████████████████████
# ██                                                                          ██
# ██              ──── MODEL INJECTION POINT ────                             ██
# ██                                                                          ██
# ██  The actual model checkpoints are NOT loaded yet.                        ██
# ██  When you decide which model to use, do the following:                   ██
# ██                                                                          ██
# ██  1. Set VLM_MODEL_NAME in your .env file.                               ██
# ██     Example:  VLM_MODEL_NAME=Salesforce/blip2-opt-2.7b                  ██
# ██               VLM_MODEL_NAME=llava-hf/llava-1.5-7b-hf                  ██
# ██                                                                          ██
# ██  2. Set OPENAI_API_KEY (for GPT-4o orchestrator) in .env.               ██
# ██                                                                          ██
# ██  3. The load_vlm() and get_llm() functions below will automatically      ██
# ██     pick up your settings and load the correct model.                   ██
# ██                                                                          ██
# ██████████████████████████████████████████████████████████████████████████████
# ════════════════════════════════════════════════════════════════════════════════
from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.core.logger import get_logger

settings = get_settings()
logger = get_logger("model_provider")


# ── VLM LOADER & INFERENCE ───────────────────────────────────────────────────
@lru_cache(maxsize=1)
def load_vlm() -> tuple[Any, Any]:
    """
    Loads the Vision-Language Model (VLM) processor and model.
    Supports local fine-tuned LoRA checkpoints, PaliGemma, and generic HuggingFace VLMs.
    Uses 4-bit quantization on CUDA to strictly respect the 6GB VRAM constraint.

    Returns:
        (processor, model) — ready for inference.
    """
    from pathlib import Path

    model_name = settings.vlm_model_name

    if model_name == "PLACEHOLDER_SET_WHEN_MODEL_IS_CHOSEN":
        logger.warning(
            "vlm_not_configured",
            message="VLM_MODEL_NAME is not set. Returning stub. Set it in .env before running inference.",
        )
        return _stub_processor(), _stub_model()

    # Check if local path specified and whether it exists
    local_path = Path(model_name)
    if not local_path.is_absolute():
        repo_root = Path(__file__).parent.parent.parent.resolve()
        candidate = repo_root / model_name
        if candidate.exists():
            local_path = candidate

    if not local_path.exists() and (model_name.startswith("./") or model_name.startswith("/")):
        logger.warning(
            "vlm_checkpoint_not_found",
            path=str(local_path),
            message=f"Local weights path {local_path} not found. Returning stub until trained.",
        )
        return _stub_processor(), _stub_model()

    target_path_str = str(local_path if local_path.exists() else model_name)
    logger.info("loading_vlm", model=target_path_str, device=settings.vlm_device)

    import torch
    from transformers import AutoProcessor, BitsAndBytesConfig

    # 4-bit quantization config to guarantee fitting in 6GB VRAM
    use_cuda = settings.vlm_device == "cuda" and torch.cuda.is_available()
    bnb_config = (
        BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        if use_cuda
        else None
    )
    device_map = "auto" if use_cuda else "cpu"

    # Check if this is a PEFT LoRA adapter directory
    adapter_config_file = local_path / "adapter_config.json" if local_path.exists() and local_path.is_dir() else None
    if adapter_config_file and adapter_config_file.exists():
        import json
        from peft import PeftModel
        from transformers import PaliGemmaForConditionalGeneration

        with open(adapter_config_file, "r") as f:
            cfg = json.load(f)
        base_model_id = cfg.get("base_model_name_or_path", "google/paligemma-3b-pt-224")
        logger.info("loading_peft_vlm", base_model=base_model_id, adapter_dir=str(local_path))

        proc_source = str(local_path) if (local_path / "preprocessor_config.json").exists() else base_model_id
        processor = AutoProcessor.from_pretrained(proc_source)
        base_model = PaliGemmaForConditionalGeneration.from_pretrained(
            base_model_id,
            quantization_config=bnb_config,
            device_map=device_map,
            torch_dtype=torch.float16 if use_cuda else torch.float32,
        )
        model = PeftModel.from_pretrained(base_model, str(local_path))
        model.eval()
        logger.info("peft_vlm_loaded", adapter_path=str(local_path))
        return processor, model

    # Direct PaliGemma checkpoint
    if "paligemma" in model_name.lower():
        from transformers import PaliGemmaForConditionalGeneration
        processor = AutoProcessor.from_pretrained(target_path_str)
        model = PaliGemmaForConditionalGeneration.from_pretrained(
            target_path_str,
            quantization_config=bnb_config,
            device_map=device_map,
            torch_dtype=torch.float16 if use_cuda else torch.float32,
        )
        model.eval()
        logger.info("paligemma_loaded", model=model_name)
        return processor, model

    # Generic AutoModelForVision2Seq
    from transformers import AutoModelForVision2Seq
    processor = AutoProcessor.from_pretrained(target_path_str)
    model = AutoModelForVision2Seq.from_pretrained(
        target_path_str,
        quantization_config=bnb_config,
        torch_dtype="auto",
        device_map=device_map,
    )
    model.eval()
    logger.info("vlm_loaded", model=model_name)
    return processor, model


def generate_vlm_answer(processor: Any, model: Any, image: Any, prompt: str, max_new_tokens: int = 128) -> str:
    """
    Runs inference on an image and prompt using the loaded VLM processor and model.
    Handles PaliGemma token slicing as well as standard VLM generation.
    """
    # Graceful fallback for unconfigured or missing local weights
    if isinstance(model, _StubModel) or not hasattr(processor, "batch_decode"):
        return (
            "[VLM stub — model checkpoint not loaded or not yet fine-tuned. "
            "Run scripts/finetune_vlm.py or configure VLM_MODEL_NAME in .env]"
        )

    import torch
    from PIL import Image

    if isinstance(image, str):
        image = Image.open(image).convert("RGB")
    elif not isinstance(image, Image.Image):
        image = Image.fromarray(image).convert("RGB")

    inputs = processor(text=prompt, images=image, return_tensors="pt")
    
    device = getattr(model, "device", "cuda" if torch.cuda.is_available() else "cpu")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)

    if not isinstance(generated_ids, torch.Tensor):
        return str(generated_ids)

    # Slice out input tokens if model concatenates prompt + answer (e.g. PaliGemma)
    input_len = inputs["input_ids"].shape[1] if "input_ids" in inputs else 0
    new_tokens = generated_ids[:, input_len:]
    answer = processor.batch_decode(new_tokens, skip_special_tokens=True, clean_up_tokenization_spaces=True)[0]
    return answer.strip()


# ── LLM LOADER (ORCHESTRATOR) ─────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_llm() -> Any:
    """
    Returns the LLM used by the LangGraph orchestrator planner.
    Default: GPT-4o (best production results for agentic tasks).

    ── LLM INJECTION POINT ─────────────────────────────────────────────────────
    Set LLM_PROVIDER and the corresponding API key in .env.
    Supported providers: openai (default), gemini, ollama
    ─────────────────────────────────────────────────────────────────────────────
    """
    provider = settings.llm_provider
    model = settings.llm_model
    logger.info("loading_llm", provider=provider, model=model)

    if provider == "openai":
        if settings.openai_api_key == "PLACEHOLDER_API_KEY_TO_BE_PROVIDED":
            logger.warning("llm_api_key_missing", provider="openai")
            return _stub_llm()
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=settings.openai_api_key, temperature=0)

    elif provider == "gemini":
        if not settings.google_api_key:
            logger.warning("llm_api_key_missing", provider="gemini")
            return _stub_llm()
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            # Both legacy AIza... keys and new AQ. keys are passed as-is;
            # langchain-google-genai ≥4.0 supports both formats.
            return ChatGoogleGenerativeAI(
                model=model,
                google_api_key=settings.google_api_key,
                temperature=0,
            )
        except ImportError:
            logger.error(
                "langchain_google_genai_missing",
                message="Run: pip install langchain-google-genai>=4.0.0",
            )
            return _stub_llm()
        except Exception as e:
            logger.error("gemini_llm_init_failed", error=str(e))
            return _stub_llm()

    elif provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=model, base_url=settings.ollama_base_url, temperature=0)

    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}. Choose: openai | gemini | ollama")


# ── STUBS ──────────────────────────────────────────────────────────────────────

class _StubProcessor:
    """Stub processor returned when VLM_MODEL_NAME is not configured."""
    def __call__(self, *args, **kwargs) -> dict:
        return {}


class _StubModel:
    """Stub model returned when VLM_MODEL_NAME is not configured."""
    def generate(self, *args, **kwargs) -> list:
        return []


class _StubLLMResponse:
    """Mimics the AIMessage returned by real LangChain LLMs."""
    content: str = "[LLM stub — set GEMINI_API_KEY or OPENAI_API_KEY in .env to enable real inference]"

    def __str__(self) -> str:
        return self.content


class _StubLLM:
    """Stub LLM returned when API key is not yet provided."""
    def invoke(self, *args, **kwargs) -> _StubLLMResponse:
        return _StubLLMResponse()

    def with_structured_output(self, schema):
        """Returns a stub that raises a predictable exception instead of crashing unpredictably."""
        class _StructuredStub:
            def invoke(self, *a, **kw):
                raise RuntimeError("LLM not configured — set GEMINI_API_KEY or OPENAI_API_KEY in .env")
        return _StructuredStub()


def _stub_processor() -> _StubProcessor:
    return _StubProcessor()

def _stub_model() -> _StubModel:
    return _StubModel()

def _stub_llm() -> _StubLLM:
    return _StubLLM()
