"""session revocation + per-client sender binding

Revision ID: 20261007_0008_hardening_gm
Revises: 20261005_0007_multi_enterprise_apps
Create Date: 2026-10-07 00:00:00

  - users.session_version — bumped to revoke every session of a user.
  - smtp_accounts.allowed_senders / ip_whitelist.allowed_senders — MAIL FROM
    addresses a client may use. Empty keeps the previous behaviour (any
    globally authorised sender).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20261007_0008_hardening_gm"
down_revision = "20261005_0007_multi_enterprise_apps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("session_version", sa.Integer, nullable=False, server_default="0")
        )
    for table in ("smtp_accounts", "ip_whitelist"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("allowed_senders", sa.Text, nullable=False, server_default="")
            )


def downgrade() -> None:
    for table in ("ip_whitelist", "smtp_accounts"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("allowed_senders")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("session_version")
