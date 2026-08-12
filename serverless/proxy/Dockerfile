FROM runpod/base:0.6.2-cuda12.1.0

# System deps: ffmpeg with nvdec/nvenc already in base, add python deps
WORKDIR /app

# Copy app code (FastAPI app + proxy, s3, models, database) for Neon mirror + transcode fallback
COPY pyproject.toml uv.lock ./
COPY app app
COPY alembic alembic
COPY alembic.ini ./
COPY serverless/proxy/handler.py ./handler.py

# Install Python deps via uv (or pip)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir runpod boto3 python-dotenv sqlalchemy psycopg[binary] logfire fastapi pydantic requests

# Also install ffmpeg extras if missing (base already has ffmpeg n9.0, ffprobe, nvenc)
RUN ffmpeg -version | head -n1 && ffprobe -version | head -n1

# Pre-create volume mount point (RunPod mounts at /runpod-volume)
RUN mkdir -p /runpod-volume

# Handler entrypoint for RunPod Serverless
CMD ["python", "-u", "handler.py"]
