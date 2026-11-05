# T5: API image. Build from the repository root:  docker compose build
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/launcher PRAMAAN_DATA=/data
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY data/ data/
COPY launcher/ launcher/
RUN useradd --system --uid 10001 pramaan && mkdir -p /data && chown pramaan /data
USER pramaan
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4)"
CMD ["python", "-m", "uvicorn", "Pramaan.backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers"]
