FROM python:3.14-slim@sha256:486b8092bfb12997e10d4920897213a06563449c951c5506c2a2cfaf591c599f

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=app.py
ENV FLASK_DEBUG=0
ENV IN_DOCKER=1

EXPOSE 8080

CMD ["flask", "run", "--host=0.0.0.0", "--port=8080"] 