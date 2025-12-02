#!/bin/bash

# =============================================================================
# Test script for Pipeline Failure Agent
# =============================================================================

# Agent configuration
AGENT_URL="${AGENT_URL:-http://localhost:8000}"

# Server configuration
export PORT="${PORT:-8000}"

# Test payload
TEST_NAMESPACE="${TEST_NAMESPACE:-agent-user1}"
TEST_POD_NAME="${TEST_POD_NAME:-agent-c4b5477-mfkb7}"
TEST_CONTAINER_NAME="${TEST_CONTAINER_NAME:-}"

# =============================================================================

echo "=== Pipeline Failure Agent Test ==="
echo ""
echo "Agent URL: ${AGENT_URL}"
echo ""

# Health check
echo "--- Health Check ---"
curl -s "${AGENT_URL}/health" | python3 -m json.tool 2>/dev/null || echo "Health check failed"
echo ""

# Test failure report
echo "--- Sending Failure Report ---"
echo "Namespace: ${TEST_NAMESPACE}"
echo "Pod: ${TEST_POD_NAME}"
echo "Container: ${TEST_CONTAINER_NAME:-not specified}"
echo ""

PAYLOAD="{\"namespace\":\"${TEST_NAMESPACE}\",\"pod_name\":\"${TEST_POD_NAME}\""
if [ -n "${TEST_CONTAINER_NAME}" ]; then
    PAYLOAD="${PAYLOAD},\"container_name\":\"${TEST_CONTAINER_NAME}\""
fi
PAYLOAD="${PAYLOAD}}"

echo "Payload: ${PAYLOAD}"
echo ""

curl -i -X POST \
    -H "Content-Type: application/json" \
    -d "${PAYLOAD}" \
    "${AGENT_URL}/report-failure"

echo ""
echo "=== Test Complete ==="
