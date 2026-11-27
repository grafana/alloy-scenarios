ARG PYTHON_VERSION=3.11-slim
FROM python:${PYTHON_VERSION}
RUN apt-get update && apt-get install -y --only-upgrade libzstd1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade setuptools==84.2.1 && pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-u", "tracker.py"]
