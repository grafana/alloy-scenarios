FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=ai_server.py
ENV FLASK_DEBUG=0
ENV IN_DOCKER=1

EXPOSE 8081

CMD ["flask", "run", "--host=0.0.0.0", "--port=8081"] 