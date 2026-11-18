#!/usr/bin/env python3
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(os.environ.get("LOG_PATH", "/logs/app.log"))
LEVELS = ["INFO"] * 40 + ["DEBUG"] * 40 + ["WARN"] * 10 + ["ERROR"] * 10
MESSAGES = {
    "INFO": ["request accepted", "cart loaded", "payment authorized"],
    "DEBUG": ["cache hit", "inventory lookup", "price calculation"],
    "WARN": ["payment provider retry", "slow inventory lookup"],
    "ERROR": ["payment provider timeout", "order write failed"],
}


def main() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sequence = 0
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log_file:
        while True:
            for level in LEVELS:
                sequence += 1
                message = MESSAGES[level][sequence % len(MESSAGES[level])]
                record = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": level,
                    "service": "checkout",
                    "message": message,
                    "sequence": sequence,
                }
                log_file.write(json.dumps(record, separators=(",", ":")) + "\n")
            log_file.flush()
            time.sleep(0.5)


if __name__ == "__main__":
    main()
