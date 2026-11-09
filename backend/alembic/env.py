"""Alembic runs this for every migration command. Connects to DATABASE_URL from .env."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.db import database_url
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """alembic upgrade head --sql: print the SQL instead of running it."""
    context.configure(url=database_url() or "postgresql+psycopg://", target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = database_url()
    if not url:
        raise SystemExit("DATABASE_URL is not set in .env")
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
