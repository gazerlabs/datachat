"""MCP client for bridging external MCP servers into the Claude tool-use loop.

Connects to a remote MCP server (via SSE/Streamable HTTP), discovers its tools,
and provides methods to convert them to Anthropic tool format and dispatch calls.
"""

import logging
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class MCPBridge:
    """Manages an MCP client session and bridges tools into the Anthropic API."""

    def __init__(self, server_url: str, headers: dict[str, str] | None = None):
        self.server_url = server_url
        self.headers = headers or {}
        self._session: ClientSession | None = None
        self._read = None
        self._write = None
        self._cm = None
        self._tools_cache: list[dict] | None = None
        self._tool_names: set[str] = set()

    async def connect(self) -> None:
        """Connect to the MCP server and initialize the session."""
        # Try streamable HTTP first (newer protocol), fall back to SSE
        try:
            self._cm = streamablehttp_client(self.server_url, headers=self.headers)
            self._read, self._write = await self._cm.__aenter__()
            self._session = ClientSession(self._read, self._write)
            await self._session.__aenter__()
            await self._session.initialize()
            logger.info(f"MCP session initialized via streamable HTTP with {self.server_url}")
        except Exception as e:
            logger.info(f"Streamable HTTP failed ({e}), falling back to SSE")
            # Clean up failed attempt
            if self._session:
                try:
                    await self._session.__aexit__(None, None, None)
                except Exception:
                    pass
                self._session = None
            if self._cm:
                try:
                    await self._cm.__aexit__(None, None, None)
                except Exception:
                    pass
                self._cm = None
            # Fall back to SSE
            self._cm = sse_client(self.server_url, headers=self.headers)
            self._read, self._write = await self._cm.__aenter__()
            self._session = ClientSession(self._read, self._write)
            await self._session.__aenter__()
            await self._session.initialize()
            logger.info(f"MCP session initialized via SSE with {self.server_url}")

    async def close(self) -> None:
        """Close the MCP session and transport."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                logger.debug("MCP session cleanup failed", exc_info=True)
            self._session = None
        if self._cm:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:
                logger.debug("MCP transport cleanup failed", exc_info=True)
            self._cm = None

    async def get_tools_as_anthropic_format(self) -> list[dict]:
        """Discover tools from the MCP server and return in Anthropic tool format."""
        if self._tools_cache is not None:
            return self._tools_cache

        if not self._session:
            raise RuntimeError("MCP session not initialized. Call connect() first.")

        result = await self._session.list_tools()
        tools = []
        for tool in result.tools:
            anthropic_tool = {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            tools.append(anthropic_tool)
            self._tool_names.add(tool.name)

        self._tools_cache = tools
        logger.info(f"Discovered {len(tools)} tools from MCP server: {[t['name'] for t in tools]}")
        return tools

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to this MCP bridge."""
        return tool_name in self._tool_names

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on the MCP server and return the result as text."""
        if not self._session:
            raise RuntimeError("MCP session not initialized. Call connect() first.")

        try:
            result = await self._session.call_tool(tool_name, arguments)
        except Exception as e:
            error_msg = str(e)
            if "rate" in error_msg.lower() or "limit" in error_msg.lower():
                return f"Salesforce API rate limit hit: {error_msg}. Please wait a moment and try again."
            raise

        # Concatenate text content from the result
        text_parts = []
        for content in result.content:
            if hasattr(content, "text"):
                text_parts.append(content.text)
            elif hasattr(content, "data"):
                text_parts.append(str(content.data))

        return "\n".join(text_parts) if text_parts else "No results returned."
