"""Continuously send representative legacy StatsD metrics over UDP."""

import socket
import time


STATSD_ADDRESS = ("alloy", 8125)
METRICS = (
    "legacy.checkout.requests:1|c",
    "legacy.checkout.queue_depth:42|g",
    "legacy.checkout.request_duration:125|ms",
)


def main() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        while True:
            for metric in METRICS:
                client.sendto(metric.encode("utf-8"), STATSD_ADDRESS)
            time.sleep(1)


if __name__ == "__main__":
    main()
