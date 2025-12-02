import os
import json
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import litellm

from mcp_client import MCPClient, MCPToolRegistry

# Global registry for MCP tools
mcp_registry = MCPToolRegistry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MCP connections on startup."""
    print("\n" + "="*60)
    print("🚀 Pipeline Failure Agent - Starting up")
    print("="*60)

    # Configure MCP clients from environment variables
    print("\n📋 Loading MCP configuration from environment...")
    openshift_url = os.environ.get("MCP_OPENSHIFT_URL")
    openshift_transport = os.environ.get("MCP_OPENSHIFT_TRANSPORT", "sse")
    gitea_url = os.environ.get("MCP_GITEA_URL")
    gitea_transport = os.environ.get("MCP_GITEA_TRANSPORT", "streamable-http")

    if openshift_url:
        print(f"   OpenShift: {openshift_url} ({openshift_transport})")
        mcp_registry.add_client(MCPClient("openshift", openshift_url, transport=openshift_transport))
    else:
        print("   ⚠️  MCP_OPENSHIFT_URL not set, OpenShift tools unavailable")

    if gitea_url:
        print(f"   Gitea: {gitea_url} ({gitea_transport})")
        mcp_registry.add_client(MCPClient("gitea", gitea_url, transport=gitea_transport))
    else:
        print("   ⚠️  MCP_GITEA_URL not set, Gitea tools unavailable")

    # Initialize all MCP connections
    await mcp_registry.initialize_all()

    total_tools = len(mcp_registry.get_all_tools())
    print(f"\n✅ Startup complete - {total_tools} tools available")
    print("="*60 + "\n")

    yield


app = FastAPI(title="Pipeline Failure Agent", lifespan=lifespan)

MODEL_PROMPT = """You are a helpful assistant. You have access to a number of tools.
Whenever a tool is called, be sure to return the Response in a friendly and helpful tone.
"""

PROMPT_TEMPLATE = """You are an expert OpenShift administrator. Your task is to analyze pod logs, summarize the error, and generate a JSON object to create a Gitea issue for tracking. Follow the format in the examples below.

---
EXAMPLE 1:
Input: The logs for pod 'frontend-v2-abcde' in namespace 'webapp' show: ImagePullBackOff: Back-off pulling image 'my-registry/frontend:latest'.

Output:
The pod is in an **ImagePullBackOff** state. This means Kubernetes could not pull the container image 'my-registry/frontend:latest', likely due to an incorrect image tag or authentication issues.
{{"name":"create_issue","arguments":{{"owner":"{gitea_owner}","repo":"{gitea_repo}","title":"Issue with pipeline","body":"### Cluster/namespace location\\nwebapp/frontend-v2-abcde\\n\\n### Summary of the problem\\nThe pod is failing to start due to an ImagePullBackOff error.\\n\\n### Detailed error/code\\nImagePullBackOff: Back-off pulling image 'my-registry/frontend:latest'\\n\\n### Possible solutions\\n1. Verify the image tag 'latest' exists in the 'my-registry/frontend' repository.\\n2. Check for authentication errors with the image registry."}}}}

---
EXAMPLE 2:
Input: The logs for pod 'data-processor-xyz' in namespace 'pipelines' show: CrashLoopBackOff. Last state: OOMKilled.

Output:
The pod is in a **CrashLoopBackOff** state because it was **OOMKilled**. The container tried to use more memory than its configured limit.
{{"name":"create_issue","arguments":{{"owner":"{gitea_owner}","repo":"{gitea_repo}","title":"Issue with pipeline","body":"### Cluster/namespace location\\npipelines/data-processor-xyz\\n\\n### Summary of the problem\\nThe pod is in a CrashLoopBackOff state because it was OOMKilled (Out of Memory).\\n\\n### Detailed error/code\\nCrashLoopBackOff, Last state: OOMKilled\\n\\n### Possible solutions\\n1. Increase the memory limit in the pod's deployment configuration.\\n2. Analyze the application for memory leaks."}}}}
---

NOW, YOUR TURN:

Steps:
1. First, get the pod logs using: {{"name":"pods_log","arguments":{{"namespace":"{namespace}","name":"{pod_name}","tailLines":10}}}}
2. Analyze the logs for errors
3. Create a Gitea issue with the error summary using: {{"name":"create_issue","arguments":{{"owner":"{gitea_owner}","repo":"{gitea_repo}","title":"Issue with Agent pipeline","body":"<summary of the error>"}}}}

Start by getting the logs for pod '{pod_name}' in namespace '{namespace}'.
"""


class FailureReport(BaseModel):
    namespace: str
    pod_name: str
    container_name: str = None


def extract_json_tool_call(content: str, valid_tool_names: list[str] = None) -> dict | None:
    """Extract a JSON tool call from text content.

    Args:
        content: The text content to search for JSON tool calls
        valid_tool_names: List of valid tool names to match against
    """
    import re

    def is_valid_tool_call(parsed: dict) -> bool:
        """Check if parsed JSON is a valid tool call."""
        if "name" not in parsed:
            return False
        if valid_tool_names and parsed["name"] not in valid_tool_names:
            return False
        return True

    # Try to find all JSON objects in the content
    candidates = []

    # Find all potential JSON objects by matching braces
    i = 0
    while i < len(content):
        if content[i] == '{':
            depth = 0
            start = i
            for j in range(i, len(content)):
                if content[j] == '{':
                    depth += 1
                elif content[j] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(content[start:j+1])
                            if is_valid_tool_call(parsed):
                                candidates.append(parsed)
                        except json.JSONDecodeError:
                            pass
                        i = j
                        break
        i += 1

    # Return the first valid tool call found
    if candidates:
        return candidates[0]

    return None


async def run_agent(namespace: str, pod_name: str, container_name: str = None) -> str:
    """Run the agent to analyze a failed pod and create an issue."""
    print(f"\n🚀 Starting agent run...")
    print(f"   Pod: {pod_name}")
    print(f"   Namespace: {namespace}")
    print(f"   Container: {container_name or '(default)'}")

    gitea_owner = os.environ.get("GITEA_OWNER", "user1")
    gitea_repo = os.environ.get("GITEA_REPO", "mcp")

    formatted_prompt = PROMPT_TEMPLATE.format(
        pod_name=pod_name,
        namespace=namespace,
        gitea_owner=gitea_owner,
        gitea_repo=gitea_repo
    )
    print(f"\n📝 Prompt prepared ({len(formatted_prompt)} chars)")
    print(f"   Gitea target: {gitea_owner}/{gitea_repo}")

    litellm_url = os.environ.get("LITELLM_URL", "")
    litellm_api_key = os.environ.get("LITELLM_API_KEY", "")
    litellm_model = os.environ.get("LITELLM_MODEL", "openai/Llama-4-Scout-17B-16E-W4A16")

    print(f"\n🤖 LLM Configuration:")
    print(f"   Model: {litellm_model}")
    print(f"   API Base: {litellm_url or '(default)'}")

    messages = [
        {"role": "system", "content": MODEL_PROMPT},
        {"role": "user", "content": formatted_prompt}
    ]

    # Get tools from MCP servers
    tools = mcp_registry.get_all_tools()
    tool_names = [t["function"]["name"] for t in tools]
    print(f"\n🔧 Available tools ({len(tools)}): {tool_names}")

    if not tools:
        print("❌ No tools available!")
        return "Error: No tools available from MCP servers"

    max_iterations = 10
    iteration = 0

    print(f"\n{'='*60}")
    print("Starting agent loop (max {max_iterations} iterations)")
    print(f"{'='*60}")

    while iteration < max_iterations:
        iteration += 1
        print(f"\n┌─ Iteration {iteration}/{max_iterations} ─────────────────────────────────┐")

        try:
            print("│  📡 Calling LLM...")
            completion_kwargs = {
                "model": litellm_model,
                "messages": messages,
                "tools": tools,
                "api_key": litellm_api_key
            }
            if litellm_url:
                completion_kwargs["api_base"] = litellm_url

            response = await asyncio.to_thread(
                litellm.completion,
                **completion_kwargs
            )
            print("│  ✓ LLM response received")
        except Exception as e:
            print(f"│  ❌ LLM error: {str(e)}")
            return f"Error calling LiteLLM: {str(e)}"

        choice = response.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason
        print(f"│  Finish reason: {finish_reason}")

        if message.tool_calls:
            print(f"│  📞 Model requested {len(message.tool_calls)} tool call(s)")
            messages.append(message.model_dump())

            for i, tool_call in enumerate(message.tool_calls, 1):
                tool_name = tool_call.function.name
                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}

                print(f"│")
                print(f"│  🔧 Tool call {i}/{len(message.tool_calls)}: {tool_name}")
                print(f"│     Arguments: {json.dumps(arguments, indent=2).replace(chr(10), chr(10) + '│     ')}")
                print(f"│     Executing...")
                try:
                    result = await mcp_registry.call_tool(tool_name, arguments)
                    print(f"│     ✓ Tool completed successfully")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    result = f"Error calling tool: {str(e)}"
                    print(f"│     ❌ Tool failed: {str(e)}")

                result_preview = result[:200] + "..." if len(result) > 200 else result
                print(f"│     Result: {result_preview}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
        else:
            content = message.content or ""
            print(f"│  💬 Model returned text response")

            # Show a preview of the content
            content_preview = content[:150].replace('\n', ' ')
            if len(content) > 150:
                content_preview += "..."
            print(f"│     Preview: {content_preview}")

            # Check if the model output a JSON tool call in text form
            available_tool_names = [t["function"]["name"] for t in tools]
            json_tool_call = extract_json_tool_call(content, available_tool_names)
            if json_tool_call:
                tool_name = json_tool_call.get("name")
                arguments = json_tool_call.get("arguments") or json_tool_call.get("parameters", {})

                print(f"│")
                print(f"│  🔍 Found JSON tool call in text: {tool_name}")
                print(f"│     Arguments: {json.dumps(arguments, indent=2).replace(chr(10), chr(10) + '│     ')}")
                print(f"│     Executing...")
                try:
                    result = await mcp_registry.call_tool(tool_name, arguments)
                    print(f"│     ✓ Tool completed successfully")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    result = f"Error calling tool: {str(e)}"
                    print(f"│     ❌ Tool failed: {str(e)}")

                result_preview = result[:200] + "..." if len(result) > 200 else result
                print(f"│     Result: {result_preview}")

                # If create_issue was successful, we're done
                # Check for actual errors (starts with "Error:" or contains error JSON key)
                is_error = result.startswith("Error:") or '"error":' in result.lower()
                if tool_name == "create_issue" and not is_error:
                    print(f"│")
                    print(f"└─ ✅ Agent completed: Issue created successfully")
                    return f"Issue created: {result}"

                # Add the response and tool result to continue the conversation
                print(f"│  ↩ Continuing conversation with tool result...")
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": f"Tool result:\n{result}\n\nPlease continue with your analysis and create the issue."})
            else:
                print(f"│")
                print(f"└─ ✅ Agent completed with final response")
                print(f"\n{'─'*60}")
                print(f"Final response:\n{content}")
                print(f"{'─'*60}")
                return content

    print(f"\n⚠️ Agent reached maximum iterations ({max_iterations}) without completing")
    return "Agent reached maximum iterations without completing."


@app.post("/report-failure")
async def report_failure(report: FailureReport):
    """Handle a pipeline failure report and analyze it."""
    print(f"\n{'='*60}")
    print(f"📥 Received failure report")
    print(f"{'='*60}")
    print(f"   Namespace: {report.namespace}")
    print(f"   Pod:       {report.pod_name}")
    print(f"   Container: {report.container_name or '(not specified)'}")

    try:
        result = await run_agent(
            namespace=report.namespace,
            pod_name=report.pod_name,
            container_name=report.container_name
        )
        print(f"\n{'='*60}")
        print(f"📤 Sending response: success")
        print(f"{'='*60}\n")
        return {"status": "success", "result": result}
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"📤 Sending response: error - {str(e)}")
        print(f"{'='*60}\n")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
