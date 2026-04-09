"""add image_url to products

Revision ID: 004_add_image_url
Revises: 003
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = "006_add_image_url"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "products",
        sa.Column("image_url", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("products", "image_url")
