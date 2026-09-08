"""finding details: answer and properties columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-08

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add answer (VQA / captioning text) and properties (bounding_boxes, change_classes, etc.)
    op.add_column("findings", sa.Column("answer", sa.String(), nullable=True))
    op.add_column("findings", sa.Column("properties", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default="{}"))


def downgrade() -> None:
    op.drop_column("findings", "properties")
    op.drop_column("findings", "answer")
