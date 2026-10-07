"""per-whitelist-entry TLS requirement

Revision ID: 20261007_0009_whitelist_tls
Revises: 20261007_0008_hardening_gm
Create Date: 2026-10-07 00:00:00

  - ip_whitelist.tls_required — MAIL FROM is refused on unencrypted sessions
    unless the entry explicitly allows plain SMTP (legacy devices). Existing
    entries become TLS-only; re-allow plain SMTP per entry where needed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20261007_0009_whitelist_tls"
down_revision = "20261007_0008_hardening_gm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ip_whitelist") as batch:
        batch.add_column(
            sa.Column("tls_required", sa.Boolean, nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("ip_whitelist") as batch:
        batch.drop_column("tls_required")
