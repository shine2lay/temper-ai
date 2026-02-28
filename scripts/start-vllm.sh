#!/bin/bash
# Start vLLM server with tool-use support
# Usage: ./scripts/start-vllm.sh [--old]
#   --old  Start the previous Qwen3-Next-80B model instead of Qwen3.5-122B

CONTAINER_NAME="vllm-qwen3"
SERVED_NAME="qwen3-next"

if [ "$1" = "--old" ]; then
    IMAGE="nvcr.io/nvidia/vllm:25.12.post1-py3"
    MODEL="Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
    EXTRA_ARGS="--reasoning-parser qwen3"
    GPU_MEM_UTIL="0.70"
    TOOL_PARSER="hermes"
    # NVIDIA container entrypoint wraps command differently
    SERVE_PREFIX="vllm serve"
else
    IMAGE="vllm/vllm-openai:cu130-nightly"
    MODEL="cyankiwi/Qwen3.5-122B-A10B-AWQ-4bit"
    EXTRA_ARGS=""
    GPU_MEM_UTIL="0.80"
    TOOL_PARSER="qwen3_coder"
    # Standard vllm-openai image has "vllm serve" as entrypoint already
    SERVE_PREFIX=""
fi

# Stop existing container if running
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping existing ${CONTAINER_NAME}..."
    docker stop "$CONTAINER_NAME" 2>/dev/null
    docker rm "$CONTAINER_NAME" 2>/dev/null
fi

echo "Starting ${CONTAINER_NAME} with model: ${MODEL}..."

docker run -d \
    --name "$CONTAINER_NAME" \
    --gpus all \
    --ipc=host \
    --shm-size 64gb \
    -p 8000:8000 \
    -v "${HOME}/.cache/huggingface:/root/.cache/huggingface" \
    "$IMAGE" \
    $SERVE_PREFIX "$MODEL" \
        --host 0.0.0.0 \
        --port 8000 \
        --tensor-parallel-size 1 \
        --gpu-memory-utilization "$GPU_MEM_UTIL" \
        --max-model-len 32768 \
        --served-model-name "$SERVED_NAME" \
        --enforce-eager \
        --enable-auto-tool-choice \
        --tool-call-parser "$TOOL_PARSER" \
        $EXTRA_ARGS

echo "Waiting for vLLM to be ready (model download may take a while on first run)..."
for i in $(seq 1 120); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "vLLM is ready!"
        exit 0
    fi
    sleep 10
done

echo "Warning: vLLM did not become healthy within 20 minutes. Check logs with: docker logs $CONTAINER_NAME"
