# TFC App

A project-specific fork of the [Schnurr App](https://github.com/Will-Pike/Schnurr-App).
Flask app for logging observations and generating PDF reports from a Google Form
/ Google Sheet, tailored to the TFC project.

Deployed as a second process on the same EC2 instance as Schnurr and served at
**https://tfc.schnurr-app.com**. See [deploy/DEPLOY.md](deploy/DEPLOY.md).

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp app_config.example.json app_config.json   # then edit with real values

# Provide a Google service-account key as ./service-account.json
# On Windows/macOS, point at your local wkhtmltopdf:
export WKHTMLTOPDF_PATH="/path/to/wkhtmltopdf"   # Windows: set in env

PORT=5001 .venv/bin/python app.py
# open http://localhost:5001
```

## Layout

| Path | Purpose |
|------|---------|
| `app.py` | Flask routes + observation-counter / config logic |
| `generate_pdf.py` | Pulls Sheet rows, renders `report.html`, builds the PDF |
| `templates/index.html` | Main UI |
| `templates/report.html` | Per-observation PDF template |
| `app_config.json` | Runtime config & per-project counters (gitignored) |
| `service-account.json` | Google API credentials (gitignored) |
| `deploy/` | systemd unit, nginx block, deploy runbook |

## Relationship to Schnurr

Same starting codebase, **fully independent at runtime** — its own repo, its own
config/state, its own process and port (`5001` vs Schnurr's `5000`). Modify
freely without risk to the live Schnurr app.
