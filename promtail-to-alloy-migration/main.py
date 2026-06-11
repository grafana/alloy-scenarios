"""Structured-log generator for the promtail-to-alloy-migration scenario.

Writes one logfmt line per second to /var/log/demo/app.log. The rotation
through levels and services is deterministic (counter-based, not random)
so the two collection pipelines can be diffed line-for-line in Loki.
"""

import itertools
import os
import time
from datetime import datetime, timezone

LOG_DIR = "/var/log/demo"
LOG_FILE = os.path.join(LOG_DIR, "app.log")

LEVELS = ["INFO", "INFO", "DEBUG", "WARN", "ERROR"]
SERVICES = ["payments", "checkout", "inventory"]


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    levels = itertools.cycle(LEVELS)
    services = itertools.cycle(SERVICES)

    with open(LOG_FILE, "a", buffering=1) as f:
        for order_id in itertools.count(1000):
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            line = (
                f'{ts} level={next(levels)} service={next(services)} '
                f'msg="processed order {order_id} in {order_id % 90 + 10}ms"'
            )
            f.write(line + "\n")
            print(line, flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
