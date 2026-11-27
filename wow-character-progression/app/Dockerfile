ARG PYTHON_VERSION=3.11-slim
FROM python:${PYTHON_VERSION}
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-u", "tracker.py"]
