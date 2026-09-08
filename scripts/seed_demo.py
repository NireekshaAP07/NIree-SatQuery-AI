#!/usr/bin/env python3
"""
SatQuery AI — Example Data Seeder
=================================
Populates the database and storage with realistic bi-temporal satellite imagery
(ISRO 2022 optical baseline vs. 2026 optical change + 2026 SAR radar observation)
along with pre-computed change detection findings, WGS84 geometries, and reports.

Usage:
    python3 scripts/seed_demo.py                # seed with sample_data/
    python3 scripts/seed_demo.py --reset        # wipe existing seed data first
    python3 scripts/seed_demo.py --dry-run      # print summary without writing
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logger import get_logger, setup_logging
from app.core.storage import get_storage
from app.geospatial.preview_generator import generate_rgb_preview
from app.models.analysis_run import AnalysisRun
from app.models.finding import Finding
from app.models.image_asset import ImageAsset
from app.models.query import Query
from app.models.report import Report
from app.models.session import Session
from app.schemas.assets import ImageModality
from app.schemas.workflows import WorkflowType

setup_logging()
logger = get_logger("seed_demo")

SAMPLE_DATA = Path(__file__).parent.parent / "sample_data"

# ── Deterministic IDs so re-running or referencing is predictable ─────────────
DEMO_SESSION_ID       = "demo0000000000000000000000000001"
DEMO_ASSET_OPT_22_ID  = "demo0000000000000000000000000002"
DEMO_ASSET_OPT_26_ID  = "demo0000000000000000000000000003"
DEMO_ASSET_SAR_26_ID  = "demo0000000000000000000000000004"

DEMO_QUERY_CD_ID      = "demo0000000000000000000000000005"
DEMO_QUERY_SAR_ID     = "demo0000000000000000000000000006"
DEMO_RUN_CD_ID        = "demo0000000000000000000000000007"
DEMO_RUN_SAR_ID       = "demo0000000000000000000000000008"
DEMO_REPORT_CD_ID     = "demo0000000000000000000000000009"
DEMO_REPORT_SAR_ID    = "demo0000000000000000000000000010"

# Exact WGS84 footprints calculated from UTM Zone 43N (EPSG:32643) bounds:
# min_x=200000, max_x=205120, min_y=1900000, max_y=1905120 (1024x1024, 5m/px)
BBOX_WKT = "SRID=4326;POLYGON((72.17936 17.16511, 72.22815 17.16511, 72.22815 17.21200, 72.17936 17.21200, 72.17936 17.16511))"

# Finding 1: New Residential Subdivision in north-western sector
# Pixel box: [80, 180, 650, 480]
FINDING_1_WKT = "SRID=4326;POLYGON((72.18345 17.18971, 72.21001 17.18971, 72.21001 17.20363, 72.18345 17.20363, 72.18345 17.18971))"

# Finding 2: Active Construction Site & Earthworks in western sector
# Pixel box: [60, 440, 280, 680]
FINDING_2_WKT = "SRID=4326;POLYGON((72.18264 17.18067, 72.19281 17.18067, 72.19281 17.19165, 72.18264 17.19165, 72.18264 17.18067))"

# Finding 3: High-Density Built Structure Cluster (SAR Fusion)
FINDING_3_WKT = "SRID=4326;POLYGON((72.18345 17.18971, 72.21001 17.18971, 72.21001 17.20363, 72.18345 17.20363, 72.18345 17.18971))"

# Finding 4: Meandering River Channel (SAR specular reflection)
FINDING_4_WKT = "SRID=4326;POLYGON((72.18000 17.19900, 72.22600 17.19900, 72.22600 17.21150, 72.18000 17.21150, 72.18000 17.19900))"


async def wipe_seed_data(db: AsyncSession) -> None:
    """Deletes all records with demo IDs and clears cached preview PNGs."""
    logger.info("wiping_existing_seed_data")

    # Delete in reverse FK dependency order
    await db.execute(text("DELETE FROM reports WHERE report_id LIKE 'demo%'"))
    await db.execute(text("DELETE FROM findings WHERE run_id LIKE 'demo%'"))
    await db.execute(text("DELETE FROM analysis_runs WHERE run_id LIKE 'demo%'"))
    await db.execute(text("DELETE FROM queries WHERE query_id LIKE 'demo%'"))
    await db.execute(text("DELETE FROM image_assets WHERE asset_id LIKE 'demo%'"))
    await db.execute(text("DELETE FROM sessions WHERE session_id LIKE 'demo%'"))
    await db.commit()

    # Clean derived preview caches for demo assets so no stale frames persist
    settings = get_settings()
    for pattern in (
        Path(settings.storage_local_root) / "derived" / "demo*.png",
        Path(settings.storage_local_root) / "previews" / "demo*.png",
    ):
        for f in glob.glob(str(pattern)):
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass

    logger.info("seed_data_wiped")


async def seed(dry_run: bool = False, force: bool = False) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    storage = get_storage()

    async with session_factory() as db:
        existing = await db.execute(select(Session).where(Session.session_id == DEMO_SESSION_ID))
        if existing.scalars().first():
            if not force:
                logger.info("seed_already_present", msg="Demo data already exists. Wiping to ensure real imagery...")
            await wipe_seed_data(db)

        logger.info("seeding_example_data", dry_run=dry_run)

        # ── 1. Upload satellite GeoTIFF files to storage ────────────────────────
        opt_22_file = SAMPLE_DATA / "isro_optical_2022.tif"
        opt_26_file = SAMPLE_DATA / "isro_optical_2026.tif"
        sar_26_file = SAMPLE_DATA / "isro_sar_2026.tif"

        def _upload(path: Path, subdir: str = "raw") -> str:
            if not path.exists():
                logger.warning("sample_file_missing", path=str(path))
                return f"local://{path}"
            data = path.read_bytes()
            if dry_run:
                return f"local://{path}"
            result = storage.save_upload(data, path.name, subdir=subdir, preserve_name=True)
            return str(result)

        opt_22_uri = _upload(opt_22_file)
        opt_26_uri = _upload(opt_26_file)
        sar_26_uri = _upload(sar_26_file)
        logger.info("assets_uploaded", opt_2022=opt_22_uri, opt_2026=opt_26_uri, sar_2026=sar_26_uri)

        if dry_run:
            _print_dry_run_summary(opt_22_uri, opt_26_uri, sar_26_uri)
            return

        # ── 2. Pre-generate web-renderable PNG previews ───────────────────────
        derived_dir = Path(settings.storage_local_root) / "derived"
        derived_dir.mkdir(parents=True, exist_ok=True)
        try:
            generate_rgb_preview(opt_22_file, derived_dir / f"{DEMO_ASSET_OPT_22_ID}_1024.png", max_dimension=1024)
            generate_rgb_preview(opt_26_file, derived_dir / f"{DEMO_ASSET_OPT_26_ID}_1024.png", max_dimension=1024)
            generate_rgb_preview(sar_26_file, derived_dir / f"{DEMO_ASSET_SAR_26_ID}_1024.png", max_dimension=1024)
            logger.info("cached_previews_pregenerated")
        except Exception as exc:
            logger.warning("pregenerate_previews_error", error=str(exc))

        # ── 3. Session ────────────────────────────────────────────────────────
        demo_session = Session(
            session_id=DEMO_SESSION_ID,
            conversation_history=[
                {
                    "role": "user",
                    "content": "Compare the 2022 and 2026 satellite observations to detect land cover changes and urban development.",
                },
                {
                    "role": "assistant",
                    "content": (
                        "Bi-temporal change detection complete. A major new residential subdivision "
                        "and adjacent construction earthworks have been detected in the north-western sector, "
                        "converting approximately 6 hectares of former agricultural fields into urban infrastructure."
                    ),
                },
            ],
        )
        db.add(demo_session)
        await db.flush()

        # ── 4. Image Assets ───────────────────────────────────────────────────
        # Asset 1: 2022 Optical baseline observation
        db.add(ImageAsset(
            asset_id=DEMO_ASSET_OPT_22_ID,
            uri=opt_22_uri,
            modality=ImageModality.optical,
            crs="EPSG:32643",
            bbox=BBOX_WKT,
            acquisition_time=datetime(2022, 3, 15, 10, 30, 0),
            width=1024,
            height=1024,
            band_count=3,
            file_size_bytes=opt_22_file.stat().st_size if opt_22_file.exists() else 0,
        ))

        # Asset 2: 2026 Optical follow-up observation (with urban expansion)
        db.add(ImageAsset(
            asset_id=DEMO_ASSET_OPT_26_ID,
            uri=opt_26_uri,
            modality=ImageModality.optical,
            crs="EPSG:32643",
            bbox=BBOX_WKT,
            acquisition_time=datetime(2026, 3, 15, 10, 30, 0),
            width=1024,
            height=1024,
            band_count=3,
            file_size_bytes=opt_26_file.stat().st_size if opt_26_file.exists() else 0,
        ))

        # Asset 3: 2026 Dual-polarization SAR radar observation
        db.add(ImageAsset(
            asset_id=DEMO_ASSET_SAR_26_ID,
            uri=sar_26_uri,
            modality=ImageModality.sar,
            crs="EPSG:32643",
            bbox=BBOX_WKT,
            acquisition_time=datetime(2026, 3, 16, 6, 15, 0),
            width=1024,
            height=1024,
            band_count=2,
            file_size_bytes=sar_26_file.stat().st_size if sar_26_file.exists() else 0,
        ))
        await db.flush()
        logger.info("seeded_image_assets")

        # ── 5. Query 1: Bi-temporal Change Detection (2022 vs 2026) ───────────
        db.add(Query(
            query_id=DEMO_QUERY_CD_ID,
            session_id=DEMO_SESSION_ID,
            text="Compare the 2022 and 2026 satellite observations to detect land cover changes and urban development.",
            referenced_assets=[DEMO_ASSET_OPT_22_ID, DEMO_ASSET_OPT_26_ID],
            status="completed",
        ))
        await db.flush()

        db.add(AnalysisRun(
            run_id=DEMO_RUN_CD_ID,
            query_id=DEMO_QUERY_CD_ID,
            workflow=WorkflowType.change_detection,
            status="completed",
            duration_ms=3140.0,
            trace=[
                {"step": "router", "decision": "bi_temporal_change_detection"},
                {"step": "co_registration", "status": "aligned_epsg_32643"},
                {"step": "gemini_vision_vlm", "model": "gemini-2.5-pro", "status": "detections_extracted"},
                {"step": "coordinate_transform", "status": "projected_to_wgs84"},
            ],
        ))
        await db.flush()

        # Finding 1: New Residential Subdivision
        db.add(Finding(
            finding_id=uuid.uuid4().hex,
            run_id=DEMO_RUN_CD_ID,
            geometry=FINDING_1_WKT,
            label="New Residential Subdivision",
            answer="Master-planned residential housing cluster constructed between 2022 and 2026 in the north-western sector, replacing former agricultural land.",
            confidence=0.96,
            properties={
                "workflow": "change_detection",
                "change_type": "Urban Expansion",
                "before_state": "Agricultural crop fields",
                "after_state": "Paved streets and multi-unit residential housing",
                "estimated_area_m2": 42500,
                "bounding_boxes": [
                    {"x_min": 80, "y_min": 180, "x_max": 650, "y_max": 480}
                ],
            },
        ))

        # Finding 2: Active Construction Site
        db.add(Finding(
            finding_id=uuid.uuid4().hex,
            run_id=DEMO_RUN_CD_ID,
            geometry=FINDING_2_WKT,
            label="Active Construction Site & Earthworks",
            answer="Commercial building foundation and ground clearing detected adjacent to the highway corridor in the western sector.",
            confidence=0.92,
            properties={
                "workflow": "change_detection",
                "change_type": "Land Clearing & Earthworks",
                "before_state": "Vegetated agricultural terrain",
                "after_state": "Excavated building foundations and access lanes",
                "estimated_area_m2": 18200,
                "bounding_boxes": [
                    {"x_min": 60, "y_min": 440, "x_max": 280, "y_max": 680}
                ],
            },
        ))
        await db.flush()

        db.add(Report(
            report_id=DEMO_REPORT_CD_ID,
            run_id=DEMO_RUN_CD_ID,
            session_id=DEMO_SESSION_ID,
            summary=(
                "Bi-temporal satellite analysis between the 2022 and 2026 observations reveals substantial "
                "anthropogenic landscape transformation. A new master-planned residential subdivision (approx. 4.25 ha) "
                "and an active commercial construction site (approx. 1.82 ha) have been developed over former cropland. "
                "The northern river hydrology, riparian corridor, and regional highway remain intact."
            ),
            evidence=[
                {"type": "image", "asset_id": DEMO_ASSET_OPT_22_ID, "label": "Baseline (2022)"},
                {"type": "image", "asset_id": DEMO_ASSET_OPT_26_ID, "label": "Observation (2026)"},
            ],
        ))
        await db.flush()
        logger.info("seeded_change_detection_run")

        # ── 6. Query 2: SAR-Optical Multi-Modal Fusion ────────────────────────
        db.add(Query(
            query_id=DEMO_QUERY_SAR_ID,
            session_id=DEMO_SESSION_ID,
            text="Analyze radar backscatter and optical characteristics using Sentinel-1 SAR and ISRO optical fusion.",
            referenced_assets=[DEMO_ASSET_OPT_26_ID, DEMO_ASSET_SAR_26_ID],
            status="completed",
        ))
        await db.flush()

        db.add(AnalysisRun(
            run_id=DEMO_RUN_SAR_ID,
            query_id=DEMO_QUERY_SAR_ID,
            workflow=WorkflowType.sar_fusion,
            status="completed",
            duration_ms=4820.0,
            trace=[
                {"step": "router", "decision": "sar_optical_fusion"},
                {"step": "sar_backscatter_calibration", "polarizations": ["VV", "VH"]},
                {"step": "gemini_multimodal_synthesis", "model": "gemini-2.5-pro", "status": "fused_signatures_analyzed"},
            ],
        ))
        await db.flush()

        db.add(Finding(
            finding_id=uuid.uuid4().hex,
            run_id=DEMO_RUN_SAR_ID,
            geometry=FINDING_3_WKT,
            label="High-Density Built Structure Cluster",
            answer="Strong double-bounce microwave backscatter co-located with high-reflectance optical rooftops confirms newly erected multi-story buildings.",
            confidence=0.94,
            properties={
                "workflow": "sar_fusion",
                "sar_evidence": "Intense double-bounce return (>0.82 normalized intensity)",
                "optical_evidence": "Rectilinear geometric rooftop signatures",
                "bounding_boxes": [
                    {"x_min": 80, "y_min": 180, "x_max": 650, "y_max": 480}
                ],
            },
        ))

        db.add(Finding(
            finding_id=uuid.uuid4().hex,
            run_id=DEMO_RUN_SAR_ID,
            geometry=FINDING_4_WKT,
            label="Meandering River Channel",
            answer="Very low radar backscatter due to specular reflection off smooth water surface confirms open water river channel.",
            confidence=0.95,
            properties={
                "workflow": "sar_fusion",
                "sar_evidence": "Near-zero microwave return (<0.08 normalized intensity)",
                "optical_evidence": "Dark winding natural watercourse with riparian tree margins",
                "bounding_boxes": [
                    {"x_min": 20, "y_min": 10, "x_max": 980, "y_max": 280}
                ],
            },
        ))
        await db.flush()

        db.add(Report(
            report_id=DEMO_REPORT_SAR_ID,
            run_id=DEMO_RUN_SAR_ID,
            session_id=DEMO_SESSION_ID,
            summary=(
                "SAR-Optical multimodal fusion confirms high structural density in the newly built north-western "
                "development zone via distinct microwave corner-reflector signatures. The winding river course in the "
                "north is independently validated by specular microwave non-return. Fusion demonstrates 100% agreement "
                "between radar backscatter and optical spectral classifications."
            ),
            evidence=[
                {"type": "image", "asset_id": DEMO_ASSET_OPT_26_ID, "label": "Optical (2026)"},
                {"type": "image", "asset_id": DEMO_ASSET_SAR_26_ID, "label": "SAR Radar (2026)"},
            ],
        ))
        await db.commit()
        logger.info("seeded_sar_fusion_run")

    await engine.dispose()
    print("\n✅  Real-world satellite example data seeded successfully!")
    print(f"   Session ID:     {DEMO_SESSION_ID}")
    print(f"   Optical 2022:   {DEMO_ASSET_OPT_22_ID} (Baseline)")
    print(f"   Optical 2026:   {DEMO_ASSET_OPT_26_ID} (Observation)")
    print(f"   SAR Radar 2026: {DEMO_ASSET_SAR_26_ID} (Multi-modal)")
    print(f"   Reports:        {DEMO_REPORT_CD_ID} / {DEMO_REPORT_SAR_ID}")
    print("\n   Open http://localhost:3000/compare to view the real-world satellite comparison.")


def _print_dry_run_summary(opt_22: str, opt_26: str, sar_26: str) -> None:
    print("\n🔎  DRY RUN — no data was written.\n")
    print("   Would create:")
    print(f"     Session        {DEMO_SESSION_ID}")
    print(f"     ImageAsset     {DEMO_ASSET_OPT_22_ID} (Optical 2022) -> {opt_22}")
    print(f"     ImageAsset     {DEMO_ASSET_OPT_26_ID} (Optical 2026) -> {opt_26}")
    print(f"     ImageAsset     {DEMO_ASSET_SAR_26_ID} (SAR Radar 2026) -> {sar_26}")
    print(f"     Query          {DEMO_QUERY_CD_ID}  (change_detection)")
    print(f"     Query          {DEMO_QUERY_SAR_ID}  (sar_fusion)")
    print(f"     AnalysisRun    {DEMO_RUN_CD_ID}")
    print(f"     AnalysisRun    {DEMO_RUN_SAR_ID}")
    print(f"     4 Findings     (2 per run, with WGS84 and pixel bounding boxes)")
    print(f"     Report         {DEMO_REPORT_CD_ID}")
    print(f"     Report         {DEMO_REPORT_SAR_ID}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed SatQuery AI with realistic satellite example data.")
    parser.add_argument("--reset", action="store_true", help="Wipe existing seed data first")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be inserted without writing")
    args = parser.parse_args()

    async def _main():
        if args.reset and not args.dry_run:
            settings = get_settings()
            engine = create_async_engine(settings.database_url, echo=False)
            session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with session_factory() as db:
                await wipe_seed_data(db)
            await engine.dispose()
        await seed(dry_run=args.dry_run, force=args.reset)

    asyncio.run(_main())
