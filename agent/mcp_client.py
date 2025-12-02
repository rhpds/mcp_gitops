import json
import httpx
from urllib.parse import urlparse, urljoin


class MCPClient:
    """Client for connecting to MCP servers."""

    def __init__(self, name: str, url: str, transport: str = "streamable-http"):
        self.name = name
        self.url = url
        self.transport = transport
        self.tools = []
        self.request_id = 0
        self._session_id = None
        self._message_endpoint = None

    def _get_base_url(self) -> str:
        """Extract base URL (scheme + host) from the configured URL."""
        parsed = urlparse(self.url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    def _jsonrpc_request(self, method: str, params: dict = None) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {}
        }

    async def initialize(self) -> None:
        """Initialize connection and discover tools."""
        print(f"   Connecting to {self.name} ({self.transport})...")
        print(f"   URL: {self.url}")
        if self.transport == "streamable-http":
            await self._init_streamable_http()
        elif self.transport == "sse":
            await self._init_sse()

    async def _init_streamable_http(self) -> None:
        """Initialize using streamable-http transport."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

        async with httpx.AsyncClient(timeout=30) as client:
            # Initialize
            init_request = self._jsonrpc_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pipeline-agent", "version": "1.0.0"}
            })
            response = await client.post(self.url, json=init_request, headers=headers)
            response.raise_for_status()

            # Save session ID if returned
            self._session_id = response.headers.get("mcp-session-id")

            # Send initialized notification
            initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            notify_headers = headers.copy()
            if self._session_id:
                notify_headers["mcp-session-id"] = self._session_id
            await client.post(self.url, json=initialized, headers=notify_headers)

            # List tools
            list_request = self._jsonrpc_request("tools/list")
            list_headers = headers.copy()
            if self._session_id:
                list_headers["mcp-session-id"] = self._session_id
            response = await client.post(self.url, json=list_request, headers=list_headers)
            response.raise_for_status()
            result = response.json()
            self.tools = result.get("result", {}).get("tools", [])

    async def _init_sse(self) -> None:
        """Initialize using SSE transport.

        In SSE transport:
        1. Connect to /sse endpoint
        2. Receive 'endpoint' event with message URL
        3. POST messages to that URL
        4. Responses come back on the SSE stream
        """
        import asyncio

        base_url = self._get_base_url()
        headers = {"Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("GET", self.url) as sse_response:
                # Collect lines from SSE stream
                lines_iterator = sse_response.aiter_lines()

                # First, get the endpoint URL from first data line
                endpoint_path = None
                async for line in lines_iterator:
                    if line.startswith("data: "):
                        endpoint_path = line[6:].strip()
                        break

                if endpoint_path:
                    if endpoint_path.startswith("/"):
                        self._message_endpoint = base_url + endpoint_path
                    elif endpoint_path.startswith("http"):
                        self._message_endpoint = endpoint_path
                    else:
                        self._message_endpoint = base_url + "/" + endpoint_path
                else:
                    self._message_endpoint = self.url.replace("/sse", "/message")

                print(f"   SSE message endpoint: {self._message_endpoint}")

                # Create a queue to collect SSE responses
                response_queue = asyncio.Queue()

                # Background task to read SSE events
                async def read_sse_events():
                    try:
                        async for line in lines_iterator:
                            if line.startswith("data: "):
                                data = line[6:].strip()
                                if data:
                                    try:
                                        msg = json.loads(data)
                                        await response_queue.put(msg)
                                    except json.JSONDecodeError:
                                        pass
                    except Exception:
                        pass

                # Start reading SSE in background
                reader_task = asyncio.create_task(read_sse_events())

                try:
                    # Send initialize request
                    init_request = self._jsonrpc_request("initialize", {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pipeline-agent", "version": "1.0.0"}
                    })
                    await client.post(self._message_endpoint, json=init_request, headers=headers)

                    # Wait for initialize response
                    init_result = await asyncio.wait_for(response_queue.get(), timeout=10)
                    print(f"   SSE init result: {init_result}")

                    # Send initialized notification
                    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                    await client.post(self._message_endpoint, json=initialized, headers=headers)

                    # Small delay to let notification process
                    await asyncio.sleep(0.1)

                    # Send tools/list request
                    list_request = self._jsonrpc_request("tools/list")
                    await client.post(self._message_endpoint, json=list_request, headers=headers)

                    # Wait for tools/list response
                    list_result = await asyncio.wait_for(response_queue.get(), timeout=10)

                    if list_result and "result" in list_result:
                        self.tools = list_result.get("result", {}).get("tools", [])
                    else:
                        print(f"   SSE tools/list result: {list_result}")

                finally:
                    reader_task.cancel()
                    try:
                        await reader_task
                    except asyncio.CancelledError:
                        pass

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server."""
        print(f"│        MCP [{self.name}] calling: {tool_name}")
        request = self._jsonrpc_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

        if self.transport == "sse":
            print(f"│        Transport: SSE")
            result = await self._sse_call(request)
        else:
            print(f"│        Transport: streamable-http")
            if self._session_id:
                headers["mcp-session-id"] = self._session_id
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(self.url, json=request, headers=headers)
                response.raise_for_status()
                result = response.json()

        if "error" in result:
            error_msg = result['error'].get('message', 'Unknown error')
            print(f"│        MCP error: {error_msg}")
            return f"Error: {error_msg}"

        content = result.get("result", {}).get("content", [])
        if content:
            # Extract text from content blocks
            texts = [c.get("text", str(c)) for c in content if isinstance(c, dict)]
            response_text = "\n".join(texts) if texts else str(content)
            print(f"│        MCP response: {len(response_text)} chars")
            return response_text
        return str(result.get("result", "No result"))

    async def _sse_call(self, request: dict) -> dict:
        """Make an SSE call - open connection, initialize, send request, read response."""
        import asyncio

        base_url = self._get_base_url()
        headers = {"Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("GET", self.url) as sse_response:
                lines_iterator = sse_response.aiter_lines()

                # Get message endpoint from first data line
                endpoint_path = None
                async for line in lines_iterator:
                    if line.startswith("data: "):
                        endpoint_path = line[6:].strip()
                        break

                if endpoint_path:
                    if endpoint_path.startswith("/"):
                        message_endpoint = base_url + endpoint_path
                    elif endpoint_path.startswith("http"):
                        message_endpoint = endpoint_path
                    else:
                        message_endpoint = base_url + "/" + endpoint_path
                else:
                    message_endpoint = self._message_endpoint

                # Queue for responses
                response_queue = asyncio.Queue()

                async def read_sse_events():
                    try:
                        async for line in lines_iterator:
                            if line.startswith("data: "):
                                data = line[6:].strip()
                                if data:
                                    try:
                                        msg = json.loads(data)
                                        await response_queue.put(msg)
                                    except json.JSONDecodeError:
                                        pass
                    except Exception:
                        pass

                reader_task = asyncio.create_task(read_sse_events())

                try:
                    # Must initialize session before calling tools
                    init_request = self._jsonrpc_request("initialize", {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pipeline-agent", "version": "1.0.0"}
                    })
                    await client.post(message_endpoint, json=init_request, headers=headers)
                    await asyncio.wait_for(response_queue.get(), timeout=10)

                    # Send initialized notification
                    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
                    await client.post(message_endpoint, json=initialized, headers=headers)
                    await asyncio.sleep(0.1)

                    # Now send the actual tool call request
                    await client.post(message_endpoint, json=request, headers=headers)

                    # Wait for response
                    result = await asyncio.wait_for(response_queue.get(), timeout=30)
                    return result
                finally:
                    reader_task.cancel()
                    try:
                        await reader_task
                    except asyncio.CancelledError:
                        pass

        return {}

    def get_tools_for_llm(self) -> list[dict]:
        """Convert MCP tools to OpenAI function calling format."""
        llm_tools = []
        for tool in self.tools:
            llm_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}})
                }
            })
        return llm_tools


class MCPToolRegistry:
    """Registry for managing multiple MCP servers and their tools."""

    def __init__(self):
        self.clients: dict[str, MCPClient] = {}
        self.tool_to_client: dict[str, MCPClient] = {}

    def add_client(self, client: MCPClient) -> None:
        """Add an MCP client to the registry."""
        self.clients[client.name] = client

    async def initialize_all(self) -> None:
        """Initialize all registered clients."""
        print(f"\n🔌 Initializing MCP connections ({len(self.clients)} servers)...")
        for client in self.clients.values():
            try:
                await client.initialize()
                print(f"   ✅ {client.name}: connected")
                tool_names = [t['name'] for t in client.tools]
                print(f"      Tools ({len(tool_names)}): {tool_names}")
                # Map tools to clients
                for tool in client.tools:
                    self.tool_to_client[tool["name"]] = client
            except Exception as e:
                print(f"   ❌ {client.name}: failed - {e}")

    def get_all_tools(self) -> list[dict]:
        """Get all tools from all clients in LLM format."""
        all_tools = []
        for client in self.clients.values():
            all_tools.extend(client.get_tools_for_llm())
        return all_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool by name, routing to the appropriate MCP server."""
        client = self.tool_to_client.get(tool_name)
        if not client:
            print(f"│        ❌ Unknown tool: {tool_name}")
            return f"Error: Unknown tool '{tool_name}'"
        print(f"│        Routing to MCP server: {client.name}")
        return await client.call_tool(tool_name, arguments)
