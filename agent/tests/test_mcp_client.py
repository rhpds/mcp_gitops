"""Unit tests for mcp_client.py"""
import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_client import MCPClient, MCPToolRegistry


class TestMCPClient:
    """Tests for the MCPClient class."""

    def test_init_sets_attributes(self):
        """Should initialize with correct attributes."""
        client = MCPClient("test-server", "http://localhost:8080/mcp", transport="sse")
        assert client.name == "test-server"
        assert client.url == "http://localhost:8080/mcp"
        assert client.transport == "sse"
        assert client.tools == []
        assert client.request_id == 0

    def test_init_default_transport(self):
        """Should default to streamable-http transport."""
        client = MCPClient("test", "http://localhost:8080")
        assert client.transport == "streamable-http"

    def test_get_base_url_simple(self):
        """Should extract base URL from simple URL."""
        client = MCPClient("test", "http://localhost:8080/mcp/sse")
        assert client._get_base_url() == "http://localhost:8080"

    def test_get_base_url_with_port(self):
        """Should preserve port in base URL."""
        client = MCPClient("test", "https://api.example.com:3000/path/to/endpoint")
        assert client._get_base_url() == "https://api.example.com:3000"

    def test_get_base_url_https(self):
        """Should handle HTTPS URLs."""
        client = MCPClient("test", "https://secure.example.com/api")
        assert client._get_base_url() == "https://secure.example.com"

    def test_next_id_increments(self):
        """Should increment request ID each call."""
        client = MCPClient("test", "http://localhost:8080")
        assert client._next_id() == 1
        assert client._next_id() == 2
        assert client._next_id() == 3
        assert client.request_id == 3

    def test_jsonrpc_request_format(self):
        """Should create valid JSON-RPC 2.0 request."""
        client = MCPClient("test", "http://localhost:8080")
        request = client._jsonrpc_request("tools/list", {"filter": "test"})
        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "tools/list"
        assert request["params"] == {"filter": "test"}
        assert "id" in request

    def test_jsonrpc_request_empty_params(self):
        """Should default params to empty dict."""
        client = MCPClient("test", "http://localhost:8080")
        request = client._jsonrpc_request("initialize")
        assert request["params"] == {}

    def test_jsonrpc_request_unique_ids(self):
        """Each request should have unique ID."""
        client = MCPClient("test", "http://localhost:8080")
        req1 = client._jsonrpc_request("method1")
        req2 = client._jsonrpc_request("method2")
        assert req1["id"] != req2["id"]

    def test_get_tools_for_llm_empty(self):
        """Should return empty list when no tools."""
        client = MCPClient("test", "http://localhost:8080")
        assert client.get_tools_for_llm() == []

    def test_get_tools_for_llm_converts_format(self):
        """Should convert MCP tools to OpenAI function format."""
        client = MCPClient("test", "http://localhost:8080")
        client.tools = [
            {
                "name": "pods_log",
                "description": "Get pod logs",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string"},
                        "name": {"type": "string"}
                    },
                    "required": ["namespace", "name"]
                }
            }
        ]
        llm_tools = client.get_tools_for_llm()
        assert len(llm_tools) == 1
        assert llm_tools[0]["type"] == "function"
        assert llm_tools[0]["function"]["name"] == "pods_log"
        assert llm_tools[0]["function"]["description"] == "Get pod logs"
        assert "properties" in llm_tools[0]["function"]["parameters"]

    def test_get_tools_for_llm_handles_missing_fields(self):
        """Should handle tools with missing optional fields."""
        client = MCPClient("test", "http://localhost:8080")
        client.tools = [{"name": "simple_tool"}]
        llm_tools = client.get_tools_for_llm()
        assert len(llm_tools) == 1
        assert llm_tools[0]["function"]["name"] == "simple_tool"
        assert llm_tools[0]["function"]["description"] == ""
        assert llm_tools[0]["function"]["parameters"] == {"type": "object", "properties": {}}


class TestMCPToolRegistry:
    """Tests for the MCPToolRegistry class."""

    def test_init_empty(self):
        """Should initialize with empty clients and mappings."""
        registry = MCPToolRegistry()
        assert registry.clients == {}
        assert registry.tool_to_client == {}

    def test_add_client(self):
        """Should add client to registry."""
        registry = MCPToolRegistry()
        client = MCPClient("openshift", "http://localhost:8080")
        registry.add_client(client)
        assert "openshift" in registry.clients
        assert registry.clients["openshift"] is client

    def test_add_multiple_clients(self):
        """Should support multiple clients."""
        registry = MCPToolRegistry()
        client1 = MCPClient("openshift", "http://localhost:8080")
        client2 = MCPClient("gitea", "http://localhost:8081")
        registry.add_client(client1)
        registry.add_client(client2)
        assert len(registry.clients) == 2
        assert "openshift" in registry.clients
        assert "gitea" in registry.clients

    def test_get_all_tools_empty(self):
        """Should return empty list when no clients."""
        registry = MCPToolRegistry()
        assert registry.get_all_tools() == []

    def test_get_all_tools_combines_clients(self):
        """Should combine tools from all clients."""
        registry = MCPToolRegistry()

        client1 = MCPClient("openshift", "http://localhost:8080")
        client1.tools = [{"name": "pods_log", "description": "Get logs"}]

        client2 = MCPClient("gitea", "http://localhost:8081")
        client2.tools = [{"name": "create_issue", "description": "Create issue"}]

        registry.add_client(client1)
        registry.add_client(client2)

        all_tools = registry.get_all_tools()
        assert len(all_tools) == 2
        tool_names = [t["function"]["name"] for t in all_tools]
        assert "pods_log" in tool_names
        assert "create_issue" in tool_names

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool(self):
        """Should return error for unknown tool."""
        registry = MCPToolRegistry()
        result = await registry.call_tool("unknown_tool", {})
        assert "Error" in result
        assert "unknown_tool" in result.lower()
