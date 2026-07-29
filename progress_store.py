import json
import os
import time
import uuid
import shutil
from werkzeug.utils import secure_filename

DATA_FILE = os.getenv('PROGRESS_DATA_FILE', 'progress_reports.json')
UPLOAD_ROOT = os.getenv('PROGRESS_UPLOAD_DIR', 'static/uploads/progress')

STATUS_VALUES = [
    'No issues',
    'Issues Found',
    'Repair Authorized',
    'Do Not Repair',
    'Completed'
]


def _ensure_paths():
    os.makedirs(os.path.dirname(DATA_FILE) or '.', exist_ok=True)
    os.makedirs(UPLOAD_ROOT, exist_ok=True)


def _load_all_reports():
    _ensure_paths()
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f) or []
    except (json.JSONDecodeError, ValueError):
        return []


def _save_all_reports(reports):
    _ensure_paths()
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(reports, f, indent=2)


def get_progress_entries(project):
    reports = _load_all_reports()
    return [r for r in reports if r.get('project') == project]


def get_progress_entry(project, entry_id):
    for report in _load_all_reports():
        if report.get('project') == project and report.get('id') == entry_id:
            return report
    return None


def get_progress_entry_by_location(project, building, floor, room):
    for report in _load_all_reports():
        if (
            report.get('project') == project and
            report.get('building') == building and
            report.get('floor') == floor and
            report.get('room') == room
        ):
            return report
    return None


def delete_progress_entry(project, entry_id):
    reports = _load_all_reports()
    remaining = []
    deleted = False
    for report in reports:
        if report.get('project') == project and report.get('id') == entry_id:
            deleted = True
            continue
        remaining.append(report)

    if not deleted:
        return False

    _save_all_reports(remaining)
    entry_dir = os.path.join(UPLOAD_ROOT, project, entry_id)
    if os.path.exists(entry_dir):
        shutil.rmtree(entry_dir, ignore_errors=True)
    return True


def save_progress_entry(entry):
    reports = _load_all_reports()
    existing = None
    for idx, report in enumerate(reports):
        if report.get('project') == entry.get('project') and report.get('id') == entry.get('id'):
            existing = report
            reports[idx] = entry
            break
    if existing is None:
        reports.append(entry)
    _save_all_reports(reports)
    return entry


def save_progress_entry_photos(project, entry_id, files):
    _ensure_paths()
    entry_dir = os.path.join(UPLOAD_ROOT, project, entry_id)
    os.makedirs(entry_dir, exist_ok=True)
    saved_urls = []

    for file in files:
        if not file or file.filename == '':
            continue
        filename = secure_filename(file.filename)
        if not filename:
            filename = f'photo_{int(time.time() * 1000)}.jpg'
        timestamp = int(time.time() * 1000)
        dest_name = f"{timestamp}_{filename}"
        dest_path = os.path.join(entry_dir, dest_name)
        file.save(dest_path)
        saved_urls.append(f"/static/uploads/progress/{project}/{entry_id}/{dest_name}")

    return saved_urls


def build_status_summary(entries):
    summary = {status: 0 for status in STATUS_VALUES}
    total = len(entries)
    for entry in entries:
        status = entry.get('status')
        if status in summary:
            summary[status] += 1
        else:
            summary.setdefault(status, 0)
            summary[status] += 1

    complete_statuses = {'Completed', 'No issues', 'Do Not Repair'}
    complete_count = sum(summary.get(status, 0) for status in complete_statuses)
    percent_complete = int((complete_count / total) * 100) if total else 0

    return {
        'total': total,
        'counts': summary,
        'complete_count': complete_count,
        'percent_complete': percent_complete
    }
