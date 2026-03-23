"""add_media_fields_to_broadcasts

Revision ID: 003
Revises: 002
Create Date: 2026-03-20

Adds media_url, media_type, and media_filename columns to the broadcasts table
to support image + caption and document/PDF broadcast messages.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'broadcasts',
        sa.Column('media_url', sa.Text(), nullable=True),
    )
    op.add_column(
        'broadcasts',
        sa.Column('media_type', sa.String(20), nullable=True),
    )
    op.add_column(
        'broadcasts',
        sa.Column('media_filename', sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('broadcasts', 'media_filename')
    op.drop_column('broadcasts', 'media_type')
    op.drop_column('broadcasts', 'media_url')
