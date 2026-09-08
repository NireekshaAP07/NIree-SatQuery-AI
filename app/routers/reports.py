import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json
import io
from fastapi.responses import Response

from app.core.storage import get_storage
from fpdf import FPDF

from app.core.logger import get_logger
from app.schemas.reports import ExportRequest, ExportResponse, ReportListResponse, ReportResponse
from app.core.database import get_db
from app.models.report import Report
from app.models.finding import Finding

router = APIRouter(prefix="/reports", tags=["Reports & Export"])
logger = get_logger("router.reports")


@router.get(
    "/{report_id}",
    response_model=ReportResponse,
    summary="Retrieve a structured analysis report (FR-010)",
)
async def get_report(report_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).where(Report.report_id == report_id))
    report = result.scalars().first()
    
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Report '{report_id}' not found.")
        
    return ReportResponse(
        report_id=report.report_id,
        run_id=report.run_id,
        session_id=report.session_id,
        summary=report.summary,
        evidence=report.evidence,
        export_uri=report.export_uri,
        created_at=report.created_at
    )


@router.get(
    "/session/{session_id}",
    response_model=ReportListResponse,
    summary="List all reports for a session (FR-011)",
)
async def list_reports(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).where(Report.session_id == session_id))
    reports = result.scalars().all()
    
    count_result = await db.execute(select(func.count(Report.report_id)).where(Report.session_id == session_id))
    total = count_result.scalar_one_or_none() or 0
    
    return ReportListResponse(
        reports=[
            ReportResponse(
                report_id=r.report_id,
                run_id=r.run_id,
                session_id=r.session_id,
                summary=r.summary,
                evidence=r.evidence,
                export_uri=r.export_uri,
                created_at=r.created_at
            ) for r in reports
        ],
        total=total
    )


@router.post(
    "/export",
    response_model=ExportResponse,
    summary="Export a report in the requested format (FR-014)",
)
async def export_report(body: ExportRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).where(Report.report_id == body.report_id))
    report = result.scalars().first()
    
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Report '{body.report_id}' not found.")
    
    if body.format not in ("json", "pdf", "geojson"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported format. Use: json | pdf | geojson")

    # Fetch findings with geometry as GeoJSON string
    findings_result = await db.execute(
        select(Finding, func.ST_AsGeoJSON(Finding.geometry).label('geom_json'))
        .where(Finding.run_id == report.run_id)
    )
    findings_data = findings_result.all()

    # Generate bytes based on format
    if body.format == "json":
        file_bytes = _generate_json(report, findings_data)
    elif body.format == "geojson":
        file_bytes = _generate_geojson(report, findings_data)
    elif body.format == "pdf":
        file_bytes = _generate_pdf(report, findings_data)
    else:
        file_bytes = b""

    # Save to storage
    storage = get_storage()
    filename = f"{report.report_id}.{body.format}"
    storage.save_derived(file_bytes, filename)
    
    export_uri = f"/api/v1/reports/{report.report_id}/download?format={body.format}"
    
    report.export_uri = export_uri
    await db.commit()
    
    logger.info("report_exported", report_id=body.report_id, format=body.format)
    return ExportResponse(report_id=body.report_id, format=body.format, export_uri=export_uri)


@router.get(
    "/{report_id}/download",
    summary="Download an exported report",
)
async def download_report(report_id: str, format: str = "json", db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Report).where(Report.report_id == report_id))
    report = result.scalars().first()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
        
    storage = get_storage()
    key = f"derived/{report_id}.{format}"
    try:
        file_bytes = storage.get_object_bytes(key)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exported file not found on storage.")
        
    media_types = {
        "json": "application/json",
        "geojson": "application/geo+json",
        "pdf": "application/pdf"
    }
    
    return Response(
        content=file_bytes,
        media_type=media_types.get(format, "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="report_{report_id}.{format}"'}
    )

def _generate_json(report: Report, findings_data: list) -> bytes:
    data = {
        "report_id": report.report_id,
        "run_id": report.run_id,
        "summary": report.summary,
        "evidence": report.evidence,
        "findings": [
            {
                "finding_id": f.finding_id,
                "label": f.label,
                "answer": f.answer,
                "confidence": f.confidence,
                "properties": f.properties
            } for f, _ in findings_data
        ]
    }
    return json.dumps(data, indent=2).encode("utf-8")

def _generate_geojson(report: Report, findings_data: list) -> bytes:
    features = []
    for f, geom_json in findings_data:
        geom = json.loads(geom_json) if geom_json else None
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "finding_id": f.finding_id,
                "label": f.label,
                "answer": f.answer,
                "confidence": f.confidence,
                "workflow": f.properties.get("workflow", "") if f.properties else ""
            }
        })
    fc = {
        "type": "FeatureCollection",
        "properties": {
            "report_id": report.report_id,
            "summary": report.summary
        },
        "features": features
    }
    return json.dumps(fc, indent=2).encode("utf-8")

def _generate_pdf(report: Report, findings_data: list) -> bytes:
    from fpdf.enums import XPos, YPos
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=16)
    pdf.cell(0, 10, text="SatQuery AI Analysis Report", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.ln(5)
    
    pdf.set_font("helvetica", size=12)
    pdf.multi_cell(0, 10, text=report.summary)
    pdf.ln(10)
    
    pdf.set_font("helvetica", style="B", size=14)
    pdf.cell(0, 10, text="Findings:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font("helvetica", size=11)
    for f, _ in findings_data:
        label_text = f.answer if f.answer else f.label
        text = f"- [{f.confidence:.2f}] {label_text}"
        pdf.multi_cell(0, 8, text=text)
        
    return bytes(pdf.output())


async def store_report(db: AsyncSession, run_id: str, session_id: str, summary: str, evidence: list[dict]) -> str:
    """Internal helper called by the Report Agent to persist a final report."""
    report_id = uuid.uuid4().hex
    
    report = Report(
        report_id=report_id,
        run_id=run_id,
        session_id=session_id,
        summary=summary,
        evidence=evidence
    )
    db.add(report)
    await db.commit()
    
    logger.info("report_stored", report_id=report_id, run_id=run_id)
    return report_id
