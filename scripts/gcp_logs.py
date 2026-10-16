#!/usr/bin/env python3
"""Read Google Cloud Logging entries with only the Python stdlib + openssl (no gcloud, no pip packages).

Usage:
  python gcp_logs.py --project <id> --sa-file <key.json> \
      --filter 'severity>=ERROR AND jsonPayload.message:"Repository::store"' \
      --from 2026-10-13T06:13:00Z --to 2026-10-13T06:20:00Z [--limit 200] [--fields message,error_message]

The service-account key only needs the logging.read scope. Its private key is written to a temp file
(0600) for openssl and deleted right after signing. Nothing is printed except log entries.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request


def b64url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def access_token(sa: dict) -> str:
    now = int(time.time())
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = b64url(json.dumps({
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/logging.read",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 600,
    }).encode())
    fd, key_path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(sa["private_key"])
        os.chmod(key_path, 0o600)
        sig = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=header + b"." + claims, capture_output=True, check=True,
        ).stdout
    finally:
        os.remove(key_path)
    assertion = (header + b"." + claims + b"." + b64url(sig)).decode()
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body) as r:
        return json.load(r)["access_token"]


def list_entries(token: str, project: str, flt: str, limit: int):
    out, page = [], None
    while len(out) < limit:
        body = {
            "resourceNames": [f"projects/{project}"],
            "filter": flt,
            "orderBy": "timestamp asc",
            "pageSize": min(1000, limit - len(out)),
        }
        if page:
            body["pageToken"] = page
        req = urllib.request.Request(
            "https://logging.googleapis.com/v2/entries:list",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            res = json.load(r)
        out += res.get("entries", [])
        page = res.get("nextPageToken")
        if not page:
            break
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", default=os.environ.get("INCIDENT_GCP_PROJECT"))
    p.add_argument("--sa-file", default=os.environ.get("INCIDENT_GCP_SA_FILE"))
    p.add_argument("--filter", default="severity>=ERROR")
    p.add_argument("--from", dest="since", required=True, help="RFC3339, e.g. 2026-10-13T06:13:00Z")
    p.add_argument("--to", dest="until", required=True)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--fields", default="message,error_message",
                   help="jsonPayload fields to print (comma separated)")
    a = p.parse_args()
    if not a.project or not a.sa_file:
        sys.exit("--project and --sa-file (or INCIDENT_GCP_PROJECT / INCIDENT_GCP_SA_FILE) are required")

    with open(a.sa_file, encoding="utf-8") as f:
        sa = json.load(f)
    flt = f'timestamp>="{a.since}" AND timestamp<="{a.until}" AND ({a.filter})'
    entries = list_entries(access_token(sa), a.project, flt, a.limit)
    fields = [x.strip() for x in a.fields.split(",") if x.strip()]
    for e in entries:
        jp = e.get("jsonPayload", {})
        row = {"timestamp": e.get("timestamp"), "severity": e.get("severity")}
        for k in fields:
            if k in jp:
                row[k] = jp[k]
        if not jp and "textPayload" in e:
            row["text"] = e["textPayload"]
        print(json.dumps(row, ensure_ascii=False))
    print(f"# {len(entries)} entries", file=sys.stderr)


if __name__ == "__main__":
    main()
