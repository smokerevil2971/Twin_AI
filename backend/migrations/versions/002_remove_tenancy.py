"""Remove multi-tenancy — drop tenants, orders tables,
remove tenant_id from all tables, add owner table,
update unique constraints.

Revision ID: 002
Revises: 001
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Drop tables that are fully removed ─────────────────────────────────
    op.drop_table('orders')
    op.drop_table('tenants')

    # ── 2. Create owner table (replaces tenants) ──────────────────────────────
    op.create_table(
        'owner',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('business_name', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )

    # ── 3. Remove tenant_id from clients ──────────────────────────────────────
    op.drop_constraint('uq_tenant_phone', 'clients', type_='unique')
    op.drop_index('ix_clients_tenant_id', table_name='clients')
    op.drop_column('clients', 'tenant_id')
    op.create_unique_constraint('uq_phone', 'clients', ['phone'])
    op.create_index('ix_clients_phone', 'clients', ['phone'])
    op.create_index('ix_clients_opted_in', 'clients', ['opted_in'])

    # ── 4. Remove tenant_id from broadcasts ───────────────────────────────────
    op.drop_index('ix_broadcasts_tenant_id', table_name='broadcasts')
    op.drop_constraint(
        'broadcasts_tenant_id_fkey', 'broadcasts',
        type_='foreignkey'
    )
    op.drop_column('broadcasts', 'tenant_id')

    # ── 5. Remove tenant_id from conversations ────────────────────────────────
    op.drop_index('ix_conversations_tenant_id', table_name='conversations')
    op.drop_constraint(
        'conversations_tenant_id_fkey', 'conversations',
        type_='foreignkey'
    )
    op.drop_column('conversations', 'tenant_id')
    op.create_index('ix_conversations_flagged', 'conversations', ['flagged'])

    # ── 6. Remove tenant_id from knowledge_base ───────────────────────────────
    op.drop_index('ix_knowledge_base_tenant_id', table_name='knowledge_base')
    op.drop_constraint(
        'knowledge_base_tenant_id_fkey', 'knowledge_base',
        type_='foreignkey'
    )
    op.drop_column('knowledge_base', 'tenant_id')

    # ── 7. Remove tenant_id from products ────────────────────────────────────
    op.drop_index('ix_products_tenant_id', table_name='products')
    op.drop_constraint(
        'products_tenant_id_fkey', 'products',
        type_='foreignkey'
    )
    op.drop_column('products', 'tenant_id')

    # ── 8. Remove tenant_id from offers ──────────────────────────────────────
    op.drop_index('ix_offers_tenant_id', table_name='offers')
    op.drop_constraint(
        'offers_tenant_id_fkey', 'offers',
        type_='foreignkey'
    )
    op.drop_column('offers', 'tenant_id')


def downgrade() -> None:
    # Downgrade is intentionally not implemented.
    # To restore v1, switch to the main branch.
    raise NotImplementedError(
        "Downgrade not supported. Switch to main branch to restore v1."
    )
