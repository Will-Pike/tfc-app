import os
import shutil
import tempfile
import requests
import gspread
import pdfkit
from PyPDF2 import PdfMerger
from jinja2 import Environment, FileSystemLoader
from oauth2client.service_account import ServiceAccountCredentials

# Path to the wkhtmltopdf binary. Defaults to the Linux install location used
# on the EC2 host; override with WKHTMLTOPDF_PATH for local dev (e.g. Windows).
WKHTMLTOPDF_PATH = os.environ.get("WKHTMLTOPDF_PATH", "/usr/bin/wkhtmltopdf")
SERVICE_FILE = os.environ.get("SERVICE_FILE", "./service-account.json")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "16xuo0Uuyku5qD5Ul6VDO86I3rVSFzUedgVXMKfUv5CE")


def _pdfkit_config():
    """Resolve the wkhtmltopdf binary lazily.

    Building this at import time means the whole app fails to boot when the
    binary is missing (e.g. local dev). Resolving it on first use keeps the web
    app running and surfaces a clear error only on the report route.
    """
    return pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)


def generate_report_for_project(project):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    rows = sheet.get_all_records()

    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("report.html")

    pdf_files = []

    with tempfile.TemporaryDirectory() as temp_dir:
        for idx, row in enumerate(rows):
            if row.get("Project", "") != project:
                continue

            record = {
                "obs_number": row.get("OBS ID#", "N/A"),
                "date": row.get("Timestamp", ""),
                "description": row.get("Issue:", ""),
                "cost": row.get("Estimated Cost", "0"),
                "photo_path": ""
            }

            photo_url = row.get("Upload photo:", "")
            temp_img_path = None
            if "drive.google.com" in photo_url and "id=" in photo_url:
                file_id = photo_url.split("id=")[-1]
                direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                try:
                    response = requests.get(direct_url, stream=True, timeout=10)
                    response.raise_for_status()
                    temp_img_path = os.path.join(temp_dir, f"photo_{idx+1}.jpg")
                    with open(temp_img_path, 'wb') as f:
                        shutil.copyfileobj(response.raw, f)
                    record["photo_path"] = f"file:///{temp_img_path.replace(os.sep, '/')}"
                    # Only print if download succeeded
                    with open(temp_img_path, 'rb') as f:
                        print(f.read(10))
                except Exception as e:
                    print(f"⚠️ Image download failed for OBS {record['obs_number']}: {e}")
            
            html_content = template.render(records=[record])
            
            # Debug HTML
            with open(f"debug_{idx+1}.html", "w", encoding="utf-8") as f:
                f.write(html_content)

            output_file = os.path.join(temp_dir, f"report_{idx+1}.pdf")
            pdfkit.from_string(
                html_content, 
                output_file, 
                configuration=_pdfkit_config(),
                options={'enable-local-file-access': None}
            )
            pdf_files.append(output_file)

        if not pdf_files:
            raise FileNotFoundError(f"No records found for project: {project}")

        merger = PdfMerger()
        for pdf in pdf_files:
            merger.append(pdf)
        combined_pdf = f"combined_report_{project.replace(' ', '_')}.pdf"
        merger.write(combined_pdf)
        merger.close()

        return combined_pdf






