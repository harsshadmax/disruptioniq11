"""customer contracts: uploaded penalty terms, one confirmed contract per customer

Revision ID: b2d4e6f8a1c3
Revises: a1c2e3f4b5d6
Create Date: 2026-10-31 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2d4e6f8a1c3"
down_revision: Union[str, Sequence[str], None] = "a1c2e3f4b5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_contracts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("filename", sa.String(200)),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("extracted_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("terms_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("ai_check_json", postgresql.JSONB()),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_customer_contracts_customer", "customer_contracts", ["customer_id"])
    # the service retires the old one first; this makes the database refuse two confirmed contracts for one customer
    op.execute("CREATE UNIQUE INDEX uq_one_confirmed_contract_per_customer ON customer_contracts (customer_id) "
               "WHERE status = 'confirmed'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_one_confirmed_contract_per_customer")
    op.drop_index("ix_customer_contracts_customer", table_name="customer_contracts")
    op.drop_table("customer_contracts")
