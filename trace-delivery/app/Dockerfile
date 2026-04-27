ARG PYTHON_VERSION=3.14-slim@sha256:5b3879b6f3cb77e712644d50262d05a7c146b7312d784a18eff7ff5462e77033
FROM python:${PYTHON_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./

# We'll pass the service name as an environment variable
ENV SERVICE_PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"] 