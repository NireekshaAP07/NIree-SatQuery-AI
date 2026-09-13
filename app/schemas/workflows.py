# Pydantic schemas for specialist workflow results (VQA, Grounding, etc.).
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class WorkflowType(str, Enum):
    vqa = "vqa"
    captioning = "captioning"
    grounding = "grounding"
    change_detection = "change_detection"
    sar_fusion = "sar_fusion"


class BoundingBox(BaseModel):
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    crs: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_box_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            x_min = data.get("x_min") if "x_min" in data else data.get("col_min", data.get("xmin"))
            y_min = data.get("y_min") if "y_min" in data else data.get("row_min", data.get("ymin"))
            x_max = data.get("x_max") if "x_max" in data else data.get("col_max", data.get("xmax"))
            y_max = data.get("y_max") if "y_max" in data else data.get("row_max", data.get("ymax"))
            if x_min is not None and y_min is not None and x_max is not None and y_max is not None:
                return {
                    "x_min": float(x_min),
                    "y_min": float(y_min),
                    "x_max": float(x_max),
                    "y_max": float(y_max),
                    "crs": data.get("crs"),
                }
        return data


class FindingResponse(BaseModel):
    finding_id: str
    workflow: WorkflowType
    label: Optional[str] = None
    answer: Optional[str] = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    bounding_boxes: Optional[list[BoundingBox]] = None
    change_classes: Optional[list[str]] = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: Optional[dict[str, Any]] = None


class WorkflowResultResponse(BaseModel):
    run_id: str
    query_id: str
    workflow: WorkflowType
    status: str
    findings: list[FindingResponse]
    trace: list[dict] = Field(default_factory=list, description="Machine-readable agent execution trace")
    error: Optional[str] = None
    duration_ms: Optional[float] = None
