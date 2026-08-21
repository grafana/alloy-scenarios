import os
import time
import random
from datadog import initialize, statsd
from ddtrace import tracer

options = {
    'statsd_host': os.environ.get('DD_AGENT_HOST', 'datadog-agent'),
    'statsd_port': 8125
}
initialize(**options)

@tracer.wrap()
def do_work():
    time.sleep(random.uniform(0.1, 0.5))
    statsd.increment('example.work.count', 1, tags=["env:dev"])
    statsd.gauge('example.work.duration', random.uniform(10, 100), tags=["env:dev"])

if __name__ == "__main__":
    while True:
        do_work()
        time.sleep(1)
