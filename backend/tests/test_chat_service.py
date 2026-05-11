"""Tests for services/chat_service.py."""

from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


class TestBuildSystemPrompt:
    def test_basic_prompt(self):
        from app.services.chat_service import build_system_prompt

        warehouse = MagicMock()
        warehouse.warehouse_type = "postgresql"
        config = {"name": "PostgreSQL"}

        prompt = build_system_prompt(warehouse, config, {})
        assert "PostgreSQL" in prompt
        assert "RULES:" in prompt

    def test_bigquery_prompt_includes_project_id(self):
        from app.services.chat_service import build_system_prompt

        warehouse = MagicMock()
        warehouse.warehouse_type = "bigquery"
        config = {"name": "BigQuery"}
        credentials = {"project_id": "my-project-123"}

        prompt = build_system_prompt(warehouse, config, credentials)
        assert "my-project-123" in prompt
        assert "BIGQUERY CONFIGURATION" in prompt

    def test_motherduck_prompt_includes_database(self):
        from app.services.chat_service import build_system_prompt

        warehouse = MagicMock()
        warehouse.warehouse_type = "motherduck"
        config = {"name": "MotherDuck"}
        credentials = {"database": "analytics_db"}

        prompt = build_system_prompt(warehouse, config, credentials)
        assert "analytics_db" in prompt
        assert "MOTHERDUCK CONFIGURATION" in prompt

    def test_schema_included_in_prompt(self):
        from app.services.chat_service import build_system_prompt

        warehouse = MagicMock()
        warehouse.warehouse_type = "postgresql"
        config = {"name": "PostgreSQL"}

        prompt = build_system_prompt(
            warehouse, config, {},
            schema_summary="db.public.users: id (int), name (text)",
        )
        assert "DATABASE SCHEMA:" in prompt
        assert "db.public.users" in prompt

    def test_allowlist_filter(self):
        from app.services.chat_service import build_system_prompt

        warehouse = MagicMock()
        warehouse.warehouse_type = "postgresql"
        config = {"name": "PostgreSQL"}
        schema = "db.public.users: id (int)\ndb.public.orders: id (int)\ndb.public.secret: id (int)"

        prompt = build_system_prompt(
            warehouse, config, {},
            schema_summary=schema,
            allowed_tables=["public.users", "public.orders"],
        )
        assert "public.users" in prompt
        assert "public.orders" in prompt
        assert "ONLY query these tables" in prompt

    def test_first_conversation_block(self):
        from app.services.chat_service import build_system_prompt

        warehouse = MagicMock()
        warehouse.warehouse_type = "postgresql"
        config = {"name": "PostgreSQL"}

        prompt = build_system_prompt(
            warehouse, config, {},
            first_conversation=True,
            datasets_count=3,
            tables_count=15,
        )
        assert "3 dataset(s)" in prompt
        assert "15 table(s)" in prompt

    def test_date_in_prompt(self):
        from app.services.chat_service import build_system_prompt

        warehouse = MagicMock()
        warehouse.warehouse_type = "postgresql"
        config = {"name": "PostgreSQL"}

        prompt = build_system_prompt(warehouse, config, {})
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in prompt


class TestCallClaudeWithTools:
    @patch("app.services.chat_service.async_anthropic_client")
    async def test_end_turn_returns_text(self, mock_client):
        from app.services.chat_service import call_claude_with_tools

        mock_text_block = MagicMock()
        mock_text_block.text = "Here are your results."
        mock_text_block.type = "text"

        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [mock_text_block]
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        executor = MagicMock()
        result = await call_claude_with_tools(
            messages=[{"role": "user", "content": "test"}],
            system_prompt="You are a data analyst.",
            executor=executor,
        )
        text, inp, out, last_sql, tool_count = result
        assert text == "Here are your results."
        assert inp == 100
        assert out == 50
        assert tool_count == 0

    @patch("app.services.chat_service.async_anthropic_client")
    async def test_tool_use_loop(self, mock_client):
        from app.services.chat_service import call_claude_with_tools

        # First call: tool_use
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "execute_sql"
        tool_block.input = {"sql": "SELECT 1"}
        tool_block.id = "tool_1"
        tool_block.model_dump.return_value = {"type": "tool_use", "name": "execute_sql", "input": {"sql": "SELECT 1"}, "id": "tool_1"}

        resp1 = MagicMock()
        resp1.stop_reason = "tool_use"
        resp1.content = [tool_block]
        resp1.usage.input_tokens = 50
        resp1.usage.output_tokens = 20

        # Second call: end_turn
        text_block = MagicMock()
        text_block.text = "The result is 1."
        text_block.type = "text"

        resp2 = MagicMock()
        resp2.stop_reason = "end_turn"
        resp2.content = [text_block]
        resp2.usage.input_tokens = 80
        resp2.usage.output_tokens = 30

        mock_client.messages.create = AsyncMock(side_effect=[resp1, resp2])

        executor = AsyncMock()
        executor.execute_sql.return_value = "| result |\n| 1 |"

        result = await call_claude_with_tools(
            messages=[{"role": "user", "content": "run query"}],
            system_prompt="analyst",
            executor=executor,
        )
        text, inp, out, last_sql, tool_count = result
        assert "The result is 1." in text
        assert inp == 130
        assert out == 50
        assert tool_count == 1
        assert last_sql == "| result |\n| 1 |"

    @patch("app.services.chat_service.async_anthropic_client")
    async def test_no_tools_raises(self, mock_client):
        from app.services.chat_service import call_claude_with_tools

        with pytest.raises(ValueError, match="No tools available"):
            await call_claude_with_tools(
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="test",
            )


class TestCalculateCost:
    def test_default_pricing(self):
        from app.services.chat_service import calculate_cost

        cost = calculate_cost(1_000_000, 1_000_000)
        assert cost == 18.0  # 3 + 15

    def test_sonnet_pricing(self):
        from app.services.chat_service import calculate_cost

        cost = calculate_cost(1_000_000, 0, model="claude-sonnet-4-6")
        assert cost == 3.0

    def test_zero_tokens(self):
        from app.services.chat_service import calculate_cost

        cost = calculate_cost(0, 0)
        assert cost == 0.0
