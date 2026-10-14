FROM python:${PYTHON_VERSION:-3.11-slim}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# v5 — SQLite Memory writes to /data/from.db by default. Ensure the dir exists
# and is world-writeable so the container user can write even when no volume
# is mounted (local-dev / sandbox runs).
RUN mkdir -p /data && chmod 777 /data

ENV FLASK_APP=app.py
ENV FLASK_DEBUG=0
ENV IN_DOCKER=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "app.py"]
