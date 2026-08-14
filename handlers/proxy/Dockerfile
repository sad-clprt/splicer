FROM runpod/base:0.6.2-cuda12.1.0

WORKDIR /app

# Install dependencies
RUN pip install runpod boto3 python-dotenv

# Copy handler
COPY handler.py /app/

# Verify ffmpeg has NVENC support
RUN ffmpeg -hide_banner -encoders 2>/dev/null | grep h264_nvenc || \
    (echo "ERROR: ffmpeg does not have h264_nvenc encoder support" && exit 1)

CMD ["python3", "-u", "/app/handler.py"]
