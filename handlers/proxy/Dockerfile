# Optimized Dockerfile using NVIDIA CUDA runtime base (lighter than runpod/base)
# CUDA 12.8 + Ubuntu 24.04 + Python 3.12 (RunPod RTX 4090 has High stock on CUDA 12.8)
FROM nvidia/cuda:12.8.0-runtime-ubuntu24.04

# Install system dependencies (python3.12 ships with ubuntu24.04)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specification
COPY requirements.txt .

# Install Python packages
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# Set NVIDIA driver capabilities for PyNvVideoCodec
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video

# Copy handler code
COPY handler.py .

# RunPod serverless entrypoint
CMD ["python3", "-u", "/app/handler.py"]
