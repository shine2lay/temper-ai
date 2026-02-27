#!/bin/bash
# Start vLLM server with tool-use support
# Usage: ./scripts/start-vllm.sh

CONTAINER_NAME="vllm-qwen3"
IMAGE="nvcr.io/nvidia/vllm:25.12.post1-py3"
MODEL="Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
SERVED_NAME="qwen3-next"

# Stop existing container if running
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping existing ${CONTAINER_NAME}..."
    docker stop "$CONTAINER_NAME" 2>/dev/null
    docker rm "$CONTAINER_NAME" 2>/dev/null
fi

echo "Starting ${CONTAINER_NAME} with tool-use enabled..."

docker run -d \
    --name "$CONTAINER_NAME" \
    --gpus all \
    --ipc=host \
    -p 8000:8000 \
    -v "${HOME}/.cache/huggingface:/root/.cache/huggingface" \
    "$IMAGE" \
    vllm serve "$MODEL" \
        --host 0.0.0.0 \
        --port 8000 \
        --tensor-parallel-size 1 \
        --gpu-memory-utilization 0.70 \
        --max-model-len 32768 \
        --reasoning-parser qwen3 \
        --served-model-name "$SERVED_NAME" \
        --enforce-eager \
        --enable-auto-tool-choice \
        --tool-call-parser hermes

echo "Waiting for vLLM to be ready..."
for i in $(seq 1 60); do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "vLLM is ready!"
        exit 0
    fi
    sleep 5
done

echo "Warning: vLLM did not become healthy within 5 minutes. Check logs with: docker logs $CONTAINER_NAME"
