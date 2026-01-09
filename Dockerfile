# Use RunPod's pre-built PyTorch image (much smaller, already has CUDA+PyTorch)
FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install WhisperX and RunPod SDK (in one layer to save space)
RUN pip install --no-cache-dir \
    git+https://github.com/m-bain/whisperx.git \
    runpod

# Create app directory
WORKDIR /app

# Copy handler
COPY handler.py /app/handler.py

# Entrypoint for RunPod Serverless
CMD [ "python", "-u", "/app/handler.py" ]
