# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python main.py

# Build container
podman build -t pipeline-agent -f Containerfile .
```

## Environment Variables

- `LITELLM_URL` - Base URL for LiteLLM API
- `LITELLM_API_KEY` - API key for LiteLLM
- `LITELLM_MODEL` - Model to use (default: Llama-4-Scout-17B-16E-W4A16)
- `MCP_OPENSHIFT_URL` - OpenShift MCP server URL
- `MCP_OPENSHIFT_TRANSPORT` - Transport type: `sse` or `streamable-http` (default: sse)
- `MCP_GITEA_URL` - Gitea MCP server URL
- `MCP_GITEA_TRANSPORT` - Transport type: `sse` or `streamable-http` (default: streamable-http)
- `GITEA_OWNER` - Gitea repository owner for issue creation (default: user1)
- `GITEA_REPO` - Gitea repository name for issue creation (default: mcp)
- `PORT` - Server port (default: 8000)

## Architecture

Pipeline Failure Analysis Agent that receives webhook calls from Tekton pipelines and uses LLM tool calling via MCP servers.

1. **HTTP Server** (`main.py`) - FastAPI server with `/report-failure` endpoint accepting POST requests with `{namespace, pod_name, container_name}`

2. **MCP Client** (`mcp_client.py`) - Connects to external MCP servers to discover and call tools
   - Supports SSE transport (OpenShift)
   - Supports streamable-http transport (Gitea)

3. **Agent Loop** - Iterative LiteLLM completion loop that:
   - Gets available tools from MCP servers at startup
   - Forwards tool calls from the model to the appropriate MCP server
   - Returns results back to the model until completion

The model decides which tools to call based on the prompt. The agent only executes tools when requested by the model.
