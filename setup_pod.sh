#!/bin/bash
set -e

echo "=========================================="
echo "Splicer Proxy Pod Setup"
echo "=========================================="

# Update package list
echo "[1/6] Updating package list..."
apt-get update -qq

# Install system dependencies
echo "[2/6] Installing system dependencies..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    openssh-server \
    python3.12 \
    python3-pip \
    git \
    curl \
    vim \
    tmux \
    > /dev/null

# Configure SSH
echo "[3/6] Configuring SSH..."
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "$PUBLIC_KEY" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
service ssh start

# Clone repository
echo "[4/6] Cloning splicer repository..."
cd /workspace
if [ -d "splicer" ]; then
    echo "Repository already exists, pulling latest..."
    cd splicer
    git pull
else
    git clone https://github.com/samiriss7/splicer.git
    cd splicer
fi

# Install Python dependencies
echo "[5/6] Installing Python dependencies..."
pip3 install --break-system-packages -q \
    flask \
    boto3 \
    python-dotenv \
    requests \
    PyNvVideoCodec

# Verify GPU
echo "[6/6] Verifying GPU access..."
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo ""
echo "=========================================="
echo "✓ Setup complete!"
echo "=========================================="
echo ""
echo "Repository: /workspace/splicer"
echo "SSH: Running on port 22"
echo ""
echo "To start the Flask server:"
echo "  cd /workspace/splicer/handlers/proxy"
echo "  python3 pod_server.py"
echo ""
