# CONSTRAINT: Docker Hub official image only
FROM python:3.11-slim

WORKDIR /app

# CONSTRAINT: pip only — no apt, no apt-get
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8000

# CONSTRAINT: Python urllib healthcheck — no curl
# Port 8000 — the port this container runs on (NOT 7860 which is the gateway)
HEALTHCHECK --interval=20s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

CMD ["python3", "server.py"]
