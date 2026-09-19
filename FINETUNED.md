# SatQuery AI — Fine-Tuned Vision-Language Model (VLM)

> [!NOTE]
> **Training Status: COMPLETED ✅**
> The model has been successfully fine-tuned on the `bigearthnet-medium` dataset (25,000 train / 10,000 validation samples) for **3 full epochs (4,689 steps)**.
> - **Final Training Loss**: `0.1576`
> - **Best Validation Loss**: `0.1583`
> - **Adapter Location**: `data/weights/satquery-paligemma-lora/`
> - **Ready for Deployment**: See [CLOUD_DEPLOYMENT.md](file:///home/kishanravi/SatQuery_AI/CLOUD_DEPLOYMENT.md#72-transfer-and-verify-fine-tuned-model-weights) for copying weights to the Oracle production VM.

This guide walks you through fine-tuning **Google PaliGemma 3B** on the **BigEarthNet** satellite dataset using **4-bit QLoRA**, specifically tailored to run comfortably within **6 GB VRAM** on an **NVIDIA GeForce RTX 4050 Laptop GPU**.

---

## 1. Overview & Architecture

SatQuery AI uses a Vision-Language Model to interpret satellite imagery and answer user queries about land cover, infrastructure, water bodies, and terrain features.

- **Base Model**: `google/paligemma-3b-pt-224` (3 Billion parameters)
- **Quantization**: 4-bit NF4 (`bitsandbytes`) with double quantization and `float16` compute
- **Adaptation**: LoRA targeting attention projection layers (`q_proj`, `v_proj`)
- **Dataset**: BigEarthNet Sentinel-2 multispectral patches (B2, B3, B4 in RGB)
- **VRAM Footprint**: Under **4.5 GB peak VRAM**, leaving ample headroom on 6 GB GPUs

---

## 2. Prerequisites & Environment Setup

### 2.1 Hardware Requirements
- **GPU**: NVIDIA RTX 4050 Laptop GPU (6 GB VRAM) or equivalent CUDA-enabled GPU
- **RAM**: 16 GB system memory
- **Storage**:
  - ~1 GB for `bigearthnet-mini` (testing/validation)
  - ~5 GB for `bigearthnet-medium` (recommended for final training)

### 2.2 Install GPU Dependencies
Make sure you are in the project virtual environment:

```bash
source venv/bin/activate
pip install -r requirements-gpu.txt
```

Verify CUDA and BitsAndBytes:
```bash
python -c "import torch, bitsandbytes; print('CUDA Available:', torch.cuda.is_available(), '| GPU:', torch.cuda.get_device_name(0))"
```

### 2.3 Hugging Face Token (Required for PaliGemma)
`google/paligemma-3b-pt-224` is a gated model on Hugging Face. Setting up access is free:

1. Visit [https://huggingface.co/google/paligemma-3b-pt-224](https://huggingface.co/google/paligemma-3b-pt-224) and click **Acknowledge license**.
2. Generate an access token at [https://huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) (read access is sufficient).
3. Add the token to your `.env` file:
   ```env
   HF_TOKEN=hf_yourHuggingFaceTokenHere
   ```
   *(Or export it in your shell: `export HF_TOKEN=hf_yourHuggingFaceTokenHere`)*

---

## 3. Step-by-Step Training & Evaluation Workflow

### Step 1: Download & Build the VQA Dataset

The dataset builder script downloads the official BigEarthNet tarballs (from the IVADO/Deep Lake reference), extracts the 120×120 Sentinel-2 patches, stretches contrast, and pairs them with question-answer prompts based on the 43-class Corine land-cover taxonomy.

#### A. Mini Dataset (Pipeline Validation)
Recommended for your first run to confirm all components work:
```bash
python scripts/build_vlm_dataset.py --dataset_name bigearthnet-mini
```
*Outputs:* Hugging Face dataset saved to `data/derived/bigearthnet-mini_vqa/` (train & val splits).

#### B. Medium Dataset (Production Training)
When ready to train the production model:
```bash
python scripts/build_vlm_dataset.py --dataset_name bigearthnet-medium
```
*Optional 4× Data Diversification:*
```bash
python scripts/build_vlm_dataset.py --dataset_name bigearthnet-medium --diversify
```
*Outputs:* Hugging Face dataset saved to `data/derived/bigearthnet-medium_vqa/`.

---

### Step 2: Run QLoRA Fine-Tuning

The training script automatically applies memory optimizations for your RTX 4050 6 GB GPU:
- `per_device_train_batch_size=1`
- `gradient_accumulation_steps=16` (effective batch size of 16 for medium)
- `gradient_checkpointing=True` (activation recomputation)
- `optim="paged_adamw_32bit"`
- Best checkpoint tracked by `eval_loss` and saved automatically

#### A. Sanity Check Run (10 Steps)
Runs a quick 10-step loop on 50 samples to verify memory limits and pipeline execution:
```bash
python scripts/finetune_vlm.py --dataset_name bigearthnet-mini --test_run
```

#### B. Medium-Scale Fine-Tuning (Recommended)
Train the model for 3 epochs with LoRA rank 16:
```bash
python scripts/finetune_vlm.py \
  --dataset_name bigearthnet-medium \
  --lora_r 16 \
  --lora_alpha 32 \
  --gradient_accumulation_steps 16 \
  --epochs 3
```

When training completes, the adapter weights, processor configuration, and training summary will be saved to:
```
data/weights/satquery-paligemma-lora/
├── adapter_config.json
├── adapter_model.safetensors
├── preprocessor_config.json
└── training_summary.json
```

---

### Step 3: Run Model Evaluation

Evaluate the fine-tuned model against the validation split to compute Exact Match (EM), Label Recall, Label Precision, and Label F1:

```bash
# Dry run verification (fast test without loading GPU model):
python scripts/evaluate_vlm.py --dataset_name bigearthnet-mini --max_samples 10 --dry_run

# Full evaluation on medium validation split:
python scripts/evaluate_vlm.py --dataset_name bigearthnet-medium
```

*Outputs:* Report saved to `data/reports/vlm_evaluation_results.json` containing:
- `mean_exact_match`
- `mean_label_precision`
- `mean_label_recall`
- `mean_label_f1`
- Sample previews with prompt, prediction, and ground truth

---

### Step 4: Test Interactive VLM Inference

Verify that the fine-tuned model loads properly, performs inference on a satellite tile, and stays within the 6 GB VRAM budget:

```bash
python scripts/test_vlm_inference.py \
  --image data/previews/optical_asset_preview.png \
  --prompt "What land cover types and terrain features are visible in this image?"
```

The script will log:
- Total load time
- CUDA VRAM allocated & reserved (MB)
- Generated answer
- Inference latency

---

### Step 5: Integrate with SatQuery AI Backend

Your `.env` file is already pre-configured to point to the local weights directory:

```env
VLM_MODEL_NAME=./data/weights/satquery-paligemma-lora
VLM_DEVICE=cuda
```

Start the SatQuery AI FastAPI server:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The application will automatically detect `data/weights/satquery-paligemma-lora/adapter_config.json`, load PaliGemma 3B in 4-bit, mount your LoRA adapter on CUDA, and route queries from specialist agents through your local model.

---

## 4. Useful Options & CLI Flags

### `scripts/build_vlm_dataset.py`
| Argument | Default | Description |
|---|---|---|
| `--dataset_name` | `bigearthnet-mini` | Options: `bigearthnet-mini`, `bigearthnet-medium`, `bigearthnet-full` |
| `--max_train` | `None` | Restrict number of training samples for debugging |
| `--max_val` | `None` | Restrict number of validation samples for debugging |
| `--diversify` | `False` | Emit all 4 QA templates per sample instead of random 1 (4× dataset augmentation) |

### `scripts/finetune_vlm.py`
| Argument | Default | Description |
|---|---|---|
| `--dataset_name` | `bigearthnet-mini` | Dataset folder under `data/derived/` |
| `--model_id` | `google/paligemma-3b-pt-224` | Base Hugging Face model |
| `--epochs` | `3` | Number of training epochs |
| `--lora_r` | `8` | LoRA rank (use `16` for medium-scale training) |
| `--lora_alpha` | `2*lora_r` | LoRA alpha scaling factor |
| `--gradient_accumulation_steps` | `8` | Gradient accumulation steps (use `16` for medium) |
| `--save_dir` | `None` | Custom output directory (defaults to `data/weights/satquery-paligemma-lora`) |
| `--test_run` | `False` | Run only 10 steps to test pipeline |

### `scripts/evaluate_vlm.py`
| Argument | Default | Description |
|---|---|---|
| `--dataset_name` | `bigearthnet-medium` | Dataset folder under `data/derived/` |
| `--checkpoint_dir` | `None` | Override LoRA checkpoint directory |
| `--max_samples` | `None` | Limit evaluation to first N validation samples |
| `--output_file` | `None` | Path to custom output JSON report |
| `--dry_run` | `False` | Run test evaluation without loading GPU model |

---

## 5. Troubleshooting & FAQ

### Q: I get `401 Client Error: Cannot access gated repo`
**Fix**: Ensure you clicked **Acknowledge license** at [https://huggingface.co/google/paligemma-3b-pt-224](https://huggingface.co/google/paligemma-3b-pt-224) while logged in to Hugging Face, and set `HF_TOKEN=your_token` in `.env`.

### Q: CUDA Out of Memory (OOM) during training
**Fix**:
1. Check that no other process is using the GPU: `nvidia-smi`
2. Ensure `gradient_checkpointing=True` and `per_device_train_batch_size=1` (default in `finetune_vlm.py`).
3. If necessary, increase `gradient_accumulation_steps=16` in `finetune_vlm.py`.

### Q: Can I run unit tests to verify the VLM pipeline?
**Fix**: Yes, run:
```bash
PYTHONPATH=. pytest tests/test_vlm_pipeline.py -v --noconftest
```
All tests validate stubs, quantization configuration, QA pair generation, and inference slicing.
