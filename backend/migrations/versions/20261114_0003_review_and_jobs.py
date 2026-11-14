"""rule review note, job progress

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-14 10:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('rules', schema=None) as batch_op:
        batch_op.add_column(sa.Column('review_note', sa.UnicodeText(), nullable=True))
    with op.batch_alter_table('job_runs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('total', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('done', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('summary', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('job_runs', schema=None) as batch_op:
        batch_op.drop_column('summary')
        batch_op.drop_column('done')
        batch_op.drop_column('total')
    with op.batch_alter_table('rules', schema=None) as batch_op:
        batch_op.drop_column('review_note')
