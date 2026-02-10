ARG PYTHON_VERSION=3.14-slim@sha256:486b8092bfb12997e10d4920897213a06563449c951c5506c2a2cfaf591c599f
FROM python:${PYTHON_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./

# We'll pass the service name as an environment variable
ENV SERVICE_PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"] 