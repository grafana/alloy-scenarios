ARG PYTHON_VERSION=3.11-slim
FROM python:${PYTHON_VERSION}
# The exporter uses only the standard library and needs no packaging tools.
RUN apt-get update && apt-get install -y --only-upgrade libzstd1 && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y setuptools wheel pip \
    && rm -rf /usr/local/lib/python*/ensurepip
WORKDIR /companion
COPY read_recording.py export_signals.py ./
CMD ["python", "-B", "export_signals.py"]
