FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=ai_server.py
ENV FLASK_DEBUG=0
ENV IN_DOCKER=1

EXPOSE 8081

CMD ["flask", "run", "--host=0.0.0.0", "--port=8081"] 