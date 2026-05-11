"""Claude AI chat orchestration service."""

import re
import json
import logging
from datetime import datetime
from typing import AsyncGenerator, List, Optional

from anthropic import AsyncAnthropic

from app.core.config import (
    ANTHROPIC_API_KEY, CLAUDE_PRICING, ALLOWED_MODELS, DEFAULT_MODEL,
    WAREHOUSE_CONFIGS,
)
from app.connections.base import WarehouseExecutor
from app.connections.factory import create_executor
from app.services.warehouse_service import get_or_create_executor
from app.services.mcp_client import MCPBridge
from app.services.salesforce_executor import (
    SalesforceExecutor,
    SALESFORCE_TOOL_DEFINITIONS,
    execute_salesforce_tool,
)
from app.utils.tools import TOOL_DEFINITIONS, execute_tool, FILE_TOOL_DEFINITIONS, execute_file_tool
from app.utils.report_tools import (
    REPORT_TOOL_DEFINITIONS,
    ReportToolContext,
    execute_report_tool,
    update_chart_state,
    _is_report_tool,
)

logger = logging.getLogger(__name__)

async_anthropic_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

MAX_TOOL_ITERATIONS = 25


def build_system_prompt(
    warehouse,
    config: dict,
    credentials: dict,
    schema_summary: str = "",
    allowed_tables: Optional[List[str]] = None,
    first_conversation: bool = False,
    datasets_count: int = 0,
    tables_count: int = 0,
    memory_context: str = "",
) -> str:
    """Build system prompt for Claude based on warehouse type."""
    warehouse_name = config.get("name", warehouse.warehouse_type)

    warehouse_context = ""
    if warehouse.warehouse_type == "bigquery":
        project_id = credentials.get("project_id", "")
        warehouse_context = f"""
BIGQUERY CONFIGURATION:
- Project ID: {project_id}
- Always use this project ID when executing queries
- Use fully qualified table names: `{project_id}.dataset.table`
"""
    elif warehouse.warehouse_type == "motherduck":
        database = credentials.get("database", "")
        if database:
            warehouse_context = f"""
MOTHERDUCK CONFIGURATION:
- Database: {database}
"""

    effective_schema = schema_summary
    if allowed_tables is not None and schema_summary:
        allowed_set = set(allowed_tables)
        filtered_lines = []
        for line in schema_summary.splitlines():
            if line.startswith("--") or not line.strip():
                filtered_lines.append(line)
                continue
            if ": " in line:
                table_path = line.split(": ", 1)[0]
                parts = table_path.split(".")
                if len(parts) >= 2:
                    key = f"{parts[-2]}.{parts[-1]}"
                    if key in allowed_set:
                        filtered_lines.append(line)
            else:
                filtered_lines.append(line)
        effective_schema = "\n".join(filtered_lines)

    schema_block = ""
    if effective_schema:
        schema_block = f"""
DATABASE SCHEMA:
{effective_schema}

You already know the schema above. Write SQL directly without calling list_datasets, list_tables, or get_table_schema first.
If you need schema details not shown above, use the schema tools.
"""

    first_rule = (
        "- Write SQL directly using the schema above"
        if effective_schema
        else "- Start by listing datasets/tables if you don't know the schema"
    )

    allowlist_rule = ""
    if allowed_tables is not None:
        tables_str = ", ".join(allowed_tables)
        allowlist_rule = f"\n- ONLY query these tables: {tables_str}. Refuse queries to any other tables."

    first_conv_block = ""
    if first_conversation:
        first_conv_block = f"""

FIRST INTERACTION: Before answering, briefly mention you can see {datasets_count} dataset(s) with {tables_count} table(s), and offer to run a quick data validation (row counts, freshness checks). Keep this to 1-2 sentences, then answer their question."""

    memory_block = ""
    if memory_context:
        memory_block = f"""
## Context
{memory_context}

"""

    return f"""Data analyst for {warehouse_name}. Use tools to query the database.
{warehouse_context}{schema_block}{memory_block}
RULES:
{first_rule}
- Query efficiently, present results with insights
- No narration ("Let me...", "I'll..."), no emojis, no section headers, no enthusiastic closings ("Let me know!", "Feel free to ask!")
- Just give the answer directly, then stop
- If the requested dataset, table, or column does not exist, say so upfront before offering an alternative analysis using available data
- If the user uses a business term (e.g. "whale accounts", "power users", "churn") that is NOT defined in the Context section above, ask them to clarify the definition before querying. Do not assume meanings for ambiguous business terms
- The UI ALWAYS renders a chart automatically below your response when an execute_sql call returns category + numeric data. NEVER claim "I cannot render charts here", "this interface does not support charts", or suggest exporting to Excel/Sheets/Tableau. The chart will appear — trust the UI
- NEVER generate chart specs, Vega-Lite JSON, or visualization code in your response text
- NEVER draw ASCII bars, text-based bar charts, block characters (▌█▓░■□), repeating dashes/equals/dots ("====", "----", "...."), or any other text-based proportional visualization. If you catch yourself about to do this, stop and just present the table. The UI is rendering the real chart below — your text must NOT duplicate it
- When the user asks for a chart, visualization, or graph: run a SQL query that returns exactly 2 columns (one label/date column, one numeric column). Do NOT add Rank, %, or extra metric columns. Do NOT ask the user to clarify — just pick the most relevant breakdown and run the query
- For non-chart requests, present results normally with insights{allowlist_rule}

REPORTS:
- If the user asks to "save this as a report", "send me this every week", "schedule this", "email me this daily", etc., use the create_report tool. The most recent execute_sql query is captured automatically — run the query first if you haven't already.
- If the user asks to add a chart to an existing report, call list_reports first when the report name is ambiguous, and ask the user to confirm before calling add_to_report.
- Email recipients are always the current user — never offer to send reports to someone else.
- If a user request is ambiguous (which report, which cadence, what time), ASK before calling any report tool. A short clarifying question is better than guessing.
- Date: {datetime.now().strftime('%Y-%m-%d')}{first_conv_block}"""


async def call_claude_with_tools(
    messages: List[dict],
    system_prompt: str,
    warehouse_type: str = "",
    credentials: dict | None = None,
    max_tokens: int = 4096,
    warehouse_id: str | None = None,
    executor: WarehouseExecutor | None = None,
    model: str = DEFAULT_MODEL,
    allowed_tables: Optional[List[str]] = None,
    mcp_bridge: MCPBridge | None = None,
    sf_executor: SalesforceExecutor | None = None,
    allowed_objects: Optional[List[str]] = None,
    report_tool_ctx: ReportToolContext | None = None,
) -> tuple:
    """Call Claude with the tool-use loop.

    Returns (response_text, total_input_tokens, total_output_tokens, last_sql_result, tool_call_count).
    last_sql_result is the raw text from the last execute_sql call (for viz suggestions).
    """
    if executor is None and warehouse_type and credentials:
        if warehouse_id:
            executor, is_new = get_or_create_executor(warehouse_id, warehouse_type, credentials)
            if is_new:
                await executor.connect()
        else:
            executor = create_executor(warehouse_type, credentials)

    # Build combined tool list: warehouse tools + Salesforce tools + MCP tools + report tools
    all_tools = list(TOOL_DEFINITIONS) if executor else []
    if sf_executor:
        all_tools.extend(SALESFORCE_TOOL_DEFINITIONS)
    if mcp_bridge:
        try:
            mcp_tools = await mcp_bridge.get_tools_as_anthropic_format()
            all_tools.extend(mcp_tools)
        except Exception as e:
            logger.error(f"Failed to discover MCP tools: {e}")
    if report_tool_ctx is not None:
        all_tools.extend(REPORT_TOOL_DEFINITIONS)

    if not all_tools:
        raise ValueError("No tools available. Connect a warehouse or Salesforce org first.")

    total_input_tokens = 0
    total_output_tokens = 0
    sql_queries = []
    last_sql_result = None
    tool_call_count = 0

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await async_anthropic_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=all_tools,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            response_text = "".join(text_parts)

            if sql_queries:
                for sql in sql_queries:
                    response_text += f"\n\n```sql\n{sql}\n```"

            return response_text, total_input_tokens, total_output_tokens, last_sql_result, tool_call_count

        content_dicts = []
        for block in response.content:
            if hasattr(block, "model_dump"):
                d = block.model_dump()
                d.pop("parsed_output", None)
                content_dicts.append(d)
            else:
                content_dicts.append(block)
        messages.append({"role": "assistant", "content": content_dicts})

        tool_results = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_input = block.input if isinstance(block.input, dict) else {}

                tool_call_count += 1

                # Route tool call: report tool, Salesforce tool, MCP tool, or warehouse tool
                if report_tool_ctx is not None and _is_report_tool(block.name):
                    result_text, is_error = await execute_report_tool(
                        block.name, tool_input, report_tool_ctx,
                    )
                elif sf_executor and block.name.startswith("salesforce_"):
                    result_text, is_error = await execute_salesforce_tool(
                        sf_executor, block.name, tool_input,
                        allowed_objects=allowed_objects,
                    )
                elif mcp_bridge and mcp_bridge.is_mcp_tool(block.name):
                    try:
                        result_text = await mcp_bridge.call_tool(block.name, tool_input)
                        is_error = False
                    except Exception as e:
                        result_text = f"Error: {e}"
                        is_error = True
                elif executor:
                    if block.name == "execute_sql" and "sql" in tool_input:
                        sql_queries.append(tool_input["sql"].strip())

                    result_text, is_error = await execute_tool(
                        executor, block.name, tool_input,
                        allowed_tables=allowed_tables,
                    )

                    if block.name == "execute_sql" and not is_error:
                        last_sql_result = result_text
                        if report_tool_ctx is not None:
                            update_chart_state(
                                report_tool_ctx,
                                sql_query=tool_input["sql"].strip(),
                                sql_result_text=result_text,
                            )
                else:
                    result_text = f"Unknown tool: {block.name}"
                    is_error = True

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    text_parts = [b.text for b in response.content if hasattr(b, "text")]
    response_text = "".join(text_parts) or (
        "I wasn't able to complete this analysis within the allowed number of steps. "
        "Try breaking your question into smaller parts — for example, ask about one metric or table at a time."
    )

    if sql_queries:
        for sql in sql_queries:
            response_text += f"\n\n```sql\n{sql}\n```"

    return response_text, total_input_tokens, total_output_tokens, last_sql_result, tool_call_count


async def stream_claude_with_tools(
    messages: List[dict],
    system_prompt: str,
    warehouse_type: str = "",
    credentials: dict | None = None,
    max_tokens: int = 4096,
    warehouse_id: str | None = None,
    executor: WarehouseExecutor | None = None,
    model: str = DEFAULT_MODEL,
    allowed_tables: Optional[List[str]] = None,
    mcp_bridge: MCPBridge | None = None,
    sf_executor: SalesforceExecutor | None = None,
    allowed_objects: Optional[List[str]] = None,
    report_tool_ctx: ReportToolContext | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream Claude responses with tool-use loop.

    Yields SSE event dicts: text_delta, tool_call_start, tool_call_result.
    Final aggregated data is yielded as a special _done internal event.
    """
    if executor is None and warehouse_type and credentials:
        if warehouse_id:
            executor, is_new = get_or_create_executor(warehouse_id, warehouse_type, credentials)
            if is_new:
                await executor.connect()
        else:
            executor = create_executor(warehouse_type, credentials)

    all_tools = list(TOOL_DEFINITIONS) if executor else []
    if sf_executor:
        all_tools.extend(SALESFORCE_TOOL_DEFINITIONS)
    if mcp_bridge:
        try:
            mcp_tools = await mcp_bridge.get_tools_as_anthropic_format()
            all_tools.extend(mcp_tools)
        except Exception as e:
            logger.error(f"Failed to discover MCP tools: {e}")
    if report_tool_ctx is not None:
        all_tools.extend(REPORT_TOOL_DEFINITIONS)

    if not all_tools:
        raise ValueError("No tools available. Connect a warehouse or Salesforce org first.")

    total_input_tokens = 0
    total_output_tokens = 0
    sql_queries = []
    last_sql_result = None
    tool_call_count = 0
    full_response_text = ""
    iteration = 0

    for _ in range(MAX_TOOL_ITERATIONS):
        iteration += 1
        if iteration == 1:
            yield {"event": "status", "data": {"message": "Analyzing your question..."}}
        else:
            yield {"event": "status", "data": {"message": "Reviewing results..."}}

        # If the previous iteration's text didn't end with whitespace, the next
        # iteration's text would jam straight into it (e.g. "August 2025.The
        # report..."). Inject a paragraph break in both the stream and the
        # buffered transcript before the next deltas land.
        if (
            iteration > 1
            and full_response_text
            and not full_response_text[-1].isspace()
        ):
            yield {"event": "text_delta", "data": {"delta": "\n\n"}}
            full_response_text += "\n\n"

        async with async_anthropic_client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=all_tools,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    yield {"event": "text_delta", "data": {"delta": event.delta.text}}

            response = await stream.get_final_message()

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            full_response_text += "".join(text_parts)

            if sql_queries:
                for sql in sql_queries:
                    full_response_text += f"\n\n```sql\n{sql}\n```"

            yield {
                "event": "_done",
                "data": {
                    "response_text": full_response_text,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "last_sql_result": last_sql_result,
                    "tool_call_count": tool_call_count,
                },
            }
            return

        # Accumulate text from this iteration
        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        full_response_text += "".join(text_parts)

        content_dicts = []
        for block in response.content:
            if hasattr(block, "model_dump"):
                d = block.model_dump()
                d.pop("parsed_output", None)
                content_dicts.append(d)
            else:
                content_dicts.append(block)
        messages.append({"role": "assistant", "content": content_dicts})

        tool_results = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_input = block.input if isinstance(block.input, dict) else {}
                tool_call_count += 1

                yield {
                    "event": "tool_call_start",
                    "data": {"tool_name": block.name, "tool_input": tool_input},
                }

                if report_tool_ctx is not None and _is_report_tool(block.name):
                    result_text, is_error = await execute_report_tool(
                        block.name, tool_input, report_tool_ctx,
                    )
                elif sf_executor and block.name.startswith("salesforce_"):
                    result_text, is_error = await execute_salesforce_tool(
                        sf_executor, block.name, tool_input,
                        allowed_objects=allowed_objects,
                    )
                elif mcp_bridge and mcp_bridge.is_mcp_tool(block.name):
                    try:
                        result_text = await mcp_bridge.call_tool(block.name, tool_input)
                        is_error = False
                    except Exception as e:
                        result_text = f"Error: {e}"
                        is_error = True
                elif executor:
                    if block.name == "execute_sql" and "sql" in tool_input:
                        sql_queries.append(tool_input["sql"].strip())

                    result_text, is_error = await execute_tool(
                        executor, block.name, tool_input,
                        allowed_tables=allowed_tables,
                    )

                    if block.name == "execute_sql" and not is_error:
                        last_sql_result = result_text
                        if report_tool_ctx is not None:
                            update_chart_state(
                                report_tool_ctx,
                                sql_query=tool_input["sql"].strip(),
                                sql_result_text=result_text,
                            )
                else:
                    result_text = f"Unknown tool: {block.name}"
                    is_error = True

                yield {
                    "event": "tool_call_result",
                    "data": {"tool_name": block.name, "success": not is_error},
                }

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    # Max iterations reached
    text_parts = [b.text for b in response.content if hasattr(b, "text")]
    full_response_text += "".join(text_parts)
    if not full_response_text.strip():
        full_response_text = (
            "I wasn't able to complete this analysis within the allowed number of steps. "
            "Try breaking your question into smaller parts — for example, ask about one metric or table at a time."
        )

    if sql_queries:
        for sql in sql_queries:
            full_response_text += f"\n\n```sql\n{sql}\n```"

    yield {
        "event": "_done",
        "data": {
            "response_text": full_response_text,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "last_sql_result": last_sql_result,
            "tool_call_count": tool_call_count,
        },
    }


async def stream_claude_with_file_tools(
    messages: List[dict],
    system_prompt: str,
    executor,
    max_tokens: int = 4096,
    model: str = DEFAULT_MODEL,
    report_tool_ctx: ReportToolContext | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream Claude responses with file-based DuckDB tools.

    Yields SSE event dicts: text_delta, tool_call_start, tool_call_result, _done.
    """
    total_input_tokens = 0
    total_output_tokens = 0
    sql_queries = []
    last_sql_result = None
    full_response_text = ""
    iteration = 0
    tool_call_count = 0

    all_tools = list(FILE_TOOL_DEFINITIONS)
    if report_tool_ctx is not None:
        all_tools.extend(REPORT_TOOL_DEFINITIONS)

    for _ in range(MAX_TOOL_ITERATIONS):
        iteration += 1
        if iteration == 1:
            yield {"event": "status", "data": {"message": "Analyzing your question..."}}
        else:
            yield {"event": "status", "data": {"message": "Reviewing results..."}}

        # Insert a paragraph break between iterations when the previous text
        # didn't end with whitespace, so post-tool continuations don't jam into
        # the prior sentence (e.g. "August 2025.The report ...").
        if (
            iteration > 1
            and full_response_text
            and not full_response_text[-1].isspace()
        ):
            yield {"event": "text_delta", "data": {"delta": "\n\n"}}
            full_response_text += "\n\n"

        async with async_anthropic_client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=all_tools,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                    yield {"event": "text_delta", "data": {"delta": event.delta.text}}

            response = await stream.get_final_message()

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            full_response_text += "".join(text_parts)

            if sql_queries:
                for sql in sql_queries:
                    full_response_text += f"\n\n```sql\n{sql}\n```"

            yield {
                "event": "_done",
                "data": {
                    "response_text": full_response_text,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "last_sql_result": last_sql_result,
                    "tool_call_count": tool_call_count,
                },
            }
            return

        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        full_response_text += "".join(text_parts)

        content_dicts = []
        for block in response.content:
            if hasattr(block, "model_dump"):
                d = block.model_dump()
                d.pop("parsed_output", None)
                content_dicts.append(d)
            else:
                content_dicts.append(block)
        messages.append({"role": "assistant", "content": content_dicts})

        tool_results = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_input = block.input if isinstance(block.input, dict) else {}
                tool_call_count += 1

                yield {
                    "event": "tool_call_start",
                    "data": {"tool_name": block.name, "tool_input": tool_input},
                }

                if report_tool_ctx is not None and _is_report_tool(block.name):
                    result_text, is_error = await execute_report_tool(
                        block.name, tool_input, report_tool_ctx,
                    )
                else:
                    if block.name == "execute_query" and "sql" in tool_input:
                        sql_queries.append(tool_input["sql"].strip())

                    result_text, is_error = await execute_file_tool(
                        executor, block.name, tool_input,
                    )

                    if block.name == "execute_query" and not is_error:
                        last_sql_result = result_text
                        if report_tool_ctx is not None:
                            update_chart_state(
                                report_tool_ctx,
                                sql_query=tool_input.get("sql", "").strip(),
                                sql_result_text=result_text,
                            )

                yield {
                    "event": "tool_call_result",
                    "data": {"tool_name": block.name, "success": not is_error},
                }

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    text_parts = [b.text for b in response.content if hasattr(b, "text")]
    full_response_text += "".join(text_parts)
    if not full_response_text.strip():
        full_response_text = "The query required too many steps. Please try a simpler question."

    if sql_queries:
        for sql in sql_queries:
            full_response_text += f"\n\n```sql\n{sql}\n```"

    yield {
        "event": "_done",
        "data": {
            "response_text": full_response_text,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "last_sql_result": last_sql_result,
            "tool_call_count": tool_call_count,
        },
    }


def build_file_system_prompt(
    filename: str,
    source_type: str,
    schema_summary: str = "",
    filenames: Optional[List[str]] = None,
) -> str:
    """Build system prompt for file-backed DuckDB sessions.

    `filenames` is the full list of uploaded files in the session (when multiple
    files have been loaded into the same DuckDB connection so cross-file joins
    are possible). When omitted, falls back to the single `filename`.
    """
    files = filenames or [filename]
    is_multi = len(files) > 1

    if source_type == "duckdb":
        source_label = "a DuckDB database"
    elif is_multi:
        source_label = f"{len(files)} uploaded files"
    else:
        source_label = "an uploaded file"

    files_list = "\n".join(f"  - {f}" for f in files)
    files_block = f"\nFiles loaded:\n{files_list}\n" if is_multi else ""

    multi_join_rule = (
        "- Multiple files are loaded as separate tables in the same DuckDB connection. "
        "Cross-file JOINs are supported — use them when the user's question spans files.\n"
        if is_multi
        else ""
    )

    schema_block = ""
    if schema_summary:
        schema_block = f"""
DATA SOURCE SCHEMA:
The user has connected {source_label}: "{filename}"
{files_block}
{schema_summary}

You have full schema and sample data above. Write DuckDB SQL directly using the execute_query tool.
"""

    return f"""Data analyst. The user has uploaded data and wants to explore it with your help.
{schema_block}
RULES:
- Write DuckDB SQL to answer questions. Use the execute_query tool.
{multi_join_rule}- Query efficiently, present results with insights
- No narration ("Let me...", "I'll..."), no emojis, no section headers, no enthusiastic closings ("Let me know!", "Feel free to ask!")
- Just give the answer directly, then stop
- All connections are read-only — do not attempt INSERT, UPDATE, DELETE, DROP, CREATE, or ALTER
- The UI ALWAYS renders a chart automatically below your response when an execute_query call returns category + numeric data. NEVER claim "I cannot render charts here", "this interface does not support charts", or suggest exporting to Excel/Sheets/Tableau/Power BI/Datawrapper. The chart will appear — trust the UI
- NEVER generate chart specs, Vega-Lite JSON, or visualization code in your response text
- NEVER draw ASCII bars, text-based bar charts, block characters (▌█▓░■□), repeating dashes/equals/dots ("====", "----", "...."), or any other text-based proportional visualization. If you catch yourself about to do this, stop and just present the table. The UI is rendering the real chart below — your text must NOT duplicate it
- When the user asks for a chart, visualization, or graph: run a SQL query that returns exactly 2 columns (one label/date column, one numeric column). Do NOT add Rank, %, or extra metric columns. Do NOT ask the user to clarify — just pick the most relevant breakdown and run the query

REPORTS:
- If the user asks to "save this as a report", "send me this every week", "schedule this", "email me this daily", etc., use the create_report tool. The most recent execute_query is captured automatically — run it first if you haven't already.
- If the user asks to add a chart to an existing report, call list_reports first when the report name is ambiguous, and ask the user to confirm before calling add_to_report.
- Email recipients are always the current user — never offer to send reports to someone else.
- If a user request is ambiguous (which report, which cadence, what time), ASK before calling any report tool. A short clarifying question is better than guessing.
- Date: {datetime.now().strftime('%Y-%m-%d')}"""


async def call_claude_with_file_tools(
    messages: List[dict],
    system_prompt: str,
    executor,
    max_tokens: int = 4096,
    model: str = DEFAULT_MODEL,
    report_tool_ctx: ReportToolContext | None = None,
) -> tuple:
    """Call Claude with file-based DuckDB tools.

    Returns (response_text, total_input_tokens, total_output_tokens, last_sql_result).
    """
    total_input_tokens = 0
    total_output_tokens = 0
    sql_queries = []
    last_sql_result = None

    all_tools = list(FILE_TOOL_DEFINITIONS)
    if report_tool_ctx is not None:
        all_tools.extend(REPORT_TOOL_DEFINITIONS)

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await async_anthropic_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
            tools=all_tools,
        )

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            text_parts = [b.text for b in response.content if hasattr(b, "text")]
            response_text = "".join(text_parts)

            if sql_queries:
                for sql in sql_queries:
                    response_text += f"\n\n```sql\n{sql}\n```"

            return response_text, total_input_tokens, total_output_tokens, last_sql_result

        content_dicts = []
        for block in response.content:
            if hasattr(block, "model_dump"):
                d = block.model_dump()
                d.pop("parsed_output", None)
                content_dicts.append(d)
            else:
                content_dicts.append(block)
        messages.append({"role": "assistant", "content": content_dicts})

        tool_results = []
        for block in response.content:
            if hasattr(block, "type") and block.type == "tool_use":
                tool_input = block.input if isinstance(block.input, dict) else {}

                if report_tool_ctx is not None and _is_report_tool(block.name):
                    result_text, is_error = await execute_report_tool(
                        block.name, tool_input, report_tool_ctx,
                    )
                else:
                    if block.name == "execute_query" and "sql" in tool_input:
                        sql_queries.append(tool_input["sql"].strip())

                    result_text, is_error = await execute_file_tool(
                        executor, block.name, tool_input,
                    )

                    if block.name == "execute_query" and not is_error:
                        last_sql_result = result_text
                        if report_tool_ctx is not None:
                            update_chart_state(
                                report_tool_ctx,
                                sql_query=tool_input.get("sql", "").strip(),
                                sql_result_text=result_text,
                            )

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    text_parts = [b.text for b in response.content if hasattr(b, "text")]
    response_text = "".join(text_parts) or "The query required too many steps. Please try a simpler question."

    if sql_queries:
        for sql in sql_queries:
            response_text += f"\n\n```sql\n{sql}\n```"

    return response_text, total_input_tokens, total_output_tokens, last_sql_result


def calculate_cost(input_tokens: int, output_tokens: int, model: str = "default") -> float:
    """Calculate cost in USD for token usage."""
    pricing = CLAUDE_PRICING.get(model, CLAUDE_PRICING["default"])
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)
