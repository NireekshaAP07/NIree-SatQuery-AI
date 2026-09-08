#!/usr/bin/env python3
"""
SatQuery AI — Demo Data Seeder
==============================
One-command script to populate the database and storage with sample satellite
data so a new developer can immediately see a working dashboard.

Usage:
    python3 scripts/seed_demo.py                # seed with local sample_data/
    python3 scripts/seed_demo.py --reset        # wipe existing seed data first
    python3 scripts/seed_demo.py --dry-run      # print what would be inserted

Inserts:
  - 2 ImageAssets  (optical 2026 + SAR 2026 from sample_data/)
  - 1 Session      (demo session)
  - 2 Queries      (change detection + SAR fusion)
  - 2 AnalysisRuns
  - 4 Findings     (2 per run, with WGS84 PostGIS geometry)
  - 2 Reports      (one per run)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Ensure project root is on the path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logger import get_logger, setup_logging
from app.core.storage import get_storage
from app.models.image_asset import ImageAsset
from app.models.session import Session
from app.models.query import Query
from app.models.analysis_run import AnalysisRun
from app.models.finding import Finding
from app.models.report import Report
from app.schemas.assets import ImageModality

setup_logging()
logger = get_logger("seed_demo")

SAMPLE_DATA = Path(__file__).parent.parent / "sample_data"

# ── Deterministic IDs so re-running the seeder is idempotent ──────────────────
DEMO_SESSION_ID   = "demo0000000000000000000000000001"
DEMO_ASSET_OPT_ID = "demo0000000000000000000000000002"
DEMO_ASSET_SAR_ID = "demo0000000000000000000000000003"
DEMO_QUERY_CD_ID  = "demo0000000000000000000000000004"
DEMO_QUERY_SAR_ID = "demo0000000000000000000000000005"
DEMO_RUN_CD_ID    = "demo0000000000000000000000000006"
DEMO_RUN_SAR_ID   = "demo0000000000000000000000000007"
DEMO_REPORT_CD_ID = "demo0000000000000000000000000008"
DEMO_REPORT_SAR_ID= "demo0000000000000000000000000009"

# Representative WGS84 footprint covering the ISRO sample area (Bangalore region)
OPT_BBOX_WKT  = "SRID=4326;POLYGON((77.4 12.8, 77.8 12.8, 77.8 13.2, 77.4 13.2, 77.4 12.8))"
SAR_BBOX_WKT  = "SRID=4326;POLYGON((77.4 12.8, 77.8 12.8, 77.8 13.2, 77.4 13.2, 77.4 12.8))"
FINDING_1_WKT = "SRID=4326;POLYGON((77.5 12.9, 77.6 12.9, 77.6 13.0, 77.5 13.0, 77.5 12.9))"
FINDING_2_WKT = "SRID=4326;POLYGON((77.6 12.8, 77.7 12.8, 77.7 12.9, 77.6 12.9, 77.6 12.8))"
FINDING_3_WKT = "SRID=4326;POLYGON((77.5 13.0, 77.65 13.0, 77.65 13.1, 77.5 13.1, 77.5 13.0))"
FINDING_4_WKT = "SRID=4326;POLYGON((77.7 12.9, 77.8 12.9, 77.8 13.0, 77.7 13.0, 77.7 12.9))"


async def wipe_seed_data(db: AsyncSession) -> None:
    """Deletes all records with demo IDs (safe: only affects seed data)."""
    demo_ids = [
        DEMO_SESSION_ID, DEMO_ASSET_OPT_ID, DEMO_ASSET_SAR_ID,
        DEMO_QUERY_CD_ID, DEMO_QUERY_SAR_ID, DEMO_RUN_CD_ID, DEMO_RUN_SAR_ID,
        DEMO_REPORT_CD_ID, DEMO_REPORT_SAR_ID,
    ]
    logger.info("wiping_existing_seed_data")
    report_ids = "', '".join([DEMO_REPORT_CD_ID, DEMO_REPORT_SAR_ID])
    run_ids_str = f"'{DEMO_RUN_CD_ID}', '{DEMO_RUN_SAR_ID}'"
    query_ids_str = f"'{DEMO_QUERY_CD_ID}', '{DEMO_QUERY_SAR_ID}'"
    asset_ids_str = f"'{DEMO_ASSET_OPT_ID}', '{DEMO_ASSET_SAR_ID}'"
    # Delete in reverse FK order
    await db.execute(text(f"DELETE FROM reports WHERE report_id IN ('{report_ids}')"))
    await db.execute(text(f"DELETE FROM findings WHERE run_id IN ({run_ids_str})"))
    await db.execute(text(f"DELETE FROM analysis_runs WHERE run_id IN ({run_ids_str})"))
    await db.execute(text(f"DELETE FROM queries WHERE query_id IN ({query_ids_str})"))
    await db.execute(text(f"DELETE FROM image_assets WHERE asset_id IN ({asset_ids_str})"))
    await db.execute(text(f"DELETE FROM sessions WHERE session_id = '{DEMO_SESSION_ID}'"))
    await db.commit()
    logger.info("seed_data_wiped")


async def seed(dry_run: bool = False) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    storage = get_storage()

    async with session_factory() as db:
        # ── Check if already seeded ───────────────────────────────────────────
        existing = await db.execute(select(Session).where(Session.session_id == DEMO_SESSION_ID))
        if existing.scalars().first():
            logger.info("seed_already_present", msg="Demo data already exists. Run with --reset to re-seed.")
            return

        logger.info("seeding_demo_data", dry_run=dry_run)

        # ── Upload sample files to storage ────────────────────────────────────
        opt_file  = SAMPLE_DATA / "isro_optical_2026.tif"
        sar_file  = SAMPLE_DATA / "isro_sar_2026.tif"

        def _upload(path: Path, asset_id: str, subdir: str = "raw") -> str:
            if not path.exists():
                logger.warning("sample_file_missing", path=str(path))
                return f"local://{path}"
            data = path.read_bytes()
            if dry_run:
                return f"local://{path}"
            result = storage.save_upload(data, path.name, subdir=subdir)
            return str(result)

        opt_uri = _upload(opt_file, DEMO_ASSET_OPT_ID)
        sar_uri = _upload(sar_file, DEMO_ASSET_SAR_ID)
        logger.info("assets_uploaded", optical=opt_uri, sar=sar_uri)

        if dry_run:
            _print_dry_run_summary(opt_uri, sar_uri)
            return

        # ── Session ──────────────────────────────────────────────────────────
        demo_session = Session(session_id=DEMO_SESSION_ID, conversation_history=[
            {"role": "user", "content": "Compare the 2022 and 2026 satellite images of this area."},
            {"role": "assistant", "content": "Change detection analysis complete. Significant urban expansion detected in the north-eastern quadrant."},
        ])
        db.add(demo_session)
        await db.flush()
        logger.info("seeded_session", session_id=DEMO_SESSION_ID)

        # ── ImageAssets ───────────────────────────────────────────────────────
        db.add(ImageAsset(
            asset_id=DEMO_ASSET_OPT_ID,
            uri=opt_uri,
            modality=ImageModality.optical,
            crs="EPSG:32643",
            bbox=OPT_BBOX_WKT,
            width=512, height=512, band_count=3,
            file_size_bytes=opt_file.stat().st_size if opt_file.exists() else 0,
        ))
        db.add(ImageAsset(
            asset_id=DEMO_ASSET_SAR_ID,
            uri=sar_uri,
            modality=ImageModality.sar,
            crs="EPSG:32643",
            bbox=SAR_BBOX_WKT,
            width=512, height=512, band_count=2,
            file_size_bytes=sar_file.stat().st_size if sar_file.exists() else 0,
        ))
        await db.flush()
        logger.info("seeded_assets")

        # ── Query 1: Change Detection ─────────────────────────────────────────
        db.add(Query(
            query_id=DEMO_QUERY_CD_ID,
            session_id=DEMO_SESSION_ID,
            text="Compare the 2022 and 2026 satellite images of this area.",
            referenced_assets=[DEMO_ASSET_OPT_ID],
            status="completed",
        ))
        await db.flush()

        db.add(AnalysisRun(
            run_id=DEMO_RUN_CD_ID,
            query_id=DEMO_QUERY_CD_ID,
            workflow="change_detection",
            status="completed",
            duration_ms=4231.5,
        ))
        await db.flush()

        db.add(Finding(
            finding_id=uuid.uuid4().hex,
            run_id=DEMO_RUN_CD_ID,
            geometry=FINDING_1_WKT,
            label="Urban Expansion",
            answer="Significant new construction detected in north-eastern sector between 2022 and 2026.",
            confidence=0.94,
            properties={"workflow": "change_detection", "change_type": "Urban Expansion",
                        "before_state": "Open agricultural land", "after_state": "Dense residential blocks"},
        ))
        db.add(Finding(
            finding_id=uuid.uuid4().hex,
            run_id=DEMO_RUN_CD_ID,
            geometry=FINDING_2_WKT,
            label="Vegetation Loss",
            answer="Vegetative cover has been cleared in the south-eastern sector.",
            confidence=0.88,
            properties={"workflow": "change_detection", "change_type": "Vegetation Loss",
                        "before_state": "Dense tree canopy", "after_state": "Bare soil / cleared terrain"},
        ))
        await db.flush()

        db.add(Report(
            report_id=DEMO_REPORT_CD_ID,
            run_id=DEMO_RUN_CD_ID,
            session_id=DEMO_SESSION_ID,
            summary=(
                "Bi-temporal analysis of the study area (Bangalore region) between 2022 and 2026 "
                "reveals significant anthropogenic changes. Urban expansion dominates the north-eastern "
                "quadrant with 12% increase in built-up area. Concurrent vegetation loss of approximately "
                "8% observed in south-eastern zones, consistent with land-use conversion for development."
            ),
            evidence=[
                {"type": "image", "asset_id": DEMO_ASSET_OPT_ID, "label": "Optical 2026"},
            ],
        ))
        await db.flush()
        logger.info("seeded_change_detection_run")

        # ── Query 2: SAR Fusion ───────────────────────────────────────────────
        db.add(Query(
            query_id=DEMO_QUERY_SAR_ID,
            session_id=DEMO_SESSION_ID,
            text="Identify features using SAR and optical fusion for this region.",
            referenced_assets=[DEMO_ASSET_OPT_ID, DEMO_ASSET_SAR_ID],
            status="completed",
        ))
        await db.flush()

        db.add(AnalysisRun(
            run_id=DEMO_RUN_SAR_ID,
            query_id=DEMO_QUERY_SAR_ID,
            workflow="sar_fusion",
            status="completed",
            duration_ms=6712.3,
        ))
        await db.flush()

        db.add(Finding(
            finding_id=uuid.uuid4().hex,
            run_id=DEMO_RUN_SAR_ID,
            geometry=FINDING_3_WKT,
            label="Urban Double-Bounce Zone",
            answer="High SAR backscatter co-located with dense optical geometry confirms major urban infrastructure cluster.",
            confidence=0.91,
            properties={"workflow": "sar_fusion", "sar_evidence": "Strong double-bounce (>0.75 normalised intensity)",
                        "optical_evidence": "Regular grid pattern of high-reflectance structures"},
        ))
        db.add(Finding(
            finding_id=uuid.uuid4().hex,
            run_id=DEMO_RUN_SAR_ID,
            geometry=FINDING_4_WKT,
            label="Open Water Body",
            answer="Convergence of low SAR return and dark optical signature confirms a reservoir or water body.",
            confidence=0.89,
            properties={"workflow": "sar_fusion", "sar_evidence": "Very low backscatter (specular reflection)",
                        "optical_evidence": "Smooth dark surface, consistent with calm water"},
        ))
        await db.flush()

        db.add(Report(
            report_id=DEMO_REPORT_SAR_ID,
            run_id=DEMO_RUN_SAR_ID,
            session_id=DEMO_SESSION_ID,
            summary=(
                "SAR-Optical multimodal fusion of the study area confirms two dominant landscape features. "
                "A large urban double-bounce zone in the north indicates high-density built-up infrastructure, "
                "corroborated by geometric patterns in optical and strong SAR backscatter. A calm water body "
                "in the east is confirmed by specular SAR reflection and dark optical tone — likely a reservoir."
            ),
            evidence=[
                {"type": "image", "asset_id": DEMO_ASSET_OPT_ID, "label": "Optical 2026"},
                {"type": "image", "asset_id": DEMO_ASSET_SAR_ID, "label": "SAR 2026"},
            ],
        ))
        await db.commit()
        logger.info("seeded_sar_fusion_run")

    await engine.dispose()
    print("\n✅  Demo data seeded successfully!")
    print(f"   Session ID:  {DEMO_SESSION_ID}")
    print(f"   Optical:     {DEMO_ASSET_OPT_ID}")
    print(f"   SAR:         {DEMO_ASSET_SAR_ID}")
    print(f"   Reports:     {DEMO_REPORT_CD_ID}  /  {DEMO_REPORT_SAR_ID}")
    print("\n   Open the frontend at http://localhost:3000 to see the populated dashboard.")


def _print_dry_run_summary(opt_uri: str, sar_uri: str) -> None:
    print("\n🔎  DRY RUN — no data was written.\n")
    print("   Would create:")
    print(f"     Session        {DEMO_SESSION_ID}")
    print(f"     ImageAsset     {DEMO_ASSET_OPT_ID}  →  {opt_uri}")
    print(f"     ImageAsset     {DEMO_ASSET_SAR_ID}  →  {sar_uri}")
    print(f"     Query          {DEMO_QUERY_CD_ID}  (change_detection)")
    print(f"     Query          {DEMO_QUERY_SAR_ID}  (sar_fusion)")
    print(f"     AnalysisRun    {DEMO_RUN_CD_ID}")
    print(f"     AnalysisRun    {DEMO_RUN_SAR_ID}")
    print(f"     4 Findings     (2 per run, PostGIS POLYGON geometry)")
    print(f"     Report         {DEMO_REPORT_CD_ID}")
    print(f"     Report         {DEMO_REPORT_SAR_ID}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed SatQuery AI with demo data.")
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
        await seed(dry_run=args.dry_run)

    asyncio.run(_main())
