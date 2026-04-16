# CONSTRAINT: Docker Hub official image only
FROM python:3.11-slim

WORKDIR /app

# CONSTRAINT: pip only — no apt, no apt-get
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

CMD ["python3", "main.py"]
