# Use RunPod's pre-built PyTorch image (much smaller, already has CUDA+PyTorch)
FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install WhisperX and RunPod SDK (in one layer to save space)
RUN pip install --no-cache-dir \
    git+https://github.com/m-bain/whisperx.git \
    runpod

# Create app directory
WORKDIR /app

# Create temp directory with more space (RunPod has more space in /workspace)
RUN mkdir -p /workspace/tmp && chmod 777 /workspace/tmp

# Set TMPDIR to use /workspace instead of /tmp
ENV TMPDIR=/workspace/tmp

# Copy entrypoint script (handler.py will be downloaded at runtime)
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Optional: Copy handler.py as fallback if GitHub is unreachable
COPY handler.py /app/handler.py.fallback

# Entrypoint for RunPod Serverless
CMD [ "/app/entrypoint.sh" ]
