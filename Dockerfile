FROM python:3.11-slim

# Install Node.js (Required by yt-dlp to solve the 'n' parameter speed cipher)
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose Flask's default port
EXPOSE 5000

# Run the production server with an extended timeout for long video streams# Run Gunicorn with the eventlet async worker for high-speed WebSocket signaling
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "app:app", "--timeout", "120"]
