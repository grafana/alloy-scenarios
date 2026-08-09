import datetime
import random
import time


METHODS = ["GET", "GET", "GET", "POST"]
PATHS = ["/api/cart", "/api/checkout", "/api/products"]
STATUSES = [200, 200, 200, 200, 404, 500]


with open("/logs/requests.log", "w"):
    pass

while True:
    method = random.choice(METHODS)
    path = random.choice(PATHS)
    status = random.choice(STATUSES)
    duration = min(random.lognormvariate(-2.3, 0.55), 2.0)
    if status >= 500:
        duration += 0.4

    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    line = (
        f"{timestamp} method={method} path={path} "
        f"status={status} duration={duration:.3f}s"
    )

    print(line, flush=True)
    with open("/logs/requests.log", "a") as log_file:
        log_file.write(f"{line}\n")

    time.sleep(0.5)
