"""add email column to admin_user

Revision ID: 5f2a9c1d4e73
Revises: 19ca53917286
Create Date: 2026-10-19 19:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5f2a9c1d4e73"
down_revision = "19ca53917286"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("admin_user", sa.Column("email", sa.String(length=200), nullable=True))
    # Assign the existing administrator account its email address (supplied by the project owner).
    op.execute(
        "UPDATE admin_user SET email = 'admin2026@gmail.com' "
        "WHERE username = 'admin' AND (email IS NULL OR email = '')"
    )
    with op.batch_alter_table("admin_user", schema=None) as batch_op:
        batch_op.alter_column(
            "email", existing_type=sa.String(length=200), nullable=False
        )
    op.create_index(op.f("ix_admin_user_email"), "admin_user", ["email"], unique=True)


def downgrade():
    op.drop_index(op.f("ix_admin_user_email"), table_name="admin_user")
    op.drop_column("admin_user", "email")
