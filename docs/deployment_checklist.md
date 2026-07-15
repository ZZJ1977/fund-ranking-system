# Deployment Checklist

Last checked: 2026-07-15

This checklist records the latest local deployment and release-readiness checks for the project.

## Verified Locally

| Check | Result | Notes |
|---|---|---|
| Unit and integration tests | Passed | `.venv/bin/python -m pytest tests -q` returned `39 passed` |
| Local web startup | Passed | `bash scripts/start_web.sh` started the FastAPI service |
| Health endpoint | Passed | `curl http://127.0.0.1:8000/health` returned `{"status":"ok"}` |
| Local web shutdown | Passed | `bash scripts/stop_web.sh` stopped the background service |
| Clean virtualenv install | Passed | A temporary virtualenv installed the package and ran `39 passed` |
| Docker CLI | Available | Docker and Compose commands are installed locally |
| Docker daemon | Not available in this check | Docker Desktop/daemon was not running, so container health was not executed |

## Reproduce The Checks

```bash
bash scripts/stop_web.sh || true
.venv/bin/python -m pytest tests -q
bash scripts/start_web.sh
curl -fsS http://127.0.0.1:8000/health
bash scripts/stop_web.sh
```

Clean environment check:

```bash
tmpdir=$(mktemp -d /tmp/fund-ranking-clean-XXXXXX)
python3 -m venv "$tmpdir/.venv"
"$tmpdir/.venv/bin/python" -m pip install --upgrade pip --timeout 60 --retries 8
"$tmpdir/.venv/bin/python" -m pip install -e . pytest --timeout 60 --retries 8
"$tmpdir/.venv/bin/python" -m pytest tests -q
```

Docker check, when Docker Desktop or the daemon is running:

```bash
docker compose up --build -d
curl -fsS http://127.0.0.1:8000/health
docker compose ps
docker compose down
```

## Release Notes

- The default web server binds to `127.0.0.1`.
- Generated data under `data/` and `reports/` is ignored by Git.
- Curated demo artifacts are committed under `docs/sample_outputs/` for GitHub preview and reviewer download.
- Public deployment still requires authentication, rate limiting, logging, HTTPS, task queue hardening, and compliance review.
