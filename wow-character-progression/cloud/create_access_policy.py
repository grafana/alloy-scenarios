#!/usr/bin/env python3
"""Create a logs, metrics and traces write policy and token for Azeroth Chronicle, then write cloud/.env.

    GCOM_TOKEN=... python3 cloud/create_access_policy.py --stack wow

GCOM_TOKEN (or GRAFANA_CLOUD_TOKEN, as gcx uses) must be able to read the stack and write access policies and
tokens (for example a token whose policy has stacks:read,
accesspolicies:read, accesspolicies:write and accesspolicies:delete).
The new token is written to cloud/.env with mode 600 and never printed.
Uses the Grafana Cloud API documented at
https://grafana.com/docs/grafana-cloud/developer-resources/api-reference/cloud-api/
"""

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlencode
from datetime import datetime, timezone
from pathlib import Path


def call(api, path, token, body=None):
    request = urllib.request.Request(
        f"{api}{path}", method="POST" if body is not None else "GET",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "alloyroute-setup"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise SystemExit(f"create_access_policy: {exc.code} from {path.split('?')[0]}: {detail}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stack", default="wow", help="stack slug, the first label of <slug>.grafana-dev.net")
    parser.add_argument("--api", help="Cloud API base URL. Defaults to grafana-dev.com for grafana-dev.net "
                        "stacks, otherwise grafana.com")
    parser.add_argument("--domain", default="grafana-dev.net", help="stack domain (default grafana-dev.net)")
    parser.add_argument("--policy", default="alloyroute-telemetry-write", help="access policy name")
    parser.add_argument("--otlp-endpoint", help="OTLP base URL from the stack details, including /otlp")
    parser.add_argument("--env", default=str(Path(__file__).with_name(".env")), help="file to write")
    args = parser.parse_args()
    token = os.environ.get("GCOM_TOKEN") or os.environ.get("GRAFANA_CLOUD_TOKEN")
    if not token:
        raise SystemExit("create_access_policy: set GCOM_TOKEN (or GRAFANA_CLOUD_TOKEN) to a Grafana Cloud "
                         "access policy token.")
    api = args.api or ("https://grafana-dev.com/api" if args.domain == "grafana-dev.net" else "https://grafana.com/api")

    env = Path(args.env)
    if env.exists() or env.is_symlink():
        raise SystemExit(f"Configuration already exists at {env}. Choose a new --env path to rotate credentials.")
    stack = call(api, f"/instances/{args.stack}", token)
    region, loki_url, loki_user = stack.get("regionSlug"), stack.get("hlInstanceUrl"), stack.get("hlInstanceId")
    if not (stack.get("id") and region and loki_url and loki_user):
        raise SystemExit("create_access_policy: the stack response has no Loki instance details.")
    print(f"Stack {args.stack}: id {stack['id']}, region {region}, Loki {loki_url} user {loki_user}")

    scopes = ["logs:write", "metrics:write", "traces:write"]
    realms = [{"type": "stack", "identifier": str(stack["id"]), "labelPolicies": []}]
    lookup = urlencode({"region": region, "name": args.policy})
    matches = call(api, f"/v1/accesspolicies?{lookup}", token)["items"]
    if matches:
        policy = matches[0]
        targets = [(item["type"], str(item["identifier"])) for item in policy["realms"]]
        if targets != [("stack", str(stack["id"]))] or set(policy["scopes"]) != set(scopes):
            raise SystemExit("Existing policy has a different stack or scope. Choose another --policy name.")
    else:
        policy = call(api, f"/v1/accesspolicies?region={region}", token, {
            "name": args.policy, "displayName": "Azeroth Chronicle telemetry (write)",
            "scopes": scopes, "realms": realms,
        })
    print(f"Access policy {args.policy}: {policy['id']} (telemetry write on stack {args.stack})")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    host = "".join(c for c in socket.gethostname().split(".")[0].lower() if c.isalnum() or c == "-")[:40]
    created = call(api, f"/v1/tokens?region={region}", token, {
        "name": f"alloyroute-{host or 'alloy'}-{stamp}",
        "displayName": f"Azeroth Chronicle ({host or 'alloy'})",
        "accessPolicyId": policy["id"],
    })

    descriptor = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(f"GRAFANA_CLOUD_LOKI_URL={loki_url.rstrip('/')}/loki/api/v1/push\n")
        handle.write(f"GRAFANA_CLOUD_LOKI_USER={loki_user}\n")
        endpoint = args.otlp_endpoint or f"https://otlp-gateway-{region}.{args.domain}/otlp"
        handle.write(f"ALLOYROUTE_STACK_URL=https://{args.stack}.{args.domain}\n")
        handle.write(f"ALLOYROUTE_OTLP_ENDPOINT={endpoint}\nALLOYROUTE_OTLP_USER={stack['id']}\n")
        handle.write(f"ALLOYROUTE_OTLP_TOKEN={created['token']}\n")
        handle.write(f"ALLOYROUTE_LOKI_TOKEN={created['token']}\n")
    os.chmod(env, 0o600)
    print(f"Wrote {env} (mode 600). The token is stored there only.")


if __name__ == "__main__":
    sys.exit(main())
