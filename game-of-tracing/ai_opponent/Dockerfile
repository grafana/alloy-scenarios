FROM python:3.13-slim@sha256:dc1546eefcbe8caaa1f004f16ab76b204b5e1dbd58ff81b899f21cd40541232f

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=ai_server.py
ENV FLASK_DEBUG=0
ENV IN_DOCKER=1

EXPOSE 8081

CMD ["flask", "run", "--host=0.0.0.0", "--port=8081"] 