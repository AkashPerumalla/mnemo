# Deployable as-is to Nebius Serverless Endpoints, or any container host.
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY web/ ./web/
COPY skills/ ./skills/

# Memories live on a volume so they survive redeploys.
ENV MNEMO_DATA_DIR=/data
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
