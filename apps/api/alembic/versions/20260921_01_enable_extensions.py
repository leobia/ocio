"""Enable PostgreSQL extensions required by OCIO."""

from __future__ import annotations

from alembic import op

revision = "20260921_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Enable search extensions."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_textsearch")


def downgrade() -> None:
    """Remove search extensions."""
    op.execute("DROP EXTENSION IF EXISTS pg_textsearch")
    op.execute("DROP EXTENSION IF EXISTS vector")
