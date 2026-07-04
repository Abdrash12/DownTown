# Use the lightweight Python slim image to keep build sizes tiny
FROM python:3.11-slim

# Prevents Python from writing pyc files to disc and keeps stdout unbuffered for clean logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Copy requirements first to leverage Docker layer caching (fast rebuilds!)
COPY requirements.txt .

# Install dependencies cleanly without storing build cache
RUN pip install --no-cache-dir -r requirements.txt

# Copy your app.py and your templates/ folder into the container
COPY . .

# Expose port 5000 for web traffic
EXPOSE 5000

# Launch Gunicorn with lightweight sync workers (since we are only serving web pages!)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app", "--workers", "2", "--threads", "4", "--access-logfile", "-"]
