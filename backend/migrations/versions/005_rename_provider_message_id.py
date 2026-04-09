"""rename_gupshup_message_id_to_provider_message_id

Revision ID: 005
Revises: 004
Create Date: 2026-04-03

Renames the column gupshup_message_id → provider_message_id in the
broadcast_recipients table. This makes the column name provider-agnostic
now that Meta WhatsApp Business API is the primary messaging provider.
"""
from alembic import op

# revision identifiers, used by Alembic
revision = '005'
down_revision = 'dbfae1f2a04b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'broadcast_recipients',
        'gupshup_message_id',
        new_column_name='provider_message_id',
    )


def downgrade() -> None:
    op.alter_column(
        'broadcast_recipients',
        'provider_message_id',
        new_column_name='gupshup_message_id',
    )
