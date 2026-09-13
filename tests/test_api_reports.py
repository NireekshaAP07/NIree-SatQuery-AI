"""
Integration tests for the Report Export API.

These tests verify the full export → download flow that was implemented
in Priority 1: POST /reports/export generates a file; GET /reports/{id}/download
streams it back with the correct Content-Type.
"""
from __future__ import annotations

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.query import Query
from app.models.analysis_run import AnalysisRun
from app.models.finding import Finding
from app.models.report import Report


async def _seed_report(db: AsyncSession) -> tuple[str, str]:
    """
    Seeds a minimal but valid chain of records needed for report export:
    Session → Query → AnalysisRun → Finding → Report.
    Returns (report_id, run_id).
    """
    session_id = uuid.uuid4().hex
    query_id = uuid.uuid4().hex
    run_id = uuid.uuid4().hex
    report_id = uuid.uuid4().hex
    finding_id = uuid.uuid4().hex

    db.add(Session(session_id=session_id))
    await db.flush()

    db.add(Query(query_id=query_id, session_id=session_id, text="test query", referenced_assets=[], status="completed"))
    await db.flush()

    db.add(AnalysisRun(run_id=run_id, query_id=query_id, workflow="vqa"))
    await db.flush()

    db.add(Finding(
        finding_id=finding_id,
        run_id=run_id,
        geometry="SRID=4326;POLYGON((77 12, 78 12, 78 13, 77 13, 77 12))",
        label="Urban Zone",
        answer="Dense urban settlement confirmed.",
        confidence=0.93,
        properties={"workflow": "vqa"},
    ))
    await db.flush()

    db.add(Report(
        report_id=report_id,
        run_id=run_id,
        session_id=session_id,
        summary="Comprehensive analysis reveals urban expansion across the study area.",
        evidence=[],
    ))
    await db.flush()

    return report_id, run_id


class TestReportExport:
    """Tests for POST /api/v1/reports/export"""

    async def test_export_json_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        """Exporting a report as JSON should return 200 with an export_uri."""
        report_id, _ = await _seed_report(db_session)
        response = await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "json"})
        assert response.status_code == 200
        body = response.json()
        assert body["format"] == "json"
        assert "export_uri" in body
        assert report_id in body["export_uri"]

    async def test_export_geojson_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        """Exporting a report as GeoJSON should return 200."""
        report_id, _ = await _seed_report(db_session)
        response = await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "geojson"})
        assert response.status_code == 200
        assert response.json()["format"] == "geojson"

    async def test_export_pdf_returns_200(self, client: AsyncClient, db_session: AsyncSession):
        """Exporting a report as PDF should return 200."""
        report_id, _ = await _seed_report(db_session)
        response = await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "pdf"})
        assert response.status_code == 200
        assert response.json()["format"] == "pdf"

    async def test_export_unsupported_format_returns_400(self, client: AsyncClient, db_session: AsyncSession):
        """Requesting an unknown format should return HTTP 400."""
        report_id, _ = await _seed_report(db_session)
        response = await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "docx"})
        assert response.status_code == 400

    async def test_export_nonexistent_report_returns_404(self, client: AsyncClient):
        """Exporting a report that doesn't exist should return HTTP 404."""
        response = await client.post("/api/v1/reports/export", json={"report_id": "nonexistent_id", "format": "json"})
        assert response.status_code == 404


class TestReportDownload:
    """Tests for GET /api/v1/reports/{report_id}/download"""

    async def test_download_json_has_correct_content_type(self, client: AsyncClient, db_session: AsyncSession):
        """Downloaded JSON report should have application/json content type."""
        report_id, _ = await _seed_report(db_session)
        await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "json"})

        dl = await client.get(f"/api/v1/reports/{report_id}/download?format=json")
        assert dl.status_code == 200
        assert "application/json" in dl.headers["content-type"]

    async def test_download_json_contains_report_fields(self, client: AsyncClient, db_session: AsyncSession):
        """Downloaded JSON should contain the report_id and findings array."""
        report_id, _ = await _seed_report(db_session)
        await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "json"})

        dl = await client.get(f"/api/v1/reports/{report_id}/download?format=json")
        assert dl.status_code == 200
        data = dl.json()
        assert data["report_id"] == report_id
        assert "findings" in data
        assert len(data["findings"]) >= 1

    async def test_download_geojson_is_feature_collection(self, client: AsyncClient, db_session: AsyncSession):
        """Downloaded GeoJSON should be a valid FeatureCollection."""
        report_id, _ = await _seed_report(db_session)
        await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "geojson"})

        dl = await client.get(f"/api/v1/reports/{report_id}/download?format=geojson")
        assert dl.status_code == 200
        data = dl.json()
        assert data["type"] == "FeatureCollection"
        assert isinstance(data["features"], list)

    async def test_download_pdf_returns_binary(self, client: AsyncClient, db_session: AsyncSession):
        """Downloaded PDF should return non-empty binary content."""
        report_id, _ = await _seed_report(db_session)
        await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "pdf"})

        dl = await client.get(f"/api/v1/reports/{report_id}/download?format=pdf")
        assert dl.status_code == 200
        assert "application/pdf" in dl.headers["content-type"]
        assert len(dl.content) > 0

    async def test_download_before_export_returns_404(self, client: AsyncClient, db_session: AsyncSession):
        """Downloading a report that hasn't been exported yet should return 404."""
        report_id, _ = await _seed_report(db_session)
        # NOTE: do NOT call /export first
        dl = await client.get(f"/api/v1/reports/{report_id}/download?format=json")
        assert dl.status_code == 404

    async def test_download_nonexistent_report_returns_404(self, client: AsyncClient):
        """Downloading a completely nonexistent report should return 404."""
        dl = await client.get("/api/v1/reports/nonexistent_id/download?format=json")
        assert dl.status_code == 404

    async def test_download_has_attachment_header(self, client: AsyncClient, db_session: AsyncSession):
        """Download response should have Content-Disposition: attachment."""
        report_id, _ = await _seed_report(db_session)
        await client.post("/api/v1/reports/export", json={"report_id": report_id, "format": "json"})

        dl = await client.get(f"/api/v1/reports/{report_id}/download?format=json")
        assert dl.status_code == 200
        assert "attachment" in dl.headers.get("content-disposition", "")
