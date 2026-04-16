#!/bin/sh
# Clones mcp-gateway-registry as a git submodule.
# Run once: ./scripts/setup-gateway-source.sh
set -e

REPO_URL="https://github.com/agentic-community/mcp-gateway-registry.git"
TARGET="mcp-gateway-registry"

if [ -d "${TARGET}/.git" ]; then
    echo "==> mcp-gateway-registry already cloned. Pulling latest..."
    git -C "${TARGET}" pull --ff-only
else
    echo "==> Cloning mcp-gateway-registry from GitHub..."
    git clone --depth 1 "${REPO_URL}" "${TARGET}"
fi

# Register as submodule if not already
if ! grep -q "mcp-gateway-registry" .gitmodules 2>/dev/null; then
    git submodule add "${REPO_URL}" "${TARGET}" 2>/dev/null || true
fi

echo "==> Source ready at ./${TARGET}"
echo "==> Next: inspect ${TARGET}/Dockerfile and ${TARGET}/requirements.txt"
echo "    then run: docker compose up -d --build"
