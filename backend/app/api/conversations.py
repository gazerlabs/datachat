"""Conversation and chat endpoints."""

import json
import re
import sys
import time
import traceback
import uuid as uuid_mod
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.config import WAREHOUSE_CONFIGS, ALLOWED_MODELS, DEFAULT_MODEL
from app.core.security import decrypt_credentials
from app.core.dependencies import require_auth, get_current_user
from app.core.rate_limit import limiter, CHAT_RATE_LIMIT
from app.models.user import User
from app.models.warehouse import WarehouseConnection
from app.models.conversation import Conversation, ConversationMessage
from app.models.token_usage import TokenUsage
from app.models.salesforce import SalesforceConnection
from app.schemas.conversation import (
    ChatRequest, ChatResponse, CreateConversationRequest, ConversationResponse,
    MessageResponse, RenameConversationRequest,
)
from app.services.token_usage_service import TokenUsageService
from app.services.chat_service import (
    build_system_prompt, call_claude_with_tools, calculate_cost,
    build_file_system_prompt, call_claude_with_file_tools,
    stream_claude_with_tools, stream_claude_with_file_tools,
)
from app.services.warehouse_service import get_or_create_executor, get_or_fetch_schema
from app.services.visualization_service import suggest_visualization
from app.utils.report_tools import ReportToolContext
from app.services.salesforce_service import get_valid_access_token
from app.services.salesforce_executor import SalesforceExecutor
from app.services import context_service
from app.connections.duckdb_local import get_file_session, DuckDBLocalExecutor
from app.connections.local_duckdb_persistent import LocalDuckDBExecutor
from app.services import local_duckdb_service

router = APIRouter(tags=["conversations"])


def _parse_query_result(result_text: str) -> list[dict]:
    """Parse query result text (pretty-table or tab-separated) into list of dicts."""
    lines = result_text.strip().split("\n")
    if len(lines) < 2:
        return []

    # Detect pretty-table format (lines starting with + or |)
    if lines[0].startswith("+") or lines[0].startswith("|"):
        # Pretty-table: skip border lines (starting with +), parse | delimited data
        data_lines = [l for l in lines if l.startswith("|")]
        if len(data_lines) < 2:
            return []
        headers = [h.strip() for h in data_lines[0].split("|") if h.strip()]
        rows = []
        for line in data_lines[1:]:
            values = [v.strip() for v in line.split("|") if v.strip()]
            if len(values) == len(headers):
                row = {}
                for h, v in zip(headers, values):
                    try:
                        row[h] = int(v)
                    except ValueError:
                        try:
                            row[h] = float(v)
                        except ValueError:
                            row[h] = v
                rows.append(row)
        return rows

    # Fallback: tab-separated format
    headers = [h.strip() for h in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split("\t")]
        if len(values) == len(headers):
            row = {}
            for h, v in zip(headers, values):
                try:
                    row[h] = int(v)
                except ValueError:
                    try:
                        row[h] = float(v)
                    except ValueError:
                        row[h] = v
            rows.append(row)
    return rows


@router.post("/api/chat", response_model=ChatResponse)
@limiter.limit(CHAT_RATE_LIMIT)
async def chat(
    request: ChatRequest,
    req: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Send a message and get a response."""
    try:
        usage_check = TokenUsageService.check_pre_query(db, user)
        if not usage_check["allowed"]:
            raise HTTPException(
                status_code=usage_check["status_code"],
                detail=usage_check["warning"],
            )

        # Check for file session first (takes priority)
        file_session = None
        if request.file_session_id:
            file_session = get_file_session(request.file_session_id, user.id)
            if file_session is None:
                return ChatResponse(
                    success=False,
                    response="File session expired or not found. Please re-upload your file.",
                    conversation_id=request.conversation_id or str(uuid_mod.uuid4()),
                )

        # Persistent local DuckDB (per-user)
        local_db = None
        if request.local_duckdb_id and not file_session:
            local_db = local_duckdb_service.get_user_db(db, user.id)
            if local_db is None or local_db.id != request.local_duckdb_id:
                return ChatResponse(
                    success=False,
                    response="Local data source not found. Upload a file in Settings to get started.",
                    conversation_id=request.conversation_id or str(uuid_mod.uuid4()),
                )

        warehouse = None
        sf_connection = None

        if request.salesforce_id:
            # Explicit Salesforce selection — use ONLY Salesforce
            sf_connection = db.query(SalesforceConnection).filter(
                SalesforceConnection.id == request.salesforce_id,
                SalesforceConnection.user_id == user.id,
            ).first()
        elif request.warehouse_id:
            # Explicit warehouse selection — use ONLY warehouse
            warehouse = db.query(WarehouseConnection).filter(
                WarehouseConnection.id == request.warehouse_id,
                WarehouseConnection.user_id == user.id,
            ).first()
        else:
            # Fallback: try warehouse first, then Salesforce
            warehouse = db.query(WarehouseConnection).filter(
                WarehouseConnection.user_id == user.id,
                WarehouseConnection.connection_status == "connected",
            ).first()
            if not warehouse:
                sf_connection = db.query(SalesforceConnection).filter(
                    SalesforceConnection.user_id == user.id,
                    SalesforceConnection.connection_status == "connected",
                ).first()

        if not warehouse and not sf_connection and not file_session and not local_db:
            return ChatResponse(
                success=False,
                response="Please connect a data source first. Go to Settings to add a warehouse, upload a file, or connect Salesforce.",
                conversation_id=request.conversation_id or str(uuid_mod.uuid4()),
            )

        conversation = None
        if request.conversation_id:
            conversation = db.query(Conversation).filter(
                Conversation.id == request.conversation_id,
                Conversation.user_id == user.id,
            ).first()

        if not conversation:
            conversation = Conversation(
                id=str(uuid_mod.uuid4()),
                user_id=user.id,
                warehouse_connection_id=warehouse.id if warehouse else None,
                title=request.message[:50] + "..." if len(request.message) > 50 else request.message,
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)

        history_messages = db.query(ConversationMessage).filter(
            ConversationMessage.conversation_id == conversation.id
        ).order_by(ConversationMessage.created_at.desc()).limit(6).all()
        history_messages = list(reversed(history_messages))

        def compress_message(content: str, role: str) -> str:
            content = re.sub(r'```sql\s*[\s\S]*?```\s*', '', content).strip()
            if role == "assistant" and len(content) > 800:
                content = content[:800] + "... [truncated]"
            return content

        messages = [{"role": m.role, "content": compress_message(m.content, m.role)} for m in history_messages]
        messages.append({"role": "user", "content": request.message})

        # Prepare warehouse credentials — connection + schema deferred for streaming status events
        credentials = None
        warehouse_config = {}
        allowed_tables = None

        if warehouse:
            warehouse_config = WAREHOUSE_CONFIGS.get(warehouse.warehouse_type, {})
            credentials = decrypt_credentials(warehouse.credentials_encrypted)

            allowed_tables = warehouse.allowed_tables
            if isinstance(allowed_tables, str):
                allowed_tables = json.loads(allowed_tables)

        # Salesforce system prompt (warehouse prompt built later after schema fetch)
        system_prompt = None
        if not warehouse and sf_connection:
            sf_allowed_objects = sf_connection.allowed_objects
            if isinstance(sf_allowed_objects, str):
                sf_allowed_objects = json.loads(sf_allowed_objects)

            allowed_objects_prompt = ""
            if sf_allowed_objects:
                obj_list = ", ".join(sf_allowed_objects)
                allowed_objects_prompt = f"\n- ONLY query these Salesforce objects: {obj_list}. Do NOT query any other objects."

            system_prompt = f"""Data analyst with access to Salesforce CRM data. Use the available tools to query and explore Salesforce objects.

RULES:
- Use the MCP tools to discover Salesforce objects, fields, and relationships
- Query data using SOQL through the available tools{allowed_objects_prompt}
- No narration ("Let me...", "I'll..."), no emojis, no section headers
- Just give the answer directly
- Date: {datetime.now().strftime('%Y-%m-%d')}"""

        # Set up Salesforce executor (if connected)
        sf_executor = None
        sf_allowed_objects_list = None
        if sf_connection:
            try:
                sf_access_token = await get_valid_access_token(sf_connection, db)
                sf_executor = SalesforceExecutor(
                    instance_url=sf_connection.instance_url,
                    access_token=sf_access_token,
                )
                # Get allowed objects for tool enforcement
                sf_allowed = sf_connection.allowed_objects
                if isinstance(sf_allowed, str):
                    sf_allowed = json.loads(sf_allowed)
                sf_allowed_objects_list = sf_allowed
            except Exception as e:
                import traceback as tb
                tb.print_exc()
                if not warehouse:
                    return ChatResponse(
                        success=False,
                        response=f"Failed to connect to Salesforce: {e}. Please try reconnecting in Settings.",
                        conversation_id=request.conversation_id or str(uuid_mod.uuid4()),
                    )
                sf_executor = None

        selected_model = request.model if request.model in ALLOWED_MODELS else DEFAULT_MODEL

        # --- File session path (DuckDB-backed) ---
        last_sql_result = None
        if file_session:
            file_executor = DuckDBLocalExecutor(file_session)
            file_schema = await file_executor.get_schema_summary()

            file_system_prompt = build_file_system_prompt(
                filename=file_session.filename,
                source_type=file_session.source_type,
                schema_summary=file_schema,
                filenames=[f["filename"] for f in file_session._files] or None,
            )

            start_time = time.time()
            response_text, input_tokens, output_tokens, last_sql_result = await call_claude_with_file_tools(
                messages=messages,
                system_prompt=file_system_prompt,
                executor=file_executor,
                model=selected_model,
            )
            duration_ms = int((time.time() - start_time) * 1000)

        # --- Persistent LocalDuckDB path ---
        elif local_db:
            local_executor = LocalDuckDBExecutor(local_db.file_path)
            try:
                local_schema = await local_executor.get_schema_summary()
                filenames = [t.original_filename for t in local_db.tables]
                local_system_prompt = build_file_system_prompt(
                    filename="Local files",
                    source_type="local_duckdb",
                    schema_summary=local_schema,
                    filenames=filenames or None,
                )

                local_report_tool_ctx = ReportToolContext(
                    db=db, user=user, local_duckdb_id=local_db.id,
                )
                start_time = time.time()
                response_text, input_tokens, output_tokens, last_sql_result = await call_claude_with_file_tools(
                    messages=messages,
                    system_prompt=local_system_prompt,
                    executor=local_executor,
                    model=selected_model,
                    report_tool_ctx=local_report_tool_ctx,
                )
                duration_ms = int((time.time() - start_time) * 1000)
            finally:
                local_executor.close()

        # --- Warehouse / Salesforce path ---
        else:
            report_tool_ctx = None
            if warehouse:
                report_tool_ctx = ReportToolContext(
                    db=db, user=user, warehouse_id=warehouse.id,
                )
            start_time = time.time()
            response_text, input_tokens, output_tokens, last_sql_result, _ = await call_claude_with_tools(
                messages=messages,
                system_prompt=system_prompt,
                warehouse_type=warehouse.warehouse_type if warehouse else "",
                credentials=credentials,
                warehouse_id=warehouse.id if warehouse else None,
                executor=executor,
                model=selected_model,
                allowed_tables=allowed_tables,
                sf_executor=sf_executor,
                allowed_objects=sf_allowed_objects_list,
                report_tool_ctx=report_tool_ctx,
            )
            duration_ms = int((time.time() - start_time) * 1000)

        # Generate visualization suggestion from last SQL result
        visualization = None
        chart_data = None
        if last_sql_result:
            chart_data = _parse_query_result(last_sql_result)
            if chart_data:
                columns = list(chart_data[0].keys()) if chart_data else []
                visualization = suggest_visualization(columns, chart_data)

        cost = calculate_cost(input_tokens, output_tokens, model=selected_model)

        user_message = ConversationMessage(
            conversation_id=conversation.id,
            role="user",
            content=request.message,
        )
        assistant_message = ConversationMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=response_text,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            visualization=json.dumps(visualization) if visualization else None,
            chart_data=json.dumps(chart_data) if chart_data else None,
        )
        db.add(user_message)
        db.add(assistant_message)

        conversation.updated_at = datetime.utcnow()

        token_usage = TokenUsageService.record_usage(
            db=db,
            user=user,
            conversation_id=conversation.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            model=selected_model,
        )
        db.commit()
        db.refresh(assistant_message)

        post_check = TokenUsageService.check_pre_query(db, user)

        return ChatResponse(
            success=True,
            response=response_text,
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            weighted_tokens=token_usage.weighted_tokens,
            duration_ms=duration_ms,
            usage_warning=post_check.get("warning"),
            usage_percent=post_check.get("usage_percent"),
            visualization=visualization,
            chart_data=chart_data,
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        error_msg = str(e)

        if "credit balance is too low" in error_msg.lower():
            error_msg = "The AI service is temporarily unavailable due to API credit limits. Please contact the administrator."
        elif "rate_limit" in error_msg.lower():
            error_msg = "Too many requests. Please wait a moment and try again."
        elif "overloaded" in error_msg.lower():
            error_msg = "The AI service is currently busy. Please try again in a few seconds."
        elif "invalid_api_key" in error_msg.lower():
            error_msg = "API configuration error. Please contact the administrator."

        return ChatResponse(
            success=False,
            response=error_msg,
            conversation_id=request.conversation_id or str(uuid_mod.uuid4()),
        )


async def _prepare_chat_context(request: ChatRequest, user: User, db: Session) -> dict:
    """Shared setup for chat and chat/stream: resolve data sources, build prompts, etc.

    Returns a dict with all the context needed to call Claude.
    """
    # Check for file session first (takes priority)
    file_session = None
    if request.file_session_id:
        file_session = get_file_session(request.file_session_id, user.id)
        if file_session is None:
            raise ValueError("File session expired or not found. Please re-upload your file.")

    # Persistent local DuckDB (per-user)
    local_db = None
    if request.local_duckdb_id and not file_session:
        local_db = local_duckdb_service.get_user_db(db, user.id)
        if local_db is None or local_db.id != request.local_duckdb_id:
            raise ValueError("Local data source not found. Upload a file in Settings to get started.")

    warehouse = None
    sf_connection = None

    if request.salesforce_id:
        sf_connection = db.query(SalesforceConnection).filter(
            SalesforceConnection.id == request.salesforce_id,
            SalesforceConnection.user_id == user.id,
        ).first()
    elif request.warehouse_id:
        warehouse = db.query(WarehouseConnection).filter(
            WarehouseConnection.id == request.warehouse_id,
            WarehouseConnection.user_id == user.id,
        ).first()
    else:
        warehouse = db.query(WarehouseConnection).filter(
            WarehouseConnection.user_id == user.id,
            WarehouseConnection.connection_status == "connected",
        ).first()
        if not warehouse:
            sf_connection = db.query(SalesforceConnection).filter(
                SalesforceConnection.user_id == user.id,
                SalesforceConnection.connection_status == "connected",
            ).first()

    if not warehouse and not sf_connection and not file_session and not local_db:
        raise ValueError("Please connect a data source first. Go to Settings to add a warehouse, upload a file, or connect Salesforce.")

    conversation = None
    if request.conversation_id:
        conversation = db.query(Conversation).filter(
            Conversation.id == request.conversation_id,
            Conversation.user_id == user.id,
        ).first()

    if not conversation:
        conversation = Conversation(
            id=str(uuid_mod.uuid4()),
            user_id=user.id,
            warehouse_connection_id=warehouse.id if warehouse else None,
            title=request.message[:50] + "..." if len(request.message) > 50 else request.message,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    history_messages = db.query(ConversationMessage).filter(
        ConversationMessage.conversation_id == conversation.id
    ).order_by(ConversationMessage.created_at.desc()).limit(6).all()
    history_messages = list(reversed(history_messages))

    def compress_message(content: str, role: str) -> str:
        content = re.sub(r'```sql\s*[\s\S]*?```\s*', '', content).strip()
        if role == "assistant" and len(content) > 800:
            content = content[:800] + "... [truncated]"
        return content

    messages = [{"role": m.role, "content": compress_message(m.content, m.role)} for m in history_messages]
    messages.append({"role": "user", "content": request.message})

    executor = None
    credentials = None
    warehouse_config = {}
    schema_summary = ""
    allowed_tables = None

    if warehouse:
        warehouse_config = WAREHOUSE_CONFIGS.get(warehouse.warehouse_type, {})
        credentials = decrypt_credentials(warehouse.credentials_encrypted)
        executor, is_new = get_or_create_executor(warehouse.id, warehouse.warehouse_type, credentials)
        if is_new:
            await executor.connect()
        schema_summary = await get_or_fetch_schema(warehouse.id, executor)

        allowed_tables = warehouse.allowed_tables
        if isinstance(allowed_tables, str):
            allowed_tables = json.loads(allowed_tables)

    first_conversation = False
    datasets_count = 0
    tables_count = 0
    if warehouse and not request.conversation_id:
        prior_convs = db.query(Conversation).filter(
            Conversation.user_id == user.id,
            Conversation.warehouse_connection_id == warehouse.id,
        ).count()
        if prior_convs <= 1:
            first_conversation = True
            for line in schema_summary.splitlines():
                if line.startswith("--") or not line.strip() or ": " not in line:
                    continue
                tables_count += 1
            ds_set = set()
            for line in schema_summary.splitlines():
                if line.startswith("--") or not line.strip() or ": " not in line:
                    continue
                parts = line.split(": ", 1)[0].split(".")
                if len(parts) >= 2:
                    ds_set.add(parts[-2])
            datasets_count = len(ds_set)

    user_context = context_service.get_context(db, user.id)

    if warehouse:
        system_prompt = build_system_prompt(
            warehouse, warehouse_config, credentials,
            schema_summary=schema_summary,
            allowed_tables=allowed_tables,
            first_conversation=first_conversation,
            datasets_count=datasets_count,
            tables_count=tables_count,
            memory_context=user_context,
        )
    else:
        sf_allowed_objects = None
        if sf_connection:
            sf_allowed_objects = sf_connection.allowed_objects
            if isinstance(sf_allowed_objects, str):
                sf_allowed_objects = json.loads(sf_allowed_objects)

        allowed_objects_prompt = ""
        if sf_allowed_objects:
            obj_list = ", ".join(sf_allowed_objects)
            allowed_objects_prompt = f"\n- ONLY query these Salesforce objects: {obj_list}. Do NOT query any other objects."

        system_prompt = f"""Data analyst with access to Salesforce CRM data. Use the available tools to query and explore Salesforce objects.

RULES:
- Use the MCP tools to discover Salesforce objects, fields, and relationships
- Query data using SOQL through the available tools{allowed_objects_prompt}
- No narration ("Let me...", "I'll..."), no emojis, no section headers
- Just give the answer directly
- Date: {datetime.now().strftime('%Y-%m-%d')}"""

    sf_executor = None
    sf_allowed_objects_list = None
    if sf_connection:
        try:
            sf_access_token = await get_valid_access_token(sf_connection, db)
            sf_executor = SalesforceExecutor(
                instance_url=sf_connection.instance_url,
                access_token=sf_access_token,
            )
            sf_allowed = sf_connection.allowed_objects
            if isinstance(sf_allowed, str):
                sf_allowed = json.loads(sf_allowed)
            sf_allowed_objects_list = sf_allowed
        except Exception as e:
            import traceback as tb
            tb.print_exc()
            if not warehouse:
                raise ValueError(f"Failed to connect to Salesforce: {e}. Please try reconnecting in Settings.")
            sf_executor = None

    selected_model = request.model if request.model in ALLOWED_MODELS else DEFAULT_MODEL

    return {
        "conversation": conversation,
        "messages": messages,
        "system_prompt": system_prompt,  # None for warehouse (built after schema fetch)
        "warehouse": warehouse,
        "warehouse_config": warehouse_config,
        "credentials": credentials,
        "allowed_tables": allowed_tables,
        "sf_executor": sf_executor,
        "sf_allowed_objects_list": sf_allowed_objects_list,
        "selected_model": selected_model,
        "file_session": file_session,
        "local_db": local_db,
    }


@router.post("/api/chat/stream")
@limiter.limit(CHAT_RATE_LIMIT)
async def chat_stream(
    request: ChatRequest,
    req: Request,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Send a message and stream the response as SSE events."""
    try:
        usage_check = TokenUsageService.check_pre_query(db, user)
        if not usage_check["allowed"]:
            raise HTTPException(
                status_code=usage_check["status_code"],
                detail=usage_check["warning"],
            )

        ctx = await _prepare_chat_context(request, user, db)
        stream_memory_context = context_service.get_context(db, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async def event_generator():
        try:
            start_time = time.time()
            done_data = None

            if ctx["file_session"]:
                yield f"event: status\ndata: {json.dumps({'message': 'Loading file data...'})}\n\n"
                file_executor = DuckDBLocalExecutor(ctx["file_session"])
                yield f"event: status\ndata: {json.dumps({'message': 'Reading file schema...'})}\n\n"
                file_schema = await file_executor.get_schema_summary()
                file_system_prompt = build_file_system_prompt(
                    filename=ctx["file_session"].filename,
                    source_type=ctx["file_session"].source_type,
                    schema_summary=file_schema,
                    filenames=[f["filename"] for f in ctx["file_session"]._files] or None,
                )
                async for evt in stream_claude_with_file_tools(
                    messages=ctx["messages"],
                    system_prompt=file_system_prompt,
                    executor=file_executor,
                    model=ctx["selected_model"],
                ):
                    if evt["event"] == "_done":
                        done_data = evt["data"]
                    else:
                        yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'])}\n\n"

            elif ctx["local_db"]:
                local_db = ctx["local_db"]
                yield f"event: status\ndata: {json.dumps({'message': 'Opening local data...'})}\n\n"
                local_executor = LocalDuckDBExecutor(local_db.file_path)
                try:
                    yield f"event: status\ndata: {json.dumps({'message': 'Reading schema...'})}\n\n"
                    local_schema = await local_executor.get_schema_summary()
                    filenames = [t.original_filename for t in local_db.tables]
                    local_system_prompt = build_file_system_prompt(
                        filename="Local files",
                        source_type="local_duckdb",
                        schema_summary=local_schema,
                        filenames=filenames or None,
                    )
                    local_report_tool_ctx = ReportToolContext(
                        db=db, user=user, local_duckdb_id=local_db.id,
                    )
                    async for evt in stream_claude_with_file_tools(
                        messages=ctx["messages"],
                        system_prompt=local_system_prompt,
                        executor=local_executor,
                        model=ctx["selected_model"],
                        report_tool_ctx=local_report_tool_ctx,
                    ):
                        if evt["event"] == "_done":
                            done_data = evt["data"]
                        else:
                            yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'])}\n\n"
                finally:
                    local_executor.close()

            elif ctx["warehouse"]:
                warehouse = ctx["warehouse"]
                wh_name = warehouse.name or warehouse.warehouse_type

                yield f"event: status\ndata: {json.dumps({'message': f'Connecting to {wh_name}...'})}\n\n"
                executor, is_new = get_or_create_executor(
                    warehouse.id, warehouse.warehouse_type, ctx["credentials"],
                )
                if is_new:
                    await executor.connect()

                yield f"event: status\ndata: {json.dumps({'message': 'Fetching database schema...'})}\n\n"
                schema_summary = await get_or_fetch_schema(warehouse.id, executor)

                # Check first conversation
                first_conversation = False
                datasets_count = 0
                tables_count = 0
                if not request.conversation_id:
                    prior_convs = db.query(Conversation).filter(
                        Conversation.user_id == user.id,
                        Conversation.warehouse_connection_id == warehouse.id,
                    ).count()
                    if prior_convs <= 1:
                        first_conversation = True
                        for line in schema_summary.splitlines():
                            if line.startswith("--") or not line.strip() or ": " not in line:
                                continue
                            tables_count += 1
                        ds_set = set()
                        for line in schema_summary.splitlines():
                            if line.startswith("--") or not line.strip() or ": " not in line:
                                continue
                            parts = line.split(": ", 1)[0].split(".")
                            if len(parts) >= 2:
                                ds_set.add(parts[-2])
                        datasets_count = len(ds_set)

                system_prompt = build_system_prompt(
                    warehouse, ctx["warehouse_config"], ctx["credentials"],
                    schema_summary=schema_summary,
                    allowed_tables=ctx["allowed_tables"],
                    first_conversation=first_conversation,
                    datasets_count=datasets_count,
                    tables_count=tables_count,
                    memory_context=stream_memory_context,
                )

                report_tool_ctx = ReportToolContext(
                    db=db, user=user, warehouse_id=warehouse.id,
                )
                async for evt in stream_claude_with_tools(
                    messages=ctx["messages"],
                    system_prompt=system_prompt,
                    warehouse_type=warehouse.warehouse_type,
                    credentials=ctx["credentials"],
                    warehouse_id=warehouse.id,
                    executor=executor,
                    model=ctx["selected_model"],
                    allowed_tables=ctx["allowed_tables"],
                    sf_executor=ctx["sf_executor"],
                    allowed_objects=ctx["sf_allowed_objects_list"],
                    report_tool_ctx=report_tool_ctx,
                ):
                    if evt["event"] == "_done":
                        done_data = evt["data"]
                    else:
                        yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'])}\n\n"

            else:
                # Salesforce-only path
                yield f"event: status\ndata: {json.dumps({'message': 'Connecting to Salesforce...'})}\n\n"
                async for evt in stream_claude_with_tools(
                    messages=ctx["messages"],
                    system_prompt=ctx["system_prompt"],
                    sf_executor=ctx["sf_executor"],
                    allowed_objects=ctx["sf_allowed_objects_list"],
                    model=ctx["selected_model"],
                ):
                    if evt["event"] == "_done":
                        done_data = evt["data"]
                    else:
                        yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'])}\n\n"

            duration_ms = int((time.time() - start_time) * 1000)

            if done_data is None:
                yield f"event: error\ndata: {json.dumps({'message': 'Stream ended without completion'})}\n\n"
                return

            response_text = done_data["response_text"]
            input_tokens = done_data["input_tokens"]
            output_tokens = done_data["output_tokens"]
            last_sql_result = done_data["last_sql_result"]

            # Visualization suggestion
            visualization = None
            chart_data = None
            if last_sql_result:
                chart_data = _parse_query_result(last_sql_result)
                if chart_data:
                    columns = list(chart_data[0].keys()) if chart_data else []
                    visualization = suggest_visualization(columns, chart_data)

            cost = calculate_cost(input_tokens, output_tokens, model=ctx["selected_model"])

            # Persist messages
            conversation = ctx["conversation"]
            user_message = ConversationMessage(
                conversation_id=conversation.id,
                role="user",
                content=request.message,
            )
            assistant_message = ConversationMessage(
                conversation_id=conversation.id,
                role="assistant",
                content=response_text,
                duration_ms=duration_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                visualization=json.dumps(visualization) if visualization else None,
                chart_data=json.dumps(chart_data) if chart_data else None,
            )
            db.add(user_message)
            db.add(assistant_message)

            conversation.updated_at = datetime.utcnow()

            token_usage = TokenUsageService.record_usage(
                db=db,
                user=user,
                conversation_id=conversation.id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                model=ctx["selected_model"],
            )
            db.commit()
            db.refresh(assistant_message)

            post_check = TokenUsageService.check_pre_query(db, user)

            done_event = {
                "conversation_id": conversation.id,
                "message_id": assistant_message.id,
                "response_text": response_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "weighted_tokens": token_usage.weighted_tokens,
                "duration_ms": duration_ms,
                "visualization": visualization,
                "chart_data": chart_data,
                "usage_warning": post_check.get("warning"),
                "usage_percent": post_check.get("usage_percent"),
            }
            yield f"event: done\ndata: {json.dumps(done_event)}\n\n"

        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            error_msg = str(e)
            if "credit balance is too low" in error_msg.lower():
                error_msg = "The AI service is temporarily unavailable due to API credit limits. Please contact the administrator."
            elif "rate_limit" in error_msg.lower():
                error_msg = "Too many requests. Please wait a moment and try again."
            elif "overloaded" in error_msg.lower():
                error_msg = "The AI service is currently busy. Please try again in a few seconds."
            elif "invalid_api_key" in error_msg.lower():
                error_msg = "API configuration error. Please contact the administrator."

            yield f"event: error\ndata: {json.dumps({'message': error_msg})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/conversations", response_model=ConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Create a new conversation (before the first message is sent)."""
    warehouse_connection_id = None
    warehouse_name = None

    if request.warehouse_id:
        warehouse = db.query(WarehouseConnection).filter(
            WarehouseConnection.id == request.warehouse_id,
            WarehouseConnection.user_id == user.id,
        ).first()
        if not warehouse:
            raise HTTPException(status_code=404, detail="Warehouse not found")
        warehouse_connection_id = warehouse.id
        warehouse_name = warehouse.name

    conversation = Conversation(
        id=str(uuid_mod.uuid4()),
        user_id=user.id,
        warehouse_connection_id=warehouse_connection_id,
        title=request.title or "New Chat",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        warehouse_id=conversation.warehouse_connection_id,
        warehouse_name=warehouse_name,
        created_at=conversation.created_at.isoformat() + "Z",
        updated_at=conversation.updated_at.isoformat() + "Z",
    )


@router.get("/api/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List user's conversations."""
    conversations = db.query(Conversation).options(
        joinedload(Conversation.warehouse_connection)
    ).filter(
        Conversation.user_id == user.id
    ).order_by(Conversation.updated_at.desc()).limit(50).all()

    result = []
    for c in conversations:
        warehouse_name = None
        if c.warehouse_connection:
            warehouse_name = c.warehouse_connection.name

        result.append(ConversationResponse(
            id=c.id,
            title=c.title,
            warehouse_id=c.warehouse_connection_id,
            warehouse_name=warehouse_name,
            created_at=c.created_at.isoformat() + "Z",
            updated_at=c.updated_at.isoformat() + "Z",
        ))

    return result


@router.get("/api/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_conversation_messages(
    conversation_id: str,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Get messages in a conversation."""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = db.query(ConversationMessage).options(
        joinedload(ConversationMessage.feedback)
    ).filter(
        ConversationMessage.conversation_id == conversation_id
    ).order_by(ConversationMessage.created_at.asc()).all()

    return [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at.isoformat() + "Z",
            duration_ms=m.duration_ms,
            input_tokens=m.input_tokens,
            output_tokens=m.output_tokens,
            feedback=m.feedback.rating if m.feedback else None,
            visualization=json.loads(m.visualization) if m.visualization else None,
            chart_data=json.loads(m.chart_data) if m.chart_data else None,
        )
        for m in messages
    ]


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Delete a conversation."""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    db.query(TokenUsage).filter(TokenUsage.conversation_id == conversation_id).delete()
    db.delete(conversation)
    db.commit()

    return {"success": True}


@router.patch("/api/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    request: RenameConversationRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Rename a conversation."""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    ).first()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation.title = request.title
    conversation.updated_at = datetime.utcnow()
    db.commit()

    return {"success": True}


# Legacy endpoints
@router.get("/warehouse/status")
async def legacy_warehouse_status(
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy endpoint for warehouse status."""
    if not user:
        return {
            "warehouse_type": None,
            "database_name": None,
            "connection_status": "disconnected",
            "connected_at": None,
        }

    warehouse = db.query(WarehouseConnection).filter(
        WarehouseConnection.user_id == user.id,
        WarehouseConnection.connection_status == "connected",
    ).first()

    if not warehouse:
        return {
            "warehouse_type": None,
            "database_name": None,
            "connection_status": "disconnected",
            "connected_at": None,
        }

    credentials = decrypt_credentials(warehouse.credentials_encrypted)

    return {
        "warehouse_type": warehouse.warehouse_type,
        "database_name": credentials.get("database") or warehouse.name,
        "connection_status": warehouse.connection_status,
        "connected_at": warehouse.last_tested_at.isoformat() + "Z" if warehouse.last_tested_at else None,
    }


@router.post("/chat")
async def legacy_chat(
    request: ChatRequest,
    user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy chat endpoint."""
    if not user:
        user = db.query(User).filter(User.id == "legacy_user").first()
        if not user:
            user = User(id="legacy_user", email="legacy@datachat.app", plan="pro")
            db.add(user)
            db.commit()

    result = await chat(
        ChatRequest(
            message=request.message,
            conversation_id=request.conversation_id or request.session_id if hasattr(request, 'session_id') else None,
            warehouse_id=request.warehouse_id if hasattr(request, 'warehouse_id') else None,
        ),
        user=user,
        db=db,
    )

    return {
        "success": result.success,
        "response": result.response,
        "session_id": result.conversation_id,
        "data": None,
        "query": None,
        "sql": None,
    }
