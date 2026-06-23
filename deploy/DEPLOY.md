# Deploying the TFC app alongside Schnurr

The TFC app runs as a **second web + worker pair on the same EC2 instance** as
Schnurr (Amazon Linux 2023, user `ec2-user`, code under `/home/ec2-user`). It
listens on port **5001** and is exposed at `tfc.schnurr-app.com` through the
**existing AWS load balancer** that already fronts Schnurr — there is no nginx
on this box.

> **Confirm before starting:** in the AWS console, verify Schnurr is behind an
> Application Load Balancer (EC2 → Load Balancers) and note whether its ACM
> certificate is a wildcard (`*.schnurr-app.com`) or just `schnurr-app.com`.
> That determines step 5.

## 1. Code + dependencies (on the instance)

```bash
cd /home/ec2-user
git clone https://github.com/Will-Pike/tfc-app.git
cd tfc-app
# Schnurr installs deps to the user site (see its PYTHONPATH); match that:
python3 -m pip install --user -r requirements.txt
```

WeasyPrint needs native libraries; they're almost certainly already present
because Schnurr uses them, but if PDF generation fails:
`sudo dnf install -y pango gdk-pixbuf2 libffi cairo`.

## 2. Secrets + config (not in git — copy from Schnurr or supply fresh)

```bash
cd /home/ec2-user/tfc-app
cp /home/ec2-user/schnurr-app/service-account.json .   # if same Google project
cp /home/ec2-user/schnurr-app/client_secret.json .     # OAuth (Drive uploads)
cp /home/ec2-user/schnurr-app/token.pickle .           # existing OAuth token
# app_config.json: projects, Google Form URL, field IDs, obs counters.
# Start from Schnurr's and trim to the TFC project, or write a fresh one:
cp /home/ec2-user/schnurr-app/app_config.json .
$EDITOR app_config.json
```

## 3. Install the two systemd services

```bash
sudo cp deploy/tfc-web.service    /etc/systemd/system/tfc-web.service
sudo cp deploy/tfc-worker.service /etc/systemd/system/tfc-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now tfc-web tfc-worker
systemctl status tfc-web tfc-worker --no-pager
```

The units set `PORT=5001`, `REDIS_URL=redis://localhost:6379/1`, `RQ_QUEUE=tfc`
so TFC is fully isolated from Schnurr (which uses port 5000, Redis db 0, queue
`default`). Redis is already running and shared.

Sanity check locally on the box:

```bash
curl -s localhost:5001/get_projects
```

## 4. Open port 5001 from the load balancer to the instance

In the **instance's security group**, add an inbound rule:
`TCP 5001` from the **load balancer's security group** (same source already used
for the 5000 rule).

## 5. Load balancer: route tfc.schnurr-app.com → port 5001

In the AWS console:

1. **Target group** — create `tfc-tg` (target type *Instance*, protocol HTTP,
   **port 5001**), register this instance, health-check path `/get_projects`
   (returns 200) or `/`.
2. **Certificate** — the HTTPS listener must serve a cert valid for
   `tfc.schnurr-app.com`:
   - If the existing cert is `*.schnurr-app.com` → already covered, skip.
   - Otherwise request an ACM cert for `tfc.schnurr-app.com` and **add it to the
     443 listener** (ALB serves multiple certs via SNI).
3. **Listener rule** — on the **443 listener**, add a rule:
   *IF Host header = `tfc.schnurr-app.com` → forward to `tfc-tg`*.
   (Mirror Schnurr's host rule; copy its priority pattern.)

## 6. DNS

Point `tfc.schnurr-app.com` at the load balancer (same target as
`schnurr-app.com`):
- Route 53: an **A / Alias** record to the ALB.
- Other DNS host: a **CNAME** to the ALB's DNS name.

Then browse to https://tfc.schnurr-app.com.

## 7. (Optional) Link from the main Schnurr site

Add a button in Schnurr's `templates/index.html`:

```html
<a href="https://tfc.schnurr-app.com" class="btn btn-primary" target="_blank">TFC Project</a>
```

## Updating later

```bash
cd /home/ec2-user/tfc-app && git pull
python3 -m pip install --user -r requirements.txt   # if deps changed
sudo systemctl restart tfc-web tfc-worker
```

## Notes

- **Isolation recap:** TFC = port 5001, Redis db 1, queue `tfc`. Schnurr =
  port 5000, Redis db 0, queue `default`. The worker and web of each app must
  share the same `REDIS_URL`/`RQ_QUEUE`, which the units handle.
- The production app renders PDFs with **WeasyPrint**, not wkhtmltopdf — ignore
  the stale `WKHTMLTOPDF_PATH` override on Schnurr's service.
- Don't commit `service-account.json`, `client_secret.json`, `token.pickle`, or
  `app_config.json` — all are gitignored.
