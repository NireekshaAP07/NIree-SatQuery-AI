# Alembic migration environment — wires SQLAlchemy models to the migration runner.
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base + all models so Alembic can detect every table.
from app.core.database import Base  # noqa: E402
import app.models  # noqa: E402  — registers all ORM classes onto Base.metadata

target_metadata = Base.metadata


def _get_sync_url() -> str:
    """Convert asyncpg URL → psycopg URL for Alembic's sync runner."""
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://").replace(
        "postgresql+asyncio://", "postgresql+psycopg://"
    )


def run_migrations_offline() -> None:
    """Generate SQL without a live connection (for dry-run / CI diffs)."""
    context.configure(
        url=_get_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_sync_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
