from flask import Flask, render_template, jsonify, request, redirect, send_file
import json
import os
import urllib.parse
from generate_pdf import generate_report_for_project  # Import your clean PDF generator!

app = Flask(__name__)

CONFIG_FILE = 'app_config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"projects": {}, "current_obs": {}}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

app_config = load_config()

def get_projects():
    return app_config.get("projects", {})

def get_current_obs(project):
    return app_config.get("current_obs", {}).get(project, 0)

def set_current_obs(project, obs_number):
    if "current_obs" not in app_config:
        app_config["current_obs"] = {}
    app_config["current_obs"][project] = obs_number
    save_config(app_config)

def get_next_obs(project):
    current = get_current_obs(project)
    next_number = current + 1
    set_current_obs(project, next_number)
    return next_number

def get_prefilled_form_url(project, obs_number):
    projects = get_projects()
    if project not in projects:
        return None
    google_form_url = app_config.get("form_url")
    obs_field_id = app_config.get("obs_field_id")
    project_field_id = app_config.get("project_field_id")
    params = {
        'usp': 'pp_url',
        obs_field_id: str(obs_number),
        project_field_id: project
    }
    return f"{google_form_url}?{urllib.parse.urlencode(params)}"

@app.route('/')
def index():
    projects = get_projects()
    default_project = next(iter(projects)) if projects else ""
    return render_template('index.html', projects=projects, default_project=default_project)

@app.route('/get_projects')
def get_projects_route():
    return jsonify({"projects": list(get_projects().keys())})

@app.route('/get_current_obs')
def get_current_obs_route():
    project = request.args.get('project')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    current_obs = get_current_obs(project)
    form_url = get_prefilled_form_url(project, current_obs)
    return jsonify({"obs_number": current_obs, "form_url": form_url})

@app.route('/get_next_obs')
def get_next_obs_route():
    project = request.args.get('project')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    next_obs = get_next_obs(project)
    form_url = get_prefilled_form_url(project, next_obs)
    return jsonify({"obs_number": next_obs, "form_url": form_url})

@app.route('/reset_obs', methods=['POST'])
def reset_obs():
    data = request.get_json()
    project = data.get('project')
    new_number = data.get('new_number')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    if not isinstance(new_number, int) or new_number < 1:
        return jsonify({"error": "Invalid new_number"}), 400
    set_current_obs(project, new_number - 1)
    return jsonify({"success": True})

@app.route('/open_observation_form')
def open_observation_form():
    project = request.args.get('project')
    if not project or project not in get_projects():
        return "Invalid or missing project", 400
    current_obs = get_current_obs(project)
    url = get_prefilled_form_url(project, current_obs)
    if not url:
        return "Form URL not found", 404
    return redirect(url)

@app.route('/generate_report')
def generate_report():
    project = request.args.get('project')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    try:
        pdf_path = generate_report_for_project(project)
        return send_file(pdf_path, as_attachment=True)
    except Exception as e:
        print(f"Error generating report: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/obs_submitted', methods=['POST'])
def obs_submitted():
    data = request.get_json()
    project = data.get('project')
    obs_number = data.get('obs_number')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    current = get_current_obs(project)
    if obs_number == current:
        set_current_obs(project, current + 1)
    return jsonify({"success": True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)





