# SAR / Multimodal Agent: combines SAR with optical context for joint interpretation.
# Integrated with GeminiVisionClient (SAR_FUSION_PROMPT) and CoordinateTransformer.
# Falls back to deterministic numpy CV backscatter analysis if GEMINI_API_KEY is absent.
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.agents.state import AgentState
from app.core.logger import get_logger

logger = get_logger("agents.sar")


def run(state: AgentState) -> dict[str, Any]:
    """
    Fuses an optical image with a SAR image for joint multimodal analysis.

    ── FLOW ────────────────────────────────────────────────────────────────────
    1. Extracts raster metadata (CRS, affine transform, dimensions) from the
       OPTICAL image (asset_ids[0]) via RasterHandler.
    2. Generates 8-bit RGB PNG previews from BOTH assets via PreviewGenerator.
    3. Sends [optical_preview, sar_preview] + SAR_FUSION_PROMPT to GeminiVisionClient.
       If GEMINI_API_KEY is missing, the client runs the CV backscatter fallback.
    4. Transforms each returned [ymin, xmin, ymax, xmax] box to WGS84 GeoJSON
       polygon via CoordinateTransformer (anchored to optical CRS).
    5. Returns structured findings with fusion interpretation and real confidence.

    ── DATASET INJECTION POINT ──────────────────────────────────────────────
    Expected input: TWO images — one optical, one SAR.
    Optical image:  data/raw/<optical_image.tif>   (asset_ids[0])
    SAR image:      data/raw/<sar_image.tif>        (asset_ids[1])
    Both images should cover the same geographic area.
    SAR imagery should be in a standard format (e.g., Sentinel-1 GRD GeoTIFF).
    ─────────────────────────────────────────────────────────────────────────

    ── MODEL INJECTION POINT ────────────────────────────────────────────────
    GeminiVisionClient uses GEMINI_API_KEY from .env.
    If not configured, the client runs deterministic SAR backscatter thresholding.
    To use a dedicated SAR model, update app/core/model_provider.py.
    ─────────────────────────────────────────────────────────────────────────
    """
    asset_ids = state.get("asset_ids", [])
    asset_paths = state.get("asset_paths", {})
    query_text = state.get("query_text", "Perform SAR-Optical multimodal fusion analysis.")
    query_id = state.get("query_id", "SYSTEM")

    if len(asset_ids) < 2:
        return {
            "status": "error",
            "error": "SAR fusion requires 2 assets: optical (asset_ids[0]) and SAR (asset_ids[1]).",
            "findings": [],
        }

    optical_path = asset_paths.get(asset_ids[0])
    sar_path = asset_paths.get(asset_ids[1])

    if not optical_path or not sar_path:
        return {"status": "error", "error": "One or both asset paths not found.", "findings": []}

    # Graceful fallback: if files are remote URIs or do not exist on disk
    for label, path in (("optical", optical_path), ("sar", sar_path)):
        if not Path(str(path)).is_file():
            logger.warning("sar_agent_asset_not_on_disk", label=label, path=path)
            return {
                "status": "error",
                "error": (
                    f"Asset file ({label}) is not available on local disk (path: {path}). "
                    "Upload real raster files to run SAR fusion."
                ),
                "findings": [],
            }


    try:
        # ── 1. Import geospatial & AI modules ─────────────────────────────────
        from app.geospatial.raster_handler import extract_raster_metadata
        from app.geospatial.preview_generator import generate_rgb_preview
        from app.geospatial.coordinate_transform import CoordinateTransformer
        from app.ai.gemini_client import GeminiVisionClient
        from app.ai.prompts import SAR_FUSION_PROMPT

        # ── 2. Extract raster metadata (optical anchors geo coordinates) ──────
        optical_meta = extract_raster_metadata(optical_path)
        coord_transformer = CoordinateTransformer(
            width=optical_meta.width,
            height=optical_meta.height,
            affine_transform=optical_meta.transform,
            crs_str=optical_meta.crs_str,
            crs_epsg=optical_meta.crs_epsg,
        )

        # ── 3. Generate PNG previews for VLM ──────────────────────────────────
        preview_dir = Path("./data/previews")
        optical_preview = str(
            generate_rgb_preview(optical_path, preview_dir / f"{asset_ids[0]}_preview.png")
        )
        sar_preview = str(
            generate_rgb_preview(sar_path, preview_dir / f"{asset_ids[1]}_sar_preview.png")
        )

        # ── 4. Call Gemini VLM with BOTH previews (or offline CV fallback) ────
        vision_client = GeminiVisionClient()
        full_prompt = f"{SAR_FUSION_PROMPT}\n\nUSER QUERY:\n{query_text}"
        response_json = vision_client.generate_json_response(
            prompt=full_prompt,
            images=[optical_preview, sar_preview],  # Optical first, SAR second
            job_id=str(query_id),
        )

        fused_findings_raw = response_json.get("fused_findings", [])
        fusion_summary = response_json.get("fusion_summary", "SAR-Optical fusion analysis completed.")
        overall_confidence = float(response_json.get("overall_confidence", 0.80))

        # ── 5. Transform pixel bboxes to WGS84 GeoJSON features ───────────────
        findings = []
        geojson_features = []

        for item in fused_findings_raw:
            finding_id = f"sar_{uuid.uuid4().hex[:8]}"
            label = item.get("label", "SAR-Optical Feature")
            box_2d = item.get("box_2d", [100, 100, 500, 500])
            confidence = float(item.get("confidence", overall_confidence))
            optical_ev = item.get("optical_evidence", "")
            sar_ev = item.get("sar_evidence", "")
            fusion_interp = item.get("fusion_interpretation", "")

            description = f"{fusion_interp} | Optical: {optical_ev} | SAR: {sar_ev}"

            geojson_feat = coord_transformer.transform_box_to_geojson(
                box=box_2d,
                label=label,
                confidence=confidence,
                properties={
                    "finding_id": finding_id,
                    "optical_evidence": optical_ev,
                    "sar_evidence": sar_ev,
                    "fusion_interpretation": fusion_interp,
                },
            )
            geojson_features.append(geojson_feat)

            findings.append(
                {
                    "finding_id": finding_id,
                    "workflow": "sar_fusion",
                    "label": label,
                    "answer": fusion_summary,
                    "confidence": confidence,
                    "description": description,
                    "bounding_boxes": geojson_feat["properties"].get("pixel_bbox"),
                    "geojson_feature": geojson_feat,
                    "evidence_refs": asset_ids[:2],
                }
            )

        visualization_geojson = {"type": "FeatureCollection", "features": geojson_features}

        logger.info(
            "sar_fusion_complete",
            optical=optical_path,
            sar=sar_path,
            findings_count=len(findings),
            overall_confidence=overall_confidence,
            georeferenced=coord_transformer.is_georeferenced,
        )

        return {
            "status": "ok",
            "findings": findings,
            "fusion_summary": fusion_summary,
            "overall_confidence": overall_confidence,
            "visualization_geojson": visualization_geojson,
            "raster_metadata": optical_meta.to_dict(),
        }

    except Exception as exc:
        logger.error("sar_fusion_failed", error=str(exc))
        return {"status": "error", "error": str(exc), "findings": []}
