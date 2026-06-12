import socket
import time
import os
import random
import json
from datetime import datetime

# Get the target host and port from environment variables
target_host = os.getenv('TARGET_HOST', 'localhost')
target_port = int(os.getenv('TARGET_PORT', 5140))

# Define the endpoint path
endpoint_path = "/loki/api/v1/raw"


def connect_with_retry():
    """Open a TCP connection to Alloy, retrying until it is ready.

    `depends_on` in docker-compose only waits for the Alloy container to
    start, not for its loki.source.api listener to bind port 9999. Without
    a retry the simulator races Alloy on boot, hits "Connection refused",
    and exits — so retry with backoff until the listener is up.
    """
    delay = 1
    while True:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect((target_host, target_port))
            print(f"Connected to {target_host}:{target_port}")
            return sock
        except socket.error as e:
            sock.close()
            print(f"Waiting for {target_host}:{target_port} - {e}; retrying in {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 10)  # exponential backoff, capped at 10s


# Create a TCP socket, waiting for Alloy to become available
sock = connect_with_retry()

# Define log levels and messages
log_levels = ["INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL"]
messages = [
    "System started successfully",
    "User login successful",
    "Configuration loaded",
    "Connection to database failed",
    "Data processed successfully",
    "Invalid API request received",
    "Memory usage high",
    "Disk space low",
    "Unknown error occurred",
    "Service restarted",
]

# Define extra fields for the log payload
service_names = ["AuthService", "DataService", "PaymentService", "NotificationService"]
regions = ["us-east-1", "eu-west-1", "ap-south-1", "sa-east-1"]
server_ids = ["srv-101", "srv-202", "srv-303", "srv-404"]

# Generate and send JSON log messages every few seconds
while True:
    try:
        # Correct timestamp format
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        log_level = random.choice(log_levels)
        message_text = random.choice(messages)
        service_name = random.choice(service_names)
        region = random.choice(regions)
        server_id = random.choice(server_ids)
        code_line = random.randint(20, 120)  # Simulate random code line numbers

        # Create the JSON log payload
        log_payload = {
            "timestamp": timestamp,
            "severity": log_level,
            "body": message_text,
            "service_name": service_name,
            "code_line": code_line,
            "region": region,
            "server_id": server_id
        }

        # Convert the log payload to JSON string
        log_json = json.dumps(log_payload)

        # Create the HTTP POST request to send the log
        http_request = (
            f"POST {endpoint_path} HTTP/1.1\r\n"
            f"Host: {target_host}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(log_json)}\r\n"
            "Connection: keep-alive\r\n"
            "\r\n"
            f"{log_json}"
        )

        # Send the HTTP request over TCP
        sock.sendall(http_request.encode())
        print(f"Sent JSON log message to {target_host}:{target_port} - {log_json}")
    except socket.error as e:
        # The connection dropped (e.g. Alloy restarted or reloaded its
        # config). Reconnect and keep going rather than exiting.
        print(f"Failed to send log message - {e}; reconnecting")
        sock.close()
        sock = connect_with_retry()
        continue

    # Wait for a few seconds before sending the next message
    time.sleep(random.randint(3, 8))  # Send a message every 3-8 seconds
