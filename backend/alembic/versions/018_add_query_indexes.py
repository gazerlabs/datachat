"""Add indexes for hot read paths (usage stats, conversation history).

These tables were created without indexes on their high-cardinality foreign
keys, so the queries that filter by user_id or conversation_id were doing full
table scans. At small scale that's invisible; at any meaningful scale it's a
latency cliff. Idempotent — skips indexes that already exist.

Revision ID: 018
Revises: 017
Create Date: 2026-05-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018"
down_revision: Union[str, Sequence[str], None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (index_name, table_name, [columns])
INDEXES = [
    ("ix_token_usage_user_id_created_at", "token_usage", ["user_id", "created_at"]),
    ("ix_conversations_user_id", "conversations", ["user_id"]),
    ("ix_warehouse_connections_user_id", "warehouse_connections", ["user_id"]),
    ("ix_conversation_messages_conversation_id", "conversation_messages", ["conversation_id"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for index_name, table_name, columns in INDEXES:
        if table_name not in existing_tables:
            continue
        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
        if index_name in existing_indexes:
            continue
        op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for index_name, table_name, _ in INDEXES:
        if table_name not in existing_tables:
            continue
        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=table_name)
