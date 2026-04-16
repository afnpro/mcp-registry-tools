#!/bin/sh
# Pre-downloads the sentence-transformers model to the HOST path that docker-compose.yml
# bind-mounts into the container at /app/registry/models.
#
# Why a bind mount (not a named volume)?
# Named Docker volumes are managed by Docker and not directly writable from the host.
# bootstrap.sh writes to ${HOME}/mcp-gateway/models on the host filesystem.
# docker-compose.yml maps that exact path into the container with:
#   - ${HOME}/mcp-gateway/models:/app/registry/models
# This makes the pre-downloaded model immediately visible inside the container.
#
# M6 finding: the gateway reads models from /app/registry/models/<model-name>,
# NOT /app/models/<model-name> as the spec originally assumed.
#
# If this script is skipped or HuggingFace Hub is blocked:
# sentence-transformers will download the model automatically on first gateway startup.
# The first startup will then take 2-5 extra minutes depending on network speed.
#
# Uses pip and Python only — no curl, no apt, no wget.
set -e

MODELS_DIR="${HOME}/mcp-gateway/models"
MODEL_NAME="all-MiniLM-L6-v2"
MODEL_PATH="${MODELS_DIR}/${MODEL_NAME}"

echo "==> Checking embeddings model at ${MODEL_PATH}..."

if [ -d "${MODEL_PATH}" ] && [ -f "${MODEL_PATH}/model.safetensors" ]; then
    echo "    Model already present. Skipping download."
    exit 0
fi

echo "==> Downloading ${MODEL_NAME} (~90MB) via Python..."
mkdir -p "${MODELS_DIR}"

pip install -q sentence-transformers huggingface-hub

python3 - <<PYEOF
import os, shutil, glob
from sentence_transformers import SentenceTransformer

models_dir = "${MODELS_DIR}"
model_name = "all-MiniLM-L6-v2"
model_path = os.path.join(models_dir, model_name)

# Download into models_dir cache
model = SentenceTransformer(
    f"sentence-transformers/{model_name}",
    cache_folder=models_dir
)

# sentence-transformers caches under models--sentence-transformers--<name>/snapshots/<hash>/
# Copy the snapshot to a clean direct path that the gateway loads from
cached = os.path.join(models_dir, f"models--sentence-transformers--{model_name}")
if os.path.isdir(cached) and not os.path.isdir(model_path):
    snapshots = glob.glob(os.path.join(cached, "snapshots", "*"))
    if snapshots:
        shutil.copytree(snapshots[0], model_path, dirs_exist_ok=True)
        print(f"Model copied to {model_path}")
    else:
        print(f"WARNING: snapshot not found in {cached}. Gateway will download on startup.")
else:
    print(f"Model ready at {model_path}")
PYEOF

echo "==> Done. ${MODEL_PATH} is now mapped into the container via the bind mount."
echo "    The gateway will load the model from /app/registry/models/${MODEL_NAME} on startup."
