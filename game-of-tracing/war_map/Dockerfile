FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=app.py
ENV FLASK_DEBUG=0
ENV IN_DOCKER=1

EXPOSE 8080

CMD ["flask", "run", "--host=0.0.0.0", "--port=8080"] 