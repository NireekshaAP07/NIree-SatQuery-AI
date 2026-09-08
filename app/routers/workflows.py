import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.logger import get_logger
from app.models.analysis_run import AnalysisRun
from app.models.finding import Finding
from app.schemas.workflows import FindingResponse, WorkflowResultResponse, WorkflowType

router = APIRouter(prefix="/workflows", tags=["Specialist Workflows"])
logger = get_logger("router.workflows")


@router.get(
    "/{run_id}",
    response_model=WorkflowResultResponse,
    summary="Get workflow result by run ID (FR-005 to FR-009)",
)
async def get_workflow_result(run_id: str, db: AsyncSession = Depends(get_db)):
    """Returns the structured result of a completed specialist workflow run."""
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.run_id == run_id))
    run = result.scalars().first()
    
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Run '{run_id}' not found.")
        
    findings_result = await db.execute(
        select(Finding, func.ST_AsGeoJSON(Finding.geometry).label("geojson"))
        .where(Finding.run_id == run_id)
    )
    findings = findings_result.all()
    
    return WorkflowResultResponse(
        run_id=run.run_id,
        query_id=run.query_id,
        workflow=run.workflow,
        status=run.status,
        findings=[
            FindingResponse(
                finding_id=f.finding_id,
                workflow=run.workflow,
                label=f.label,
                answer=f.answer,
                confidence=f.confidence,
                bounding_boxes=f.properties.get("bounding_boxes") if f.properties else None,
                change_classes=f.properties.get("change_classes") if f.properties else None,
                metadata=f.properties,
                evidence_refs=f.evidence_refs or [],
            ) for f, geojson in findings
        ],
        trace=run.trace or [],
        error=run.error,
        duration_ms=run.duration_ms
    )


@router.get(
    "/query/{query_id}",
    response_model=list[WorkflowResultResponse],
    summary="List all workflow runs for a query",
)
async def list_runs_for_query(query_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.query_id == query_id))
    runs = result.scalars().all()
    
    responses = []
    for run in runs:
        findings_result = await db.execute(
            select(Finding, func.ST_AsGeoJSON(Finding.geometry).label("geojson"))
            .where(Finding.run_id == run.run_id)
        )
        findings = findings_result.all()
        responses.append(
            WorkflowResultResponse(
                run_id=run.run_id,
                query_id=run.query_id,
                workflow=run.workflow,
                status=run.status,
                findings=[
                    FindingResponse(
                        finding_id=f.finding_id,
                        workflow=run.workflow,
                        label=f.label,
                        answer=f.answer,
                        confidence=f.confidence,
                        bounding_boxes=f.properties.get("bounding_boxes") if f.properties else None,
                        change_classes=f.properties.get("change_classes") if f.properties else None,
                        metadata=f.properties,
                        evidence_refs=f.evidence_refs or [],
                    ) for f, geojson in findings
                ],
                trace=run.trace or [],
                error=run.error,
                duration_ms=run.duration_ms
            )
        )
    return responses


async def store_workflow_result(
    db: AsyncSession,
    query_id: str,
    workflow: WorkflowType,
    findings: list[Any],
    trace: list[dict],
    duration_ms: Optional[float] = None,
    error: Optional[str] = None,
) -> str:
    """
    Internal helper called by the orchestrator to persist a workflow result.
    Returns the generated run_id.
    """
    run_id = uuid.uuid4().hex
    
    run = AnalysisRun(
        run_id=run_id,
        query_id=query_id,
        workflow=workflow,
        status="failed" if error else "completed",
        trace=trace,
        error=error,
        duration_ms=duration_ms
    )
    db.add(run)
    
    for f in findings:
        f_dict = f.model_dump() if isinstance(f, BaseModel) else f
        
        properties = f_dict.get("metadata") or {}
        boxes = f_dict.get("bounding_boxes") or []
        box_2d = f_dict.get("box_2d")
        if box_2d and not boxes:
            boxes = [box_2d]
            
        geometry_wkt = None
        if boxes:
            properties["bounding_boxes"] = boxes
            # Use the first box to create a PostGIS POLYGON WKT
            b = boxes[0]
            if isinstance(b, dict) and "x_min" in b:
                xmin, ymin = b["x_min"], b["y_min"]
                xmax, ymax = b["x_max"], b["y_max"]
                geometry_wkt = f"POLYGON(({xmin} {ymin}, {xmax} {ymin}, {xmax} {ymax}, {xmin} {ymax}, {xmin} {ymin}))"

        if "change_classes" in f_dict:
            properties["change_classes"] = f_dict["change_classes"]
            
        finding = Finding(
            finding_id=uuid.uuid4().hex,
            run_id=run_id,
            label=f_dict.get("label"),
            answer=f_dict.get("answer"),
            properties=properties,
            confidence=f_dict.get("confidence", 1.0),
            evidence_refs=f_dict.get("evidence_refs", []),
            geometry=geometry_wkt
        )
        db.add(finding)
        
    await db.commit()
    logger.info("workflow_result_stored", run_id=run_id, workflow=workflow.value, error=bool(error))
    return run_id


# ── GRACEFUL FAILURE HANDLERS ─────────────────────────────────────────────────
# Called by the orchestrator when a workflow cannot complete (FR-015).

async def handle_unsupported_modality(db: AsyncSession, query_id: str, workflow: WorkflowType, modality: str) -> str:
    """Stores a failed run record for unsupported image modalities."""
    return await store_workflow_result(
        db=db,
        query_id=query_id,
        workflow=workflow,
        findings=[],
        trace=[{"step": "modality_check", "result": "unsupported", "modality": modality}],
        error=f"Modality '{modality}' is not supported by the {workflow.value} workflow.",
    )


async def handle_low_confidence(db: AsyncSession, query_id: str, workflow: WorkflowType, confidence: float) -> str:
    """Stores a warning run record when model confidence falls below threshold."""
    return await store_workflow_result(
        db=db,
        query_id=query_id,
        workflow=workflow,
        findings=[],
        trace=[{"step": "confidence_check", "confidence": confidence, "threshold": 0.4}],
        error=f"Result confidence ({confidence:.2f}) is below acceptable threshold. Result withheld.",
    )
