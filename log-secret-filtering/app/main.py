import time
import random
import datetime

secrets = [
    'Found config: AKIAIOSFODNN7EXAMPLE with secret',
    'Database connection: postgresql://admin:SuperSecret123@db:5432/prod',
    'Setting API_KEY=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef12',
    'Bearer token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U',
    'Slack webhook: https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX',
]

normal = [
    'Processing request from 192.168.1.100',
    'User login successful for user_id=42',
    'Health check passed: all systems operational',
    'Cache hit ratio: 94.2%',
    'Request completed in 23ms',
]

with open("/logs/app.log", "w") as f:
    pass

while True:
    line = random.choice(secrets + normal + normal)  # 2:1 ratio normal:secret
    ts = datetime.datetime.now().isoformat()
    with open("/logs/app.log", "a") as f:
        f.write(f"{ts} {line}\n")
    time.sleep(2)
