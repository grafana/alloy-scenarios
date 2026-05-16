ARG PYTHON_VERSION=3.13-slim@sha256:dc1546eefcbe8caaa1f004f16ab76b204b5e1dbd58ff81b899f21cd40541232f
FROM python:${PYTHON_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./

# We'll pass the service name as an environment variable
ENV SERVICE_PORT=8080
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"] 