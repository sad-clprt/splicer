# Deprecated: RunPod handler removed. Replaced by Modal endpoint.
# See modal_app/ or lib/tools/proxy.py for Modal implementation.
# This file is kept as placeholder and will be removed.
FROM nvidia/cuda:12.5.1-runtime-ubuntu24.04
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,video
COPY handler.py .
CMD ["python3", "-u", "/app/handler.py"]
