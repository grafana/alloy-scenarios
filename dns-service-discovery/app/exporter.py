"""Minimal Prometheus exporter used by the DNS discovery scenario."""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer


INSTANCE = os.environ["INSTANCE"]


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API requires this name.
        if self.path != "/metrics":
            self.send_error(404)
            return

        body = f'dns_discovery_demo_info{{instance="{INSTANCE}"}} 1\n'.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


HTTPServer(("0.0.0.0", 8000), MetricsHandler).serve_forever()
