from flask import Flask, jsonify
import random, time

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource

resource = Resource.create({"service.name": "demo-app"})
provider = TracerProvider(resource=resource)
exporter = OTLPSpanExporter()
provider.add_span_processor(BatchSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

app = Flask(__name__)

@app.route("/")
def index():
    with tracer.start_as_current_span("index"):
        time.sleep(random.uniform(0.01, 0.05))
        return jsonify({"status": "ok"})

@app.route("/api/data")
def get_data():
    with tracer.start_as_current_span("get-data"):
        time.sleep(random.uniform(0.02, 0.1))
        if random.random() < 0.1:
            raise Exception("Random error")
        return jsonify({"data": [1, 2, 3]})

@app.route("/api/slow")
def slow():
    with tracer.start_as_current_span("slow-operation"):
        time.sleep(random.uniform(0.5, 2.0))
        return jsonify({"status": "done"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
