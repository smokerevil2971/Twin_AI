"""add_embedding_to_conversations

Revision ID: 004
Revises: 003
Create Date: 2026-03-24

Adds a pgvector embedding column to the conversations table to enable
long-term semantic memory search (Chat History RAG).
"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '99b54a11c124'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension (safe to run multiple times)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add embedding column (768 dims — Gemini text-embedding-004)
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS "
        "embedding vector(768)"
    )

    # HNSW index for fast approximate nearest-neighbour search using cosine distance
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversations_embedding "
        "ON conversations USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conversations_embedding")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS embedding")
