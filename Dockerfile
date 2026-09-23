FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose HTTP dashboard port
EXPOSE 8000

ENV HOST=0.0.0.0
ENV PORT=8000
ENV ROBOTS=3

# Start fleet orchestrator
CMD ["python", "-m", "live.orchestrator"]
