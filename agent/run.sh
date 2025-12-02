#!/bin/bash

LITELLM_URL=https://litellm-litemaas.apps.prod.rhoai.rh-aiservices-bu.com/v1
LITELLM_API_KEY=sk-Z9kMTaKyZOE5NPShqPhzOg
LITELLM_MODEL=openai/Llama-4-Scout-17B-16E-W4A16
MCP_OPENSHIFT_URL=https://mcp-openshift-mcp-user1.apps.cluster-kd7wl.dynamic.redhatworkshops.io/sse#openshift
MCP_OPENSHIFT_TRANSPORT=sse
MCP_GITEA_URL=https://mcp-gitea-mcp-user1.apps.cluster-kd7wl.dynamic.redhatworkshops.io/mcp
MCP_GITEA_TRANSPORT=streamable-http
PORT=8000

podman run --rm \
  --name=agent \
  --publish ${PORT}:${PORT} \
  --env LITELLM_URL=${LITELLM_URL} \
  --env LITELLM_API_KEY=${LITELLM_API_KEY} \
  --env LITELLM_MODEL=${LITELLM_MODEL} \
  --env MCP_OPENSHIFT_URL=${MCP_OPENSHIFT_URL} \
  --env MCP_OPENSHIFT_TRANSPORT=${MCP_OPENSHIFT_TRANSPORT} \
  --env MCP_GITEA_URL=${MCP_GITEA_URL} \
  --env MCP_GITEA_TRANSPORT=${MCP_GITEA_TRANSPORT} \
  --env MCP_GITEA_USER=user2 \
  --env MCP_GITEA_REPO=mcp2 \
  --env PORT=${PORT} \
  quay.io/rhpds/agent:latest
