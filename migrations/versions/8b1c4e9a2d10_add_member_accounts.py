"""add member accounts

Revision ID: 8b1c4e9a2d10
Revises: 5f2a9c1d4e73
Create Date: 2026-10-20 12:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8b1c4e9a2d10"
down_revision = "5f2a9c1d4e73"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_member_email"), "member", ["email"], unique=True)


def downgrade():
    op.drop_index(op.f("ix_member_email"), table_name="member")
    op.drop_table("member")
