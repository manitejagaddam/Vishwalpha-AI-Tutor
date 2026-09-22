"""
009_ab_experiments.py
──────────────────────
Migration: Add A/B Experiments and link to LLM Call Logs.
"""
from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ab_experiments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("variant_a_template", sa.Text, nullable=False),
        sa.Column("variant_b_template", sa.Text, nullable=False),
        sa.Column("traffic_split", sa.Integer, nullable=False, server_default="50"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_ab_experiments_name", "ab_experiments", ["name"], unique=True)
    
    op.add_column("llm_call_logs", sa.Column("ab_experiment_id", sa.Integer, nullable=True))
    op.create_foreign_key(
        "fk_llm_call_logs_ab_experiment_id",
        "llm_call_logs",
        "ab_experiments",
        ["ab_experiment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_llm_call_logs_ab_experiment_id", "llm_call_logs", type_="foreignkey")
    op.drop_column("llm_call_logs", "ab_experiment_id")
    
    op.drop_index("idx_ab_experiments_name", table_name="ab_experiments")
    op.drop_table("ab_experiments")
