"""Store source acquisitions in their original format."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260923_01"
down_revision = "20260921_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve the acquired file bytes and the registry metadata."""
    op.alter_column(
        "acquisizioni_fonti",
        "contenuto",
        existing_type=sa.Text(),
        type_=sa.LargeBinary(),
        postgresql_using="convert_to(contenuto, 'UTF8')",
    )
    op.add_column(
        "acquisizioni_fonti",
        sa.Column(
            "metadati",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Restore text storage when all stored source files are UTF-8 text."""
    op.drop_column("acquisizioni_fonti", "metadati")
    op.alter_column(
        "acquisizioni_fonti",
        "contenuto",
        existing_type=sa.LargeBinary(),
        type_=sa.Text(),
        postgresql_using="convert_from(contenuto, 'UTF8')",
    )
