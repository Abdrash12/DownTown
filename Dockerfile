FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies, Node.js runtime (required for EJS solving), and curl/wget
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies cleanly without the fake npm package!
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install wgcf (Automated Cloudflare WARP registration CLI)
RUN wget -q https://github.com/ViRb3/wgcf/releases/download/v2.2.22/wgcf_2.2.22_linux_amd64 -O /usr/local/bin/wgcf \
    && chmod +x /usr/local/bin/wgcf

# Install wireproxy (User-space WireGuard client that outputs to a SOCKS5 port)
RUN wget -q https://github.com/pufferffish/wireproxy/releases/download/v1.0.9/wireproxy_linux_amd64.tar.gz \
    && tar -xzf wireproxy_linux_amd64.tar.gz -C /usr/local/bin/ \
    && rm wireproxy_linux_amd64.tar.gz \
    && chmod +x /usr/local/bin/wireproxy

COPY . .

# Ensure the bootloader script is executable
RUN chmod +x start.sh

EXPOSE 5000

# Execute our automated WARP tunnel startup script
CMD ["./start.sh"]
