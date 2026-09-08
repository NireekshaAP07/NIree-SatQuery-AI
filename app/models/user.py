import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, String
from app.core.database import Base


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, default=lambda: uuid.uuid4().hex)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)
