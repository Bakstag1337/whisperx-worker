# Base image with CUDA 11.8
FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    pyannote_token="" 

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    python3.10-distutils \
    git \
    ffmpeg \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set up Python alias
RUN ln -s /usr/bin/python3.10 /usr/bin/python

# Upgrade pip
RUN pip install --upgrade pip

# Install PyTorch (compatible with CUDA 11.8)
RUN pip install torch==2.0.1 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118

# Install WhisperX and RunPod
# Note: WhisperX often requires git installation for latest fixes
RUN pip install git+https://github.com/m-bain/whisperx.git
RUN pip install runpod

# Create app directory
WORKDIR /app

# Copy handler
COPY handler.py /app/handler.py

# Entrypoint for RunPod Serverless
CMD [ "python", "-u", "/app/handler.py" ]
