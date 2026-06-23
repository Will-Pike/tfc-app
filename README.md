# TFC App

A project-specific fork of the [Schnurr App](https://github.com/Will-Pike/Schnurr-App)
(`master` branch — the production codebase). Flask app for logging field
observations from a Google Form / Sheet and generating PDF reports, tailored to
the TFC project.

Deployed as a **second pair of services on the same EC2 instance** as Schnurr,
served at **https://tfc.schnurr-app.com** via the existing AWS load balancer.
See [deploy/DEPLOY.md](deploy/DEPLOY.md).

## Architecture

- **Web** (`app.py`) — Flask UI + JSON API. Report generation is enqueued, not
  run inline.
- **Worker** (`worker.py`) — an RQ worker that pulls report jobs off Redis and
  runs `generate_pdf.py` (WeasyPrint) in the background.
- **Redis** — RQ job queue + progress metadata.

These three are exactly the Schnurr setup; the TFC copy is isolated from
Schnurr by running on its **own port and its own Redis DB/queue** (see below).

## Coexistence with Schnurr (important)

Both apps run on one box and share one Redis server, so TFC is isolated via
environment variables (defaults preserve the original single-app behavior):

| Var | Schnurr | TFC |
|-----|---------|-----|
| `PORT` | 5000 | **5001** |
| `REDIS_URL` | `redis://localhost:6379` (db 0) | **`redis://localhost:6379/1`** (db 1) |
| `RQ_QUEUE` | `default` | **`tfc`** |

`app.py` and `worker.py` read all three from the environment; the `tfc-web` /
`tfc-worker` systemd units in `deploy/` set them. Without these, the two apps
would share the `default` queue and steal each other's jobs.

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # needs system libs for WeasyPrint
redis-server &                              # or brew services start redis
cp <your> service-account.json .            # Google service-account key
# app_config.json holds projects + form/field IDs (gitignored)

REDIS_URL=redis://localhost:6379/1 RQ_QUEUE=tfc PORT=5001 python app.py &
REDIS_URL=redis://localhost:6379/1 RQ_QUEUE=tfc python worker.py &
# open http://localhost:5001
```

> WeasyPrint needs native libs (pango/cairo/gdk-pixbuf). On macOS:
> `brew install pango gdk-pixbuf libffi`. PDF generation won't work without them,
> but the web UI will still boot.

## Secrets / runtime files (gitignored)

- `service-account.json` — Google service-account key (Sheets/Drive).
- `client_secret.json` + `token.pickle` — Google OAuth (Drive photo upload).
- `app_config.json` — project, buildings, Google Form URL + prefill field IDs.

## TFC customization

This fork is scoped to a single project (TFC) with location-aware OBS IDs and
operator-entered pricing. Behavior:

- **No project dropdown** — the app is locked to the `project` in `app_config.json`.
- **Building + Floor** are chosen on the home page. The Floor list is contextual
  (Lavaca = 7 floors, North Congress = 4), driven by the `buildings` map.
- **OBS ID** is composed as `{id_prefix}-{building_code}{floor}-{seq}`, e.g.
  `TFC-L3-1`. `seq` is the next sequential number across the whole project
  (derived from the sheet); the location prefix is cosmetic/contextual.
- **Pricing** is no longer computed from a work-type index. The form has a
  blank-allowed **Price Estimate** field; `Issue:` is now a free-text
  description. Reports show "Not yet priced" when blank.
- **Edit / Price view** lists every OBS, badges those with no price as
  **"Needs price"** (highlighted), and has a "show only needs pricing" filter.

### Config checklist (once the new Google Form + response Sheet exist)

1. **`app_config.json`** — set `form_url` and the prefill field entry IDs
   (`obs_field_id`, `project_field_id`, `building_field_id`, `floor_field_id`,
   `room_field_id`, `user_field_id`). Get them from the form's *"Get pre-filled
   link"* feature. See `app_config.example.json`.
2. **`SPREADSHEET_ID`** — set in the `tfc-web`/`tfc-worker` service units to the
   TFC form's response Sheet (not Schnurr's).
3. **Sheet columns** — the response Sheet must have a **`Building`** column and a
   **`Price Estimate`** column (or override `BUILDING_COLUMN`/`PRICE_COLUMN` env
   to match your headers). `Issue:`, `Floor:`, `Room:`, etc. stay as-is.
4. The form's Building/Floor questions should accept the values the app sends
   (building names exactly as in `buildings`; floor as a number).

## Relationship to Schnurr

Same starting codebase (`master`), **independent at runtime**: own repo, own
config/state, own processes, own port and Redis namespace. Modify freely without
risk to the live Schnurr app.
