"""Log generator for the fluent-bit-to-alloy-migration scenario.

Writes two files that both collectors tail:

  /var/log/demo/app.log      logfmt lines. Every fifth entry is an ERROR
                             that drags an indented stack trace behind it,
                             so the multiline pipelines have something to
                             join.
  /var/log/demo/orders.json  one compact JSON object per line.

Everything is counter-driven rather than random, so the two collection
pipelines can be diffed line-for-line in Loki.
"""

import itertools
import json
import os
import time
from datetime import datetime, timezone

LOG_DIR = "/var/log/demo"
TEXT_FILE = os.path.join(LOG_DIR, "app.log")
JSON_FILE = os.path.join(LOG_DIR, "orders.json")

LEVELS = ["INFO", "INFO", "DEBUG", "WARN", "ERROR"]
SERVICES = ["payments", "checkout", "inventory"]

# Continuation lines for the ERROR entries. Nothing here contains
# "level=", so the unanchored extraction regex on both sides can only
# ever match the header line.
STACK = (
    "    at com.example.OrderService.charge(OrderService.java:87)\n"
    "    at com.example.OrderService.submit(OrderService.java:41)\n"
    "    at com.example.Api.post(Api.java:23)"
)


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    levels = itertools.cycle(LEVELS)
    services = itertools.cycle(SERVICES)

    with open(TEXT_FILE, "a", buffering=1) as text, \
            open(JSON_FILE, "a", buffering=1) as jsonl:
        for order_id in itertools.count(1000):
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            level = next(levels)
            service = next(services)
            msg = f"processed order {order_id} in {order_id % 90 + 10}ms"

            line = f'{ts} level={level} service={service} msg="{msg}"'
            if level == "ERROR":
                line = f"{line}\n{STACK}"
            text.write(line + "\n")

            # trace_id is a hex string, not a number, so both pipelines
            # coerce it the same way on the way into structured metadata.
            jsonl.write(json.dumps(
                {
                    "ts": ts,
                    "level": level,
                    "service": service,
                    "trace_id": f"{order_id:016x}",
                    "msg": msg,
                },
                separators=(",", ":"),
            ) + "\n")

            time.sleep(1)


if __name__ == "__main__":
    main()
