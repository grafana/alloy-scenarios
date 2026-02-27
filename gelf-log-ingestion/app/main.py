import logging
import time
import random
from pygelf import GelfUdpHandler

logger = logging.getLogger("gelf-demo")
logger.setLevel(logging.DEBUG)
handler = GelfUdpHandler(host="alloy", port=12201, compress=False)
logger.addHandler(handler)

messages = [
    (logging.INFO, "User authentication successful", {"user_id": "42", "method": "oauth2"}),
    (logging.WARNING, "Slow database query detected", {"query_time_ms": "2500", "table": "orders"}),
    (logging.ERROR, "Failed to connect to payment gateway", {"gateway": "stripe", "retry_count": "3"}),
    (logging.INFO, "Order processed successfully", {"order_id": "ORD-12345", "total": "99.99"}),
    (logging.DEBUG, "Cache lookup completed", {"cache_hit": "true", "key": "user:42:profile"}),
    (logging.CRITICAL, "Disk space critically low", {"mount": "/data", "available_pct": "2"}),
    (logging.INFO, "Health check passed", {"service": "api", "response_ms": "12"}),
    (logging.WARNING, "Rate limit approaching threshold", {"client_ip": "10.0.1.50", "requests": "980"}),
]

print("Starting GELF log generator...")
while True:
    level, msg, extra = random.choice(messages)
    logger.log(level, msg, extra=extra)
    time.sleep(random.uniform(1, 3))
