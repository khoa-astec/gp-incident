---
name: incident
description: Root-cause a production incident or 運用対応 ticket. Use when the user gives a ticket key or symptom ("/incident GP-12345", "why is this photo not showing", "調査して") and wants the cause, the affected scope and a ticket comment. Read-only investigation across the ticket, database (read replica), object storage, CDN, application exception logs and APM/RUM; ends with a plain-language comment draft. Never writes to production without explicit approval.
---

# Incident root-cause

Goal: from a ticket to **cause + scope + fix**, backed by evidence, explained so non-engineers understand it.

## Rules
- **Read-only.** SELECT on a read replica, HEAD/GET on storage, log queries. Any production write (data repair, re-upload, config change) is a separate step that needs the user's explicit "go".
- **Never print secrets.** Credentials are loaded in-process from the environment or your secret store; delete any temp credential file before finishing.
- Every claim cites evidence: a query result, `file:line`, a log line, an HTTP status. If something can't be verified, say so.
- Customer names, user names and IDs stay in the ticket and your local notes. They never go into shared docs or commit messages.

## Configuration (environment variables, set locally — nothing is stored in this repo)
| Variable | Meaning |
|---|---|
| `INCIDENT_DB_EXEC` | Command prefix that runs `mysql -e "<SQL>"` against the **read replica** (e.g. a short-lived kubectl pod or bastion wrapper). |
| `INCIDENT_AWS_PROFILE` | AWS profile for read-only S3/ECS/CloudFront calls. |
| `INCIDENT_BUCKET` | Media bucket name. |
| `INCIDENT_CDN_BASE` | Public CDN base URL for media. |
| `INCIDENT_GCP_PROJECT` / `INCIDENT_GCP_SA_FILE` | (Optional) Cloud Logging project and a service-account key path for `scripts/gcp_logs.py`, if exceptions are shipped to GCP. |

## Workflow

### 1. Read the ticket
Pull the ticket and all comments. Extract: symptom in the user's words, exact IDs (record / case / company), first-seen time, platform (PC/SP/app), whether ops reproduced it. Write a one-line hypothesis per plausible cause.

### 2. Look at the data
- Fetch the affected row(s) from the read replica. Compare with a healthy sibling (same case, same day).
- Look for state that claims something exists (flags, paths, foreign keys) and verify each claim.
- Timestamp gaps are evidence: `updated - created` far above siblings means a slow or failed step.

### 3. Verify what the data points to
- **Object storage:** `aws s3api head-object` (size, content-type, last-modified) and `list-object-versions` on the exact key. If bucket versioning is on, *no versions and no delete markers* means **never written**, not deleted.
- **CDN:** `curl -s -o f -w "%{http_code} %{content_type} %{size_download}"` the public URL and check the first bytes (`ff d8` = JPEG, `3c 3f 78 6d` = XML error). A ~100-byte XML "download" is a storage error page saved as a file.
- **Image resizer / derived URLs:** rebuild the exact URL the client builds (read the front-end helper) and probe it the same way.

### 4. Find the failing step
- Read the code path that should have produced the missing thing. Look for: work done before success is known (flags set first), `try/catch` that only logs, ignored return values (`put()` returning false), calls through the public URL that can cross deploys.
- Application exceptions: check where the app actually ships them (it may not be your APM). `scripts/gcp_logs.py` reads Cloud Logging with only the Python stdlib + `openssl`.
- APM/RUM: search the time window for errors, aborted requests (status 0), stale-chunk errors. Correlate with deploy times (e.g. ECS task-definition `registeredAt`).

### 5. Size the impact
Query every record created in the same window with the same characteristics and verify each one the same way (step 3). Report "N records, M accounts, window HH:MM–HH:MM", and confirm records just before/after are healthy.

### 6. Write it up
Two outputs:
1. **Technical note** (local, for engineers): evidence table, root cause, code references, fix plan, repair plan.
2. **Ticket comment draft** for non-engineers, in the ticket's language:
   - 何が起きたか — what the user sees and why, with no jargon (say "the photo with the blackboard drawn in" instead of `board_flg`).
   - 影響範囲 — how many records/accounts, which time window, and "the original data is safe" when true.
   - 対応方針 — prevention (next release) and repair (hotfix), in plain words.

Show the draft; post only after the user approves. Then propose the code fix as a separate branch.

## Pitfalls
- Don't stop at "the file is missing": prove *why* (never written vs deleted vs wrong key).
- A thumbnail that still shows can be a client-side fallback to the original — check `onError` handlers before concluding the data is fine.
- Logs rotate: ECS service events keep ~100 entries, APM traces of killed requests may never be flushed. Say so instead of guessing.
