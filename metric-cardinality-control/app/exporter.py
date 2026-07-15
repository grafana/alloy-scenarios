"""Expose deterministic metrics that demonstrate cardinality controls."""

from http.server import BaseHTTPRequestHandler, HTTPServer


NOISY_SERIES_COUNT = 200
STARTUP_GAP_SCRAPES = 1


class MetricsHandler(BaseHTTPRequestHandler):
    scrape_number = 0

    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return

        scrape_number = type(self).scrape_number
        type(self).scrape_number += 1

        lines = [
            "# HELP cardinality_demo_noisy_series Stable noisy series dropped by the after pipeline.",
            "# TYPE cardinality_demo_noisy_series gauge",
        ]
        lines.extend(
            f'cardinality_demo_noisy_series{{series_id="series-{index:03d}"}} 1'
            for index in range(NOISY_SERIES_COUNT)
        )
        lines.extend(
            [
                "# HELP cardinality_demo_request_value A request metric with intentionally volatile labels.",
                "# TYPE cardinality_demo_request_value gauge",
            ]
        )

        # Leave one successful scrape without the request family after each
        # exporter start. If Alloy retained a raw request series across an
        # exporter restart, this scrape carries its stale marker before a new
        # normalized request series is introduced.
        if scrape_number >= STARTUP_GAP_SCRAPES:
            request_number = scrape_number - STARTUP_GAP_SCRAPES

            # Alternating the retained operation and route family prevents the
            # current sample and the previous scrape's stale marker from
            # collapsing after request_id/query are dropped and route is
            # normalized.
            if request_number % 2 == 0:
                operation = "checkout"
                route_family = "orders"
            else:
                operation = "search"
                route_family = "users"

            dynamic_id = 100_000 + request_number
            lines.append(
                "cardinality_demo_request_value{"
                f'operation="{operation}",'
                f'route="/{route_family}/{dynamic_id}",'
                f'request_id="req-{request_number:08d}",'
                f'query="term-{request_number:08d}"'
                "} 1"
            )

        body = ("\n".join(lines) + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), MetricsHandler).serve_forever()
