# Deploying the TFC app alongside Schnurr on the existing EC2 instance

The TFC app runs as a **second process on the same t3a.small box** as the
Schnurr app — no new EC2 instance. It listens on `127.0.0.1:5001` (Schnurr uses
`:5000`) and is reverse-proxied by nginx at `tfc.schnurr-app.com`.

## 1. DNS

Add an **A record** for `tfc` pointing at the instance's Elastic IP (the same
IP `schnurr-app.com` already resolves to). Wait for it to propagate:

```bash
dig +short tfc.schnurr-app.com   # should print the Elastic IP
```

## 2. System packages (one-time)

`wkhtmltopdf` is required for PDF generation:

```bash
sudo apt-get update
sudo apt-get install -y wkhtmltopdf python3-venv
which wkhtmltopdf   # should be /usr/bin/wkhtmltopdf (the app's default)
```

## 3. Get the code & install deps

```bash
sudo git clone https://github.com/Will-Pike/tfc-app.git /opt/tfc-app   # or your new repo URL
cd /opt/tfc-app
sudo chown -R ubuntu:ubuntu /opt/tfc-app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 4. Secrets & runtime state (not in git)

- `service-account.json` — Google service-account key for Sheets/Drive access.
  Copy it into `/opt/tfc-app/`. (Easiest: reuse the same one as the Schnurr app
  if it points at the right Drive/Sheets, or mint a new one for TFC.)
- `app_config.json` — created from the template, then edited with the real
  Google Form URL, field IDs, and the TFC project name:

  ```bash
  cp app_config.example.json app_config.json
  $EDITOR app_config.json   # set form_url, obs_field_id, project_field_id, projects
  ```

  Also point `SPREADSHEET_ID` at the TFC sheet if it differs — override via the
  systemd unit (`Environment=SPREADSHEET_ID=...`) rather than editing code.

## 5. Install the service

```bash
sudo cp deploy/tfc-app.service /etc/systemd/system/tfc-app.service
# confirm the User= and paths match your box, then:
sudo systemctl daemon-reload
sudo systemctl enable --now tfc-app
systemctl status tfc-app          # should be active (running)
curl -s localhost:5001/get_projects   # sanity check the app responds
```

## 6. nginx + TLS

```bash
sudo cp deploy/nginx-tfc.conf /etc/nginx/sites-available/tfc.schnurr-app.com
sudo ln -s /etc/nginx/sites-available/tfc.schnurr-app.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Issue/extend the cert for the new subdomain:
sudo certbot --nginx -d tfc.schnurr-app.com
```

Visit https://tfc.schnurr-app.com — done.

## 7. (Optional) Link from the main site

Add a button to the Schnurr app's `templates/index.html`:

```html
<a href="https://tfc.schnurr-app.com" class="btn btn-primary" target="_blank">TFC Project</a>
```

## Updating later

```bash
cd /opt/tfc-app
git pull
.venv/bin/pip install -r requirements.txt   # if deps changed
sudo systemctl restart tfc-app
```

## Notes / gotchas

- The two apps are fully isolated: separate code, separate `app_config.json`,
  separate process. Changing TFC cannot break Schnurr.
- `wkhtmltopdf` path is read from `WKHTMLTOPDF_PATH` (default `/usr/bin/wkhtmltopdf`).
- `index.html` references `/open_foreman_form`, which has no matching route in
  `app.py` in this snapshot — wire it up or remove the button as needed for TFC.
