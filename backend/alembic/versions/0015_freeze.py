"""Freeze merge (S0, 07:00 plan moved up): joins the parallel session branches analysis (A), ask (L), review (B) and
data (D) into one head. No schema change. Later fixes go linearly on top of 0015_freeze.

Revision ID: 0015_freeze
Revises: 0007_analysis, 0008_question, 0009_review, 0014_bzp_changes_only
Create Date: 2026-11-21 22:08:08.120700
"""
from typing import Sequence, Union


revision: str = '0015_freeze'
down_revision: Union[str, Sequence[str], None] = ('0007_analysis', '0008_question', '0009_review', '0014_bzp_changes_only')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
