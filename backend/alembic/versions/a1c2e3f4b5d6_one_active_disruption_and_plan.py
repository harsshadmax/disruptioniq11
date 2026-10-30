"""one active disruption per cell, one in-flight plan per disruption

Revision ID: a1c2e3f4b5d6
Revises: 6f719624f558
Create Date: 2026-10-30 16:00:00.000000

The services already check both rules; these indexes make the database refuse a second row even if two
requests race past the check.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1c2e3f4b5d6"
down_revision: Union[str, Sequence[str], None] = "6f719624f558"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_one_active_disruption_per_cell ON disruptions (warehouse_id, sku_id) "
               "WHERE status = 'active'")
    op.execute("CREATE UNIQUE INDEX uq_one_in_flight_plan_per_disruption ON plans (disruption_id) "
               "WHERE status IN ('PROPOSED', 'APPROVED', 'EXECUTING')")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_one_in_flight_plan_per_disruption")
    op.execute("DROP INDEX IF EXISTS uq_one_active_disruption_per_cell")
