FROM python:3.11-slim

# Install system deps: ffmpeg for PCM decode, libopus for Discord voice encoding,
# libsodium for PyNaCl voice encryption
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libsodium23 \
    && rm -rf /var/lib/apt/lists/*

# Increase UDP socket buffer sizes to prevent SOCKET_RCVBUFF drops
# (Discord voice sends ~50 UDP packets/sec, default buffers are too small)
RUN echo "net.core.rmem_max=26214400" >> /etc/sysctl.conf \
    && echo "net.core.rmem_default=26214400" >> /etc/sysctl.conf \
    && echo "net.core.wmem_max=26214400" >> /etc/sysctl.conf \
    && echo "net.core.wmem_default=26214400" >> /etc/sysctl.conf

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
