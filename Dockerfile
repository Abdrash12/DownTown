# 1. Use an official lightweight Python runtime
FROM python:3.14-slim

# 2. Install system dependencies (FFmpeg and Node.js for yt-dlp signature decryption)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# 3. Set the working directory inside the container
WORKDIR /app

# 4. Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the application code
COPY . .

# NEW: Make the startup script executable
RUN chmod +x start.sh

# 6. Expose the port Flask runs on
EXPOSE 5000

# 7. Run the startup script instead of launching Gunicorn directly
CMD ["./start.sh"]
