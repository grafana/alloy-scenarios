ARG PYTHON_VERSION=3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
FROM python:${PYTHON_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./

# We'll pass the service name as an environment variable
ENV SERVICE_PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"] 