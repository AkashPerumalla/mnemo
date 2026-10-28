# Deployable as-is to Nebius Serverless Endpoints, Render, or any container host.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY web/ ./web/
COPY skills/ ./skills/

# Memories live on a volume so they survive redeploys, where the host supports
# one. Hosts with an ephemeral filesystem should run in demo mode instead.
ENV MNEMO_DATA_DIR=/data \
    PORT=8000
VOLUME /data

# Bind whatever port the host asks for. Render does not inject PORT for the
# Docker runtime and auto-detects the listening port, so serving a fixed port
# while the platform probes another is a real way to fail a deploy.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
