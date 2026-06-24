from flask import Flask, render_template, jsonify, request, redirect, send_file
import json
import os
import urllib.parse
from generate_pdf import generate_report_for_project  # Import your clean PDF generator!
from rq import Queue
from rq.job import Job
import redis
import uuid
import platform

app = Flask(__name__)

CONFIG_FILE = 'app_config.json'
REPORT_JOB_TIMEOUT = int(os.environ.get('REPORT_JOB_TIMEOUT', '7200'))

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

app_config = load_config()

def get_project():
    """The single project this app is scoped to (TFC)."""
    project = app_config.get("project")
    if project:
        return project
    # Backward-compatible fallback to the old multi-project shape.
    legacy = app_config.get("projects", {})
    return next(iter(legacy), None)

def get_projects():
    """Kept as a dict so existing `project in get_projects()` checks still work,
    but this app is scoped to a single project."""
    project = get_project()
    return {project: {}} if project else {}

def get_buildings():
    return app_config.get("buildings", {})

def compose_obs_id(seq, building=None, floor=None):
    """Build the location-prefixed OBS ID, e.g. TFC-L3-1 (Lavaca, floor 3, #1).
    Falls back to the bare sequence number when building/floor aren't supplied."""
    prefix = app_config.get("id_prefix") or get_project() or ""
    buildings = get_buildings()
    if building and floor and building in buildings:
        code = buildings[building].get("code") or building[:1].upper()
        return f"{prefix}-{code}{floor}-{seq}"
    return str(seq)

def get_prefilled_form_url(obs_id, building=None, floor=None, room=None, user=None):
    google_form_url = app_config.get("form_url")
    if not google_form_url:
        return None

    params = {'usp': 'pp_url'}
    if app_config.get("obs_field_id"):
        params[app_config["obs_field_id"]] = str(obs_id)
    if app_config.get("project_field_id"):
        params[app_config["project_field_id"]] = get_project()
    if building and app_config.get("building_field_id"):
        params[app_config["building_field_id"]] = building
    if floor and app_config.get("floor_field_id"):
        params[app_config["floor_field_id"]] = str(floor)
    if room and app_config.get("room_field_id"):
        params[app_config["room_field_id"]] = room
    if user and app_config.get("user_field_id"):
        params[app_config["user_field_id"]] = user

    return f"{google_form_url}?{urllib.parse.urlencode(params)}"

@app.route('/')
def index():
    return render_template(
        'index.html',
        project=get_project(),
        buildings=get_buildings()
    )

@app.route('/get_projects')
def get_projects_route():
    return jsonify({"projects": list(get_projects().keys())})

@app.route('/get_last_row_data')
def get_last_row_data_route():
    try:
        from generate_pdf import get_last_row_data
        data = get_last_row_data()
        if data:
            return jsonify(data)
        else:
            return jsonify({"error": "No data found"}), 404
    except Exception as e:
        print(f"Error in get_last_row_data_route: {e}")
        return jsonify({"error": "Failed to load data"}), 500

def _next_obs_payload(project, building=None, floor=None):
    """Compute the next sequence number, the composed OBS ID, and a prefilled
    form URL for the given building/floor selection."""
    from generate_pdf import get_highest_obs_for_project
    seq = get_highest_obs_for_project(project) + 1
    obs_id = compose_obs_id(seq, building, floor)
    form_url = get_prefilled_form_url(obs_id, building=building, floor=floor)
    return {"seq": seq, "obs_id": obs_id, "form_url": form_url}

@app.route('/get_current_obs')
def get_current_obs_route():
    project = request.args.get('project') or get_project()
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    building = request.args.get('building')
    floor = request.args.get('floor')
    try:
        return jsonify(_next_obs_payload(project, building, floor))
    except Exception as e:
        print(f"Error in get_current_obs_route: {e}")
        return jsonify({"error": "Failed to load OBS data"}), 500

@app.route('/get_next_obs')
def get_next_obs_route():
    project = request.args.get('project') or get_project()
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    building = request.args.get('building')
    floor = request.args.get('floor')
    try:
        return jsonify(_next_obs_payload(project, building, floor))
    except Exception as e:
        print(f"Error in get_next_obs_route: {e}")
        return jsonify({"error": "Failed to load OBS data"}), 500

@app.route('/reset_obs', methods=['POST'])
def reset_obs():
    data = request.get_json()
    project = data.get('project')
    new_number = data.get('new_number')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    if not isinstance(new_number, int) or new_number < 1:
        return jsonify({"error": "Invalid new_number"}), 400
    # This route is now mostly obsolete but keeping for compatibility
    return jsonify({"success": True})

@app.route('/open_observation_form')
def open_observation_form():
    project = request.args.get('project') or get_project()
    if not project or project not in get_projects():
        return "Invalid or missing project", 400
    building = request.args.get('building')
    floor = request.args.get('floor')
    try:
        url = _next_obs_payload(project, building, floor)["form_url"]
        if not url:
            return "Form URL not found", 404
        return redirect(url)
    except Exception as e:
        print(f"Error in open_observation_form: {e}")
        return "Error loading form", 500

# Redis/queue are env-configurable so a second copy of this app (e.g. TFC) can
# run on the same box with its own DB/queue and never pick up the other app's
# jobs. Defaults match the original single-app behavior (db 0, "default" queue).
redis_conn = redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
task_queue = Queue(os.environ.get('RQ_QUEUE', 'default'), connection=redis_conn)

@app.route('/generate_report', methods=['POST'])
def generate_report():
    project = request.json.get('project')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    try:
        job_id = str(uuid.uuid4())  # Generate a unique job ID
        job = task_queue.enqueue_call(
            func='generate_pdf.generate_report_for_project',
            args=(project,),
            job_id=job_id,
            timeout=REPORT_JOB_TIMEOUT
        )
        return jsonify({"job_id": job_id}), 202
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
    # This route is now mostly obsolete but keeping for compatibility
    return jsonify({"success": True})

@app.route('/get_report_count')
def get_report_count():
    project = request.args.get('project')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    try:
        from generate_pdf import get_report_record_count
        count = get_report_record_count(project)
        return jsonify({"count": count})
    except Exception as e:
        print(f"Error getting report count: {e}")
        return jsonify({"error": "Failed to get report count"}), 500

@app.route('/report_status/<job_id>')
def report_status(job_id):
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        return jsonify({"status": "not_found"}), 404

    if job.is_finished:
        return jsonify({"status": "finished", "download_url": f"/download_report/{job_id}"})
    elif job.is_failed:
        return jsonify({"status": "failed"})
    else:
        return jsonify({"status": "in_progress"})

@app.route('/download_report/<job_id>')
def download_report(job_id):
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        pdf_path = job.result
        return send_file(pdf_path, as_attachment=True)
    except Exception:
        return "Report not found or not ready.", 404

@app.route('/generate_reports', methods=['POST'])
def generate_reports():
    """Generate both PDF and CSV reports for a project with date range"""
    data = request.json
    project = data.get('project')
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    if not start_date or not end_date:
        return jsonify({"error": "Start and end dates are required"}), 400
    
    try:
        job_id = str(uuid.uuid4())
        job = task_queue.enqueue_call(
            func='generate_pdf.generate_both_reports',
            args=(project, start_date, end_date),
            job_id=job_id,
            timeout=REPORT_JOB_TIMEOUT
        )
        return jsonify({"job_id": job_id}), 202
    except Exception as e:
        print(f"Error generating reports: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/reports_status/<job_id>')
def reports_status(job_id):
    """Check status of both PDF and CSV report generation"""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception:
        return jsonify({"status": "not_found"}), 404

    # Refresh job/meta to avoid stale progress in Redis
    try:
        job.refresh()
        meta = job.get_meta(refresh=True)
    except Exception:
        meta = job.meta or {}

    csv_path = meta.get('csv_path')
    csv_url = f"/download_csv_report/{job_id}" if csv_path else None

    if job.is_finished:
        result = job.result
        return jsonify({
            "status": "finished",
            "pdf_url": f"/download_pdf_report/{job_id}",
            "csv_url": f"/download_csv_report/{job_id}"
        })
    elif job.is_failed:
        error_message = str(job.exc_info) if job.exc_info else "Unknown error"
        return jsonify({"status": "failed", "error": error_message, "csv_url": csv_url})
    else:
        # Get progress information from job metadata
        total = meta.get('total', 0)
        processed = meta.get('processed', 0)
        status = meta.get('status', 'in_progress')
        progress = int((processed / total * 100)) if total > 0 else 0
        
        # If merging PDFs, show 99% to indicate almost done
        if status == 'merging_pdfs':
            progress = 99
        
        return jsonify({
            "status": "in_progress",
            "progress": progress,
            "processed": processed,
            "total": total,
            "phase": status,
            "csv_url": csv_url
        })

@app.route('/download_pdf_report/<job_id>')
def download_pdf_report(job_id):
    """Download PDF report"""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        result = job.result
        pdf_path = result['pdf_path']
        return send_file(pdf_path, as_attachment=True, download_name=os.path.basename(pdf_path))
    except Exception as e:
        print(f"Error downloading PDF: {e}")
        return "PDF report not found or not ready.", 404

@app.route('/download_csv_report/<job_id>')
def download_csv_report(job_id):
    """Download CSV report"""
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        if job.is_finished and job.result:
            csv_path = job.result['csv_path']
        else:
            csv_path = job.meta.get('csv_path')
        if not csv_path:
            return "CSV report not found or not ready.", 404
        return send_file(csv_path, as_attachment=True, download_name=os.path.basename(csv_path))
    except Exception as e:
        print(f"Error downloading CSV: {e}")
        return "CSV report not found or not ready.", 404

@app.route('/edit_obs')
def edit_obs():
    return render_template('edit_obs.html', project=get_project(), buildings=get_buildings())

@app.route('/get_obs_list')
def get_obs_list():
    project = request.args.get('project')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    
    try:
        from generate_pdf import get_obs_list_for_project
        obs_list = get_obs_list_for_project(project)
        return jsonify({"obs_list": obs_list})
    except Exception as e:
        print(f"Error getting OBS list: {e}")
        return jsonify({"error": "Failed to get OBS list"}), 500

@app.route('/get_unpriced_count')
def get_unpriced_count():
    project = request.args.get('project') or get_project()
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    try:
        from generate_pdf import get_obs_list_for_project
        obs_list = get_obs_list_for_project(project)
        count = sum(1 for o in obs_list if o.get("needs_price"))
        return jsonify({"count": count})
    except Exception as e:
        print(f"Error getting unpriced count: {e}")
        return jsonify({"error": "Failed to get unpriced count"}), 500

@app.route('/get_obs_details')
def get_obs_details():
    project = request.args.get('project')
    obs_id = request.args.get('obs_id')
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    if not obs_id:
        return jsonify({"error": "Missing OBS ID"}), 400
    
    try:
        from generate_pdf import get_obs_details
        details = get_obs_details(project, obs_id)
        if details:
            return jsonify(details)
        else:
            return jsonify({"error": "OBS not found"}), 404
    except Exception as e:
        print(f"Error getting OBS details: {e}")
        return jsonify({"error": "Failed to get OBS details"}), 500

@app.route('/update_obs', methods=['POST'])
def update_obs():
    data = request.json
    project = data.get('project')
    obs_id = data.get('obs_id')
    
    if not project or project not in get_projects():
        return jsonify({"error": "Invalid or missing project"}), 400
    if not obs_id:
        return jsonify({"error": "Missing OBS ID"}), 400
    
    try:
        from generate_pdf import update_obs_in_spreadsheet
        success = update_obs_in_spreadsheet(project, obs_id, data)
        if success:
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Failed to update OBS"}), 500
    except Exception as e:
        print(f"Error updating OBS: {e}")
        return jsonify({"error": "Failed to update OBS"}), 500

@app.route('/upload_photos', methods=['POST'])
def upload_photos():
    """Handle photo uploads to Google Drive"""
    try:
        files = request.files.getlist('photos')
        project = request.form.get('project')
        obs_id = request.form.get('obs_id')
        
        if not files:
            return jsonify({"error": "No files uploaded"}), 400
        if not project or not obs_id:
            return jsonify({"error": "Missing project or OBS ID"}), 400
        
        uploaded_urls = []
        
        # Upload each file to Google Drive
        for file in files:
            if file.filename == '':
                continue
                
            # Read file data
            file_data = file.read()
            
            # Upload to Google Drive
            from generate_pdf import upload_photo_to_drive
            url = upload_photo_to_drive(file_data, file.filename, project, obs_id)
            
            if url:
                uploaded_urls.append(url)
            else:
                print(f"Failed to upload {file.filename}")
        
        if uploaded_urls:
            # Add the new URLs to the spreadsheet
            from generate_pdf import add_photo_urls_to_obs
            success = add_photo_urls_to_obs(project, obs_id, uploaded_urls)
            
            if success:
                return jsonify({
                    "success": True,
                    "message": f"Successfully uploaded {len(uploaded_urls)} photo(s)",
                    "uploaded_urls": uploaded_urls
                })
            else:
                return jsonify({"error": "Photos uploaded but failed to update spreadsheet"}), 500
        else:
            return jsonify({"error": "Failed to upload any photos"}), 500
            
    except Exception as e:
        print(f"Error uploading photos: {e}")
        return jsonify({"error": "Failed to upload photos"}), 500

@app.route('/delete_photo', methods=['POST'])
def delete_photo():
    """Delete a photo from Google Drive and remove from spreadsheet"""
    try:
        data = request.json
        project = data.get('project')
        obs_id = data.get('obs_id')
        photo_url = data.get('photo_url')
        
        if not project or not obs_id or not photo_url:
            return jsonify({"error": "Missing required parameters"}), 400
        
        if project not in get_projects():
            return jsonify({"error": "Invalid project"}), 400
        
        # Remove photo URL from spreadsheet
        from generate_pdf import remove_photo_url_from_obs
        success = remove_photo_url_from_obs(project, obs_id, photo_url)
        
        if success:
            # Optionally delete from Google Drive (commented out for safety)
            # from generate_pdf import delete_photo_from_drive
            # delete_photo_from_drive(photo_url)
            
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Failed to remove photo from spreadsheet"}), 500
            
    except Exception as e:
        print(f"Error deleting photo: {e}")
        return jsonify({"error": "Failed to delete photo"}), 500

@app.route('/debug_obs/<project>/<obs_id>')
def debug_obs(project, obs_id):
    """Debug route to see raw spreadsheet data"""
    try:
        from generate_pdf import debug_spreadsheet_data
        data = debug_spreadsheet_data(project, obs_id)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)





