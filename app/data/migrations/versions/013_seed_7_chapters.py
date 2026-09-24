"""Seed initial 7 chapters of Class 10 Science

Revision ID: 013
Revises: 012
Create Date: 2026-09-23 18:15:00.000000+00:00

"""
from typing import Sequence, Union
from alembic import op
from app.data.seeds.seeder import seed_snapshot, downgrade_snapshot

# revision identifiers, used by Alembic.
revision: str = '013'
down_revision: Union[str, Sequence[str], None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Execute snapshot seeder to insert initial 7 chapters."""
    conn = op.get_bind()
    seed_snapshot(conn)


def downgrade() -> None:
    """Remove the seeded 7 chapters (cascading deletes topics, blocks, embeddings)."""
    conn = op.get_bind()
    downgrade_snapshot(conn)
