ARG PYTHON_VERSION=3.11-slim@sha256:61e01f72680f86a5279ad510818ab7b2ee9f049822589d4e34e33e044360356c
FROM python:${PYTHON_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./

# We'll pass the service name as an environment variable
ENV SERVICE_PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"] 