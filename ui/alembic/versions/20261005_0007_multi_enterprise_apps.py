"""multiple enterprise apps routed by sender domain

Revision ID: 20261005_0007_multi_enterprise_apps
Revises: 20260721_0006_tenant_certificate_auth
Create Date: 2026-10-05 00:00:00

Turns the single tenant_config row into a list of enterprise apps (Entra
app registrations, possibly in different Microsoft 365 tenants):

  - tenant_config.name / is_default — a label per app; exactly one app is
    the default and handles every sender domain without a mapping.
  - sender_domains — maps a sender domain to an app.
  - smtp_account_apps + smtp_accounts.restrict_apps — optionally limits an
    SMTP account to some apps.
  - mail_queue.tenant_config_id — the app a queued mail is sent through.
  - settings.reject_unmapped_domains — refuse unmapped domains instead of
    using the default app (off by default).

Existing deployments keep working unchanged: the existing row becomes the
default app (named "Default"), and every domain already in use (authorised
senders and the admin alert sender) is pre-mapped to it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20261005_0007_multi_enterprise_apps"
down_revision = "20260721_0006_tenant_certificate_auth"
branch_labels = None
depends_on = None


def _domain_of(address: str | None) -> str | None:
    if not address or "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1].strip().lower().rstrip(".")
    return domain or None


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("tenant_config") as batch:
        batch.add_column(
            sa.Column(
                "name",
                sa.String(length=128),
                nullable=False,
                server_default="Default",
            )
        )
        batch.add_column(
            sa.Column(
                "is_default",
                sa.Boolean,
                nullable=False,
                server_default=sa.false(),
            )
        )

    with op.batch_alter_table("smtp_accounts") as batch:
        batch.add_column(
            sa.Column(
                "restrict_apps",
                sa.Boolean,
                nullable=False,
                server_default=sa.false(),
            )
        )

    with op.batch_alter_table("settings") as batch:
        batch.add_column(
            sa.Column(
                "reject_unmapped_domains",
                sa.Boolean,
                nullable=False,
                server_default=sa.false(),
            )
        )

    op.create_table(
        "sender_domains",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("domain", sa.String(length=253), nullable=False, unique=True),
        sa.Column(
            "tenant_config_id",
            sa.Integer,
            sa.ForeignKey("tenant_config.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_sender_domains_tenant_config_id", "sender_domains", ["tenant_config_id"]
    )

    op.create_table(
        "smtp_account_apps",
        sa.Column(
            "smtp_account_id",
            sa.Integer,
            sa.ForeignKey("smtp_accounts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_config_id",
            sa.Integer,
            sa.ForeignKey("tenant_config.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_smtp_account_apps_tenant_config_id",
        "smtp_account_apps",
        ["tenant_config_id"],
    )

    # mail_queue can be large (raw MIME for the whole retention window), so
    # add the column in place rather than through a batch table copy. SQLite
    # accepts a REFERENCES clause on ADD COLUMN when the default is NULL.
    op.execute(
        "ALTER TABLE mail_queue ADD COLUMN tenant_config_id INTEGER "
        "REFERENCES tenant_config(id) ON DELETE SET NULL"
    )
    op.create_index(
        "ix_mail_queue_tenant_config_id", "mail_queue", ["tenant_config_id"]
    )

    # The existing app (lowest id; normally the old singleton id=1) becomes
    # the default.
    default_id = bind.execute(sa.text("SELECT MIN(id) FROM tenant_config")).scalar()
    if default_id is None:
        return  # fresh database: bootstrap creates the default app
    bind.execute(
        sa.text("UPDATE tenant_config SET is_default = 1 WHERE id = :id"),
        {"id": default_id},
    )

    # Pre-map the domains already in use to the default app, so the Domains
    # page shows the real setup and later changing the default app does not
    # move them.
    addresses = [
        row[0]
        for row in bind.execute(sa.text("SELECT address FROM authorised_senders"))
    ]
    addresses += [
        row[0]
        for row in bind.execute(
            sa.text("SELECT admin_email_from FROM settings WHERE id = 1")
        )
    ]
    domains = sorted({d for d in (_domain_of(a) for a in addresses) if d})
    for domain in domains:
        bind.execute(
            sa.text(
                "INSERT INTO sender_domains "
                "(domain, tenant_config_id, description, created_at) "
                "VALUES (:domain, :app, :descr, CURRENT_TIMESTAMP)"
            ),
            {
                "domain": domain,
                "app": default_id,
                "descr": "Added automatically on upgrade",
            },
        )


def downgrade() -> None:
    # Only the default app survives a downgrade (the old code reads a single
    # row); its id may not be 1, so move it there.
    bind = op.get_bind()
    default_id = bind.execute(
        sa.text("SELECT id FROM tenant_config WHERE is_default = 1 ORDER BY id LIMIT 1")
    ).scalar()

    op.drop_index("ix_mail_queue_tenant_config_id", table_name="mail_queue")
    with op.batch_alter_table("mail_queue") as batch:
        batch.drop_column("tenant_config_id")

    op.drop_index(
        "ix_smtp_account_apps_tenant_config_id", table_name="smtp_account_apps"
    )
    op.drop_table("smtp_account_apps")
    op.drop_index("ix_sender_domains_tenant_config_id", table_name="sender_domains")
    op.drop_table("sender_domains")

    if default_id is not None:
        bind.execute(
            sa.text("DELETE FROM tenant_config WHERE id != :id"), {"id": default_id}
        )
        bind.execute(
            sa.text("UPDATE tenant_config SET id = 1 WHERE id = :id"),
            {"id": default_id},
        )

    with op.batch_alter_table("settings") as batch:
        batch.drop_column("reject_unmapped_domains")
    with op.batch_alter_table("smtp_accounts") as batch:
        batch.drop_column("restrict_apps")
    with op.batch_alter_table("tenant_config") as batch:
        batch.drop_column("is_default")
        batch.drop_column("name")
