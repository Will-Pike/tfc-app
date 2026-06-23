import os
import platform
import shutil
import tempfile
import requests
import gspread
from weasyprint import HTML
from PIL import Image, ImageFile
from PyPDF2 import PdfMerger
from jinja2 import Environment, FileSystemLoader
import logging

# Configure logging for debugging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
from oauth2client.service_account import ServiceAccountCredentials
try:
    from rq import get_current_job
except ImportError:
    get_current_job = None
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials
import io
from googleapiclient.http import MediaIoBaseUpload
import pickle
import os
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import io
from googleapiclient.http import MediaIoBaseUpload
import time

SERVICE_FILE = "./service-account.json"
SPREADSHEET_ID = "16xuo0Uuyku5qD5Ul6VDO86I3rVSFzUedgVXMKfUv5CE"

# Debug mode - set to False in production to avoid filling disk
DEBUG_HTML = os.getenv('DEBUG_HTML', 'False').lower() == 'true'

IMAGE_MAX_DIM = int(os.getenv('REPORT_IMAGE_MAX_DIM', '1600'))
IMAGE_JPEG_QUALITY = int(os.getenv('REPORT_IMAGE_JPEG_QUALITY', '75'))
ImageFile.LOAD_TRUNCATED_IMAGES = True

def compress_image(image_path):
    with Image.open(image_path) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((IMAGE_MAX_DIM, IMAGE_MAX_DIM), Image.LANCZOS)
        img.save(image_path, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)

# Google Drive folder ID where photos should be uploaded
DRIVE_FOLDER_ID = "1J0vCCtKs2nBvL0cZFuye_FtGKjk7ZkEFZwgqtaHtRx_ygPItIuz5eiegm_FyWvQl866QR-bC"

# OAuth settings
SCOPES = ['https://www.googleapis.com/auth/drive.file']
CLIENT_SECRETS_FILE = "client_secret.json"  # You'll need to create this
TOKEN_FILE = "token.pickle"

def generate_report_for_project(project, start_date=None, end_date=None):
    # Write debug to a file that we can check
    debug_file = "/tmp/schnurr_debug.log"
    
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    rows = sheet.get_all_records()

    with open(debug_file, "a") as df:
        df.write(f"\n=== REPORT GENERATION START ===\n")
        df.write(f"Total rows from sheet: {len(rows)}\n")
        df.write(f"Project requested: '{project}' (len={len(project)})\n")

    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("report.html")

    pdf_files = []

    price_dict = load_price_dictionary()
    
    if rows:
        # Show ALL project values in the sheet
        project_values = {}
        for idx, row in enumerate(rows):
            project_val = row.get("Project", "")
            if project_val:
                if project_val not in project_values:
                    project_values[project_val] = 0
                project_values[project_val] += 1
        
        with open(debug_file, "a") as df:
            df.write(f"All unique projects in sheet: {project_values}\n")
            # Check for exact match details
            for project_val, count in project_values.items():
                matches = project_val == project
                df.write(f"  Project '{project_val}' (len={len(project_val)}, count={count}): matches='{matches}'\n")
    
    # Parse date range if provided
    from datetime import datetime
    start_dt = None
    end_dt = None
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        # Set end date to end of day
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        end_dt = end_dt.replace(hour=23, minute=59, second=59)

    # Get current job for progress tracking
    job = get_current_job() if get_current_job else None
    
    # First pass: count matching records for progress tracking
    matching_rows = []
    for row in rows:
        if row.get("Project", "") != project:
            continue
        
        # Filter by date range if provided
        if start_dt or end_dt:
            timestamp_str = row.get("Timestamp", "")
            if timestamp_str:
                try:
                    row_dt = datetime.strptime(timestamp_str, "%m/%d/%Y %H:%M:%S")
                except ValueError:
                    try:
                        row_dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                
                if start_dt and row_dt < start_dt:
                    continue
                if end_dt and row_dt > end_dt:
                    continue
        
        matching_rows.append(row)
    
    total_records = len(matching_rows)
    
    with open(debug_file, "a") as df:
        df.write(f"Matching records after date filtering: {total_records}\n")
        if start_date or end_date:
            df.write(f"Date range: {start_date} to {end_date}\n")
        if total_records == 0:
            df.write(f"ERROR: No matching records found!\n")
    
    logger.info(f"Matching records found: {total_records} (project: '{project}')")
    print(f"[SCHNURR-DEBUG] Matching records found: {total_records} (project: '{project}')", flush=True)
    if total_records == 0:
        raise FileNotFoundError(f"No records found for project: {project}")
    
    # Update job metadata with total count
    if job:
        job.meta['total'] = total_records
        job.meta['processed'] = 0
        job.meta['status'] = 'generating_pdfs'
        job.meta['last_updated'] = time.time()
        job.save_meta()

    with tempfile.TemporaryDirectory() as temp_dir:
        for idx, row in enumerate(matching_rows):
            issue_type = row.get("Issue:", "")
            cost = price_dict.get(issue_type, row.get("Estimated Cost", "N/A"))

            record = {
                "project": row.get("Project", ""),
                "obs_number": row.get("OBS ID#", "N/A"),
                "date": row.get("Timestamp", ""),
                "floor": row.get("Floor:", ""),
                "room": row.get("Room:", ""),
                "user": row.get("User:", ""),
                "description": issue_type,
                "responsible": row.get("Who is responsible?", ""),
                "cost": cost,
                "photo_paths": [],  # Changed to list for multiple photos
                "additional_fields": {}  # Store any additional form fields
            }
            
            # Capture all additional fields that aren't in the standard set
            standard_fields = {"Project", "OBS ID#", "Timestamp", "Floor:", "Room:", "User:", 
                             "Issue:", "Who is responsible?", "Upload photo:", "Estimated Cost"}
            for key, value in row.items():
                if key not in standard_fields and value:  # Only include non-empty additional fields
                    record["additional_fields"][key] = value

            # Handle multiple photo URLs
            photo_urls = row.get("Upload photo:", "")
            if photo_urls:
                # Parse multiple URLs (comma-separated)
                urls = [url.strip() for url in photo_urls.split(',') if url.strip()]
                
                for photo_idx, photo_url in enumerate(urls):
                    if "drive.google.com" in photo_url and "id=" in photo_url:
                        file_id = photo_url.split("id=")[-1].split('&')[0]  # Handle additional parameters
                        direct_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                        try:
                            response = requests.get(direct_url, stream=True, timeout=10)
                            response.raise_for_status()
                            temp_img_path = os.path.join(temp_dir, f"photo_{idx+1}_{photo_idx+1}.jpg")
                            with open(temp_img_path, 'wb') as f:
                                shutil.copyfileobj(response.raw, f)

                            try:
                                compress_image(temp_img_path)
                            except Exception as e:
                                print(f"⚠️ Image compression failed for OBS {record['obs_number']}, photo {photo_idx+1}: {e}")
                            
                            # Add the file path to the list
                            record["photo_paths"].append(f"file:///{temp_img_path.replace(os.sep, '/')}")
                            print(f"✅ Downloaded photo {photo_idx+1} for OBS {record['obs_number']}")
                            
                        except Exception as e:
                            print(f"⚠️ Image download failed for OBS {record['obs_number']}, photo {photo_idx+1}: {e}")
            
            html_content = template.render(records=[record])
            
            # Debug HTML (only in debug mode)
            if DEBUG_HTML:
                with open(f"debug_{idx+1}.html", "w", encoding="utf-8") as f:
                    f.write(html_content)

            output_file = os.path.join(temp_dir, f"report_{idx+1}.pdf")
            try:
                HTML(string=html_content, base_url=".").write_pdf(output_file)
                pdf_files.append(output_file)
                
                # Update progress
                if job:
                    job.meta['processed'] = idx + 1
                    job.meta['last_updated'] = time.time()  # Add timestamp for heartbeat
                    job.save_meta()
                    print(f"Progress: {idx + 1}/{total_records} PDFs generated")
            except OSError as e:
                print(f"❌ PDF generation failed for OBS {record['obs_number']}: {e}")
                # Save HTML for debugging
                debug_html_path = f"debug_failed_{record['obs_number']}.html"
                with open(debug_html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
                print(f"   Debug HTML saved to: {debug_html_path}")
                raise  # Re-raise to see full error

        print(f"📄 Merging {len(pdf_files)} PDFs into final report...")
        
        # Update job status to merging
        if job:
            job.meta['status'] = 'merging_pdfs'
            job.meta['last_updated'] = time.time()
            job.save_meta()
        
        # Use absolute path in current directory for Windows compatibility
        output_filename = f"report_{project.replace(' ', '_').replace('.', '')}.pdf"
        output_path = os.path.abspath(output_filename)
        
        # For large reports (>100 PDFs), use batch merging to avoid memory issues
        if len(pdf_files) > 100:
            print(f"   Using batch merge strategy for {len(pdf_files)} PDFs...")
            batch_size = 50
            temp_merged_files = []
            
            # Merge in batches
            for batch_idx in range(0, len(pdf_files), batch_size):
                batch = pdf_files[batch_idx:batch_idx + batch_size]
                batch_merger = PdfMerger()
                
                try:
                    for pdf in batch:
                        batch_merger.append(pdf)
                    
                    # Write batch to temp file
                    batch_output = os.path.join(temp_dir, f"batch_{batch_idx // batch_size}.pdf")
                    batch_merger.write(batch_output)
                    temp_merged_files.append(batch_output)
                    print(f"   Merged batch {batch_idx // batch_size + 1}/{(len(pdf_files) + batch_size - 1) // batch_size}")
                finally:
                    batch_merger.close()
            
            # Final merge of batches
            print(f"   Combining {len(temp_merged_files)} batches into final report...")
            final_merger = PdfMerger()
            try:
                for temp_file in temp_merged_files:
                    final_merger.append(temp_file)
                
                print(f"✍️  Writing final PDF to {output_filename}...")
                final_merger.write(output_path)
                print(f"✅ Report generation complete: {output_path}")
            except Exception as e:
                print(f"❌ Error during final batch merge: {e}")
                raise
            finally:
                final_merger.close()
        else:
            # For smaller reports, use direct merge
            merger = PdfMerger()
            try:
                for idx, pdf in enumerate(pdf_files):
                    try:
                        merger.append(pdf)
                        # Log progress every 50 PDFs to show merge is progressing
                        if (idx + 1) % 50 == 0:
                            print(f"   Merged {idx + 1}/{len(pdf_files)} PDFs...")
                    except Exception as e:
                        print(f"⚠️  Warning: Failed to merge PDF {idx + 1}: {e}")
                        continue
                
                print(f"✍️  Writing final PDF to {output_filename}...")
                merger.write(output_path)
                print(f"✅ Report generation complete: {output_path}")
            except Exception as e:
                print(f"❌ Error during PDF merge: {e}")
                raise
            finally:
                merger.close()

        return output_path

def load_price_dictionary():
    PRICE_SHEET_ID = "1DBpjjmtaiUeGV_eeCwrihEOBrDk8aRKdDUQERFQBLRA"
    PRICE_SHEET_NAME = "Sheet1"
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(PRICE_SHEET_ID).worksheet(PRICE_SHEET_NAME)
    rows = sheet.get_all_records()
    # Build a dictionary: {issue_type: cost}
    price_dict = {row["Issue Type"]: row["Cost Estimate"] for row in rows}
    return price_dict

def generate_csv_for_project(project, start_date=None, end_date=None):
    """Generate CSV file for a project with optional date range"""
    import csv
    from datetime import datetime
    
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    
    # Load price dictionary for cost lookup
    price_dict = load_price_dictionary()
    
    # Get all rows and headers
    all_data = sheet.get_all_values()
    if not all_data:
        raise ValueError(f"No data found for project: {project}")
    
    headers = all_data[0]
    rows = all_data[1:]
    
    # Find project column index
    try:
        project_col_idx = headers.index("Project")
    except ValueError:
        raise ValueError("Project column not found in spreadsheet")
    
    # Find timestamp column index for date filtering
    timestamp_col_idx = None
    try:
        timestamp_col_idx = headers.index("Timestamp")
    except ValueError:
        pass  # If no timestamp column, skip date filtering
    
    # Find issue type column index for cost lookup
    issue_col_idx = None
    try:
        issue_col_idx = headers.index("Issue:")
    except ValueError:
        pass  # If no issue column, skip cost lookup
    
    # Check if Estimated Cost column already exists
    cost_col_idx = None
    try:
        cost_col_idx = headers.index("Estimated Cost")
    except ValueError:
        # Add Estimated Cost column if it doesn't exist
        headers = list(headers) + ["Estimated Cost"]
    
    # Parse date range if provided
    start_dt = None
    end_dt = None
    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        end_dt = end_dt.replace(hour=23, minute=59, second=59)
    
    # Filter rows for this project and date range
    filtered_rows = []
    for row in rows:
        if len(row) <= project_col_idx or row[project_col_idx] != project:
            continue
        
        # Filter by date if timestamp column exists and date range provided
        if timestamp_col_idx is not None and (start_dt or end_dt):
            if len(row) > timestamp_col_idx and row[timestamp_col_idx]:
                try:
                    row_dt = datetime.strptime(row[timestamp_col_idx], "%m/%d/%Y %H:%M:%S")
                except ValueError:
                    try:
                        row_dt = datetime.strptime(row[timestamp_col_idx], "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue  # Skip rows with unparseable dates
                
                if start_dt and row_dt < start_dt:
                    continue
                if end_dt and row_dt > end_dt:
                    continue
        
        # Add or update estimated cost
        row = list(row)  # Convert to list so we can modify it
        
        if cost_col_idx is None:
            # Add new cost column
            if issue_col_idx is not None and len(row) > issue_col_idx:
                issue_type = row[issue_col_idx]
                cost = price_dict.get(issue_type, "N/A")
                row.append(str(cost))
            else:
                row.append("N/A")
        else:
            # Update existing cost column
            if issue_col_idx is not None and len(row) > issue_col_idx:
                issue_type = row[issue_col_idx]
                cost = price_dict.get(issue_type, row[cost_col_idx] if len(row) > cost_col_idx else "N/A")
                # Ensure row is long enough for cost column
                while len(row) <= cost_col_idx:
                    row.append("")
                row[cost_col_idx] = str(cost)
        
        filtered_rows.append(row)
    
    if not filtered_rows:
        raise FileNotFoundError(f"No records found for project: {project} in the specified date range")
    
    # Write CSV file
    output_filename = f"report_{project.replace(' ', '_').replace('.', '')}.csv"
    output_path = os.path.abspath(output_filename)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        writer.writerows(filtered_rows)
    
    return output_path

def generate_both_reports(project, start_date, end_date):
    """Generate both PDF and CSV reports for a project with date range"""
    debug_file = "/tmp/schnurr_debug.log"
    
    with open(debug_file, "a") as df:
        df.write(f"\n=== GENERATE_BOTH_REPORTS CALLED ===\n")
        df.write(f"Project: {project}, Start: {start_date}, End: {end_date}\n")
    
    job = get_current_job() if get_current_job else None

    if job:
        # Initialize metadata with placeholders so UI doesn't show 0/0
        job.meta['status'] = 'generating_csv'
        job.meta['total'] = 1  # Placeholder, will be updated during PDF generation
        job.meta['processed'] = 0
        job.meta['last_updated'] = time.time()
        job.save_meta()
        with open(debug_file, "a") as df:
            df.write(f"Job metadata initialized: status=generating_csv, total=1, processed=0\n")

    try:
        csv_path = generate_csv_for_project(project, start_date, end_date)
        with open(debug_file, "a") as df:
            df.write(f"CSV generated successfully: {csv_path}\n")
    except Exception as e:
        with open(debug_file, "a") as df:
            df.write(f"CSV generation FAILED: {type(e).__name__}: {e}\n")
        raise

    if job:
        job.meta['csv_path'] = csv_path
        job.meta['status'] = 'generating_pdfs'
        job.meta['last_updated'] = time.time()
        job.save_meta()
        with open(debug_file, "a") as df:
            df.write(f"Job metadata set: status=generating_pdfs\n")

    try:
        pdf_path = generate_report_for_project(project, start_date, end_date)
        with open(debug_file, "a") as df:
            df.write(f"PDF generated successfully: {pdf_path}\n")
    except Exception as e:
        with open(debug_file, "a") as df:
            df.write(f"PDF generation FAILED: {type(e).__name__}: {e}\n")
        raise
    
    with open(debug_file, "a") as df:
        df.write(f"=== GENERATE_BOTH_REPORTS COMPLETED ===\n")
    
    return {
        'pdf_path': pdf_path,
        'csv_path': csv_path
    }

def get_all_issue_types():
    """Get all issue types and their costs from the Patch Cost Estimates spreadsheet"""
    try:
        price_dict = load_price_dictionary()
        return price_dict
    except Exception as e:
        print(f"Error getting issue types: {e}")
        return {}

def get_report_record_count(project):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    rows = sheet.get_all_records()
    return sum(1 for row in rows if row.get("Project", "") == project)

def get_last_row_data():
    """Get the last row of data from the spreadsheet"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        rows = sheet.get_all_records()
        
        if rows:
            last_row = rows[-1]  # Get the last row
            return {
                "project": last_row.get("Project", ""),
                "user": last_row.get("User:", ""),
                "floor": last_row.get("Floor:", ""),
                "room": last_row.get("Room:", "")
            }
        return None
    except Exception as e:
        print(f"Error getting last row data: {e}")
        return None

def get_highest_obs_for_project(project):
    """Get the highest OBS number for a specific project from the spreadsheet"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        rows = sheet.get_all_records()
        
        highest_obs = 0
        for row in rows:
            if row.get("Project", "") == project:
                obs_id = row.get("OBS ID#", "")
                # Extract number from OBS ID (assuming format like "1-A-001" or just "1")
                try:
                    # If it's a format like "1-A-001", extract the last part
                    if isinstance(obs_id, str) and '-' in obs_id:
                        obs_number = int(obs_id.split('-')[-1])
                    else:
                        obs_number = int(obs_id)
                    highest_obs = max(highest_obs, obs_number)
                except (ValueError, TypeError):
                    continue
        
        return highest_obs
    except Exception as e:
        print(f"Error getting highest OBS for project {project}: {e}")
        return 0

def get_obs_list_for_project(project):
    """Get list of all OBS entries for a specific project"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        rows = sheet.get_all_records()
        
        obs_list = []
        for idx, row in enumerate(rows):
            if row.get("Project", "") == project:
                obs_list.append({
                    "row_index": idx + 2,  # +2 because sheets are 1-indexed and we skip header
                    "obs_id": row.get("OBS ID#", ""),
                    "date": row.get("Timestamp", ""),
                    "floor": row.get("Floor:", ""),
                    "room": row.get("Room:", ""),
                    "issue": row.get("Issue:", ""),
                    "user": row.get("User:", "")
                })
        
        # Sort by OBS ID descending (newest first)
        obs_list.sort(key=lambda x: str(x.get("obs_id", "")), reverse=True)
        return obs_list
    except Exception as e:
        print(f"Error getting OBS list: {e}")
        return []

def get_obs_details(project, obs_id):
    """Get detailed information for a specific OBS entry"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        rows = sheet.get_all_records()
        
        for idx, row in enumerate(rows):
            if row.get("Project", "") == project and str(row.get("OBS ID#", "")) == str(obs_id):
                # Get photo URLs using the correct column name
                photo_url = row.get("Upload photo:", "")
                
                # Debug: Print what we found
                print(f"Found photo URL for OBS {obs_id}: '{photo_url}'")
                
                # Clean up photo URLs - handle various formats
                if photo_url:
                    # Remove any extra whitespace, newlines, and normalize separators
                    photo_url = photo_url.replace('\n', ',').replace('\r', ',').replace(';', ',')
                    photo_url = photo_url.strip()
                
                # Build the base response
                response = {
                    "row_index": idx + 2,
                    "project": row.get("Project", ""),
                    "obs_id": row.get("OBS ID#", ""),
                    "timestamp": row.get("Timestamp", ""),
                    "user": row.get("User:", ""),
                    "floor": row.get("Floor:", ""),
                    "room": row.get("Room:", ""),
                    "issue": row.get("Issue:", ""),
                    "responsible": row.get("Who is responsible?", ""),
                    "photo_url": photo_url
                }
                
                # Add any additional fields dynamically
                standard_fields = {"Project", "OBS ID#", "Timestamp", "Floor:", "Room:", "User:", 
                                 "Issue:", "Who is responsible?", "Upload photo:", "Estimated Cost", "row_index"}
                for key, value in row.items():
                    if key not in standard_fields and value:
                        response[key] = value
                
                return response
        return None
    except Exception as e:
        print(f"Error getting OBS details: {e}")
        return None

def update_obs_in_spreadsheet(project, obs_id, updated_data):
    """Update an OBS entry in the spreadsheet"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        
        # Get header row to map field names to column numbers
        headers = sheet.row_values(1)
        
        # Create a mapping of field names to column indices
        column_map = {}
        for i, header in enumerate(headers):
            column_map[header] = i + 1  # +1 because sheets are 1-indexed
        
        # Find the row to update
        rows = sheet.get_all_records()
        for idx, row in enumerate(rows):
            if row.get("Project", "") == project and str(row.get("OBS ID#", "")) == str(obs_id):
                row_index = idx + 2  # +2 because sheets are 1-indexed and we skip header
                
                # Update the fields using the column mapping
                if 'user' in updated_data and 'User:' in column_map:
                    sheet.update_cell(row_index, column_map['User:'], updated_data['user'])
                if 'floor' in updated_data and 'Floor:' in column_map:
                    sheet.update_cell(row_index, column_map['Floor:'], updated_data['floor'])
                if 'room' in updated_data and 'Room:' in column_map:
                    sheet.update_cell(row_index, column_map['Room:'], updated_data['room'])
                if 'issue' in updated_data and 'Issue:' in column_map:
                    sheet.update_cell(row_index, column_map['Issue:'], updated_data['issue'])
                if 'responsible' in updated_data and 'Who is responsible?' in column_map:
                    sheet.update_cell(row_index, column_map['Who is responsible?'], updated_data['responsible'])
                # Handle photo URL updates if needed
                if 'photo_urls' in updated_data and 'Upload photo:' in column_map:
                    sheet.update_cell(row_index, column_map['Upload photo:'], updated_data['photo_urls'])
                
                return True
        return False
    except Exception as e:
        print(f"Error updating OBS: {e}")
        return False

def debug_spreadsheet_data(project, obs_id):
    """Debug function to see raw spreadsheet data"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        
        # Get headers
        headers = sheet.row_values(1)
        
        # Get all rows
        rows = sheet.get_all_records()
        
        # Find the specific row
        for idx, row in enumerate(rows):
            if row.get("Project", "") == project and str(row.get("OBS ID#", "")) == str(obs_id):
                return {
                    "headers": headers,
                    "row_data": row,
                    "photo_column_names": [h for h in headers if 'photo' in h.lower() or 'upload' in h.lower()],
                    "photo_data": row.get("Upload photo:", "")
                }
        
        return {"error": "Row not found", "headers": headers}
    except Exception as e:
        return {"error": str(e)}

def get_oauth_drive_service():
    """Get an authenticated Drive service using OAuth"""
    creds = None
    
    # Load existing token
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    # If there are no (valid) credentials available, return None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            return None  # Need to run OAuth flow
    
    # Save the credentials for the next run
    with open(TOKEN_FILE, 'wb') as token:
        pickle.dump(creds, token)
    
    return build('drive', 'v3', credentials=creds)

def upload_photo_to_drive(file_data, filename, project, obs_id):
    """Upload a photo using OAuth (user's Drive quota)"""
    try:
        service = get_oauth_drive_service()
        if not service:
            return None
        
        # Create a unique filename
        timestamp = int(time.time())
        unique_filename = f"{project}_{obs_id}_{timestamp}_{filename}"
        
        # Detect file type
        mimetype = 'image/jpeg'
        if filename.lower().endswith('.png'):
            mimetype = 'image/png'
        elif filename.lower().endswith('.gif'):
            mimetype = 'image/gif'
        elif filename.lower().endswith('.webp'):
            mimetype = 'image/webp'
        
        # File metadata - use your original folder ID
        file_metadata = {
            'name': unique_filename,
            'parents': ['1J0vCCtKs2nBvL0cZFuye_FtGKjk7ZkEFZwgqtaHtRx_ygPItIuz5eiegm_FyWvQl866QR-bC']
        }
        
        # Create media upload
        media = MediaIoBaseUpload(
            io.BytesIO(file_data),
            mimetype=mimetype,
            resumable=True
        )
        
        # Upload the file
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        file_id = file.get('id')
        
        # Make the file publicly viewable
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        service.permissions().create(
            fileId=file_id,
            body=permission
        ).execute()
        
        # Return the shareable URL
        shareable_url = f"https://drive.google.com/open?id={file_id}"
        
        print(f"Uploaded photo: {unique_filename} -> {shareable_url}")
        return shareable_url
        
    except Exception as e:
        print(f"Error uploading photo to Drive: {e}")
        return None

def add_photo_urls_to_obs(project, obs_id, new_photo_urls):
    """Add new photo URLs to an existing OBS entry"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        
        # Get header row to find the photo column
        headers = sheet.row_values(1)
        photo_column = None
        for i, header in enumerate(headers):
            if header == "Upload photo:":
                photo_column = i + 1  # +1 because sheets are 1-indexed
                break
        
        if not photo_column:
            print("Photo column 'Upload photo:' not found in spreadsheet")
            return False
        
        # Find the row to update
        rows = sheet.get_all_records()
        for idx, row in enumerate(rows):
            if row.get("Project", "") == project and str(row.get("OBS ID#", "")) == str(obs_id):
                row_index = idx + 2  # +2 because sheets are 1-indexed and we skip header
                
                # Get existing photo URLs
                existing_urls = row.get("Upload photo:", "")
                
                # Combine existing and new URLs
                if existing_urls.strip():
                    combined_urls = existing_urls + ", " + ", ".join(new_photo_urls)
                else:
                    combined_urls = ", ".join(new_photo_urls)
                
                # Update the cell
                sheet.update_cell(row_index, photo_column, combined_urls)
                
                print(f"Updated photo URLs for OBS {obs_id}: {combined_urls}")
                return True
        
        print(f"OBS {obs_id} not found for project {project}")
        return False
        
    except Exception as e:
        print(f"Error adding photo URLs to spreadsheet: {e}")
        return False

def remove_photo_url_from_obs(project, obs_id, photo_url_to_remove):
    """Remove a specific photo URL from an OBS entry"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_FILE, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        
        # Get header row to find the photo column
        headers = sheet.row_values(1)
        photo_column = None
        for i, header in enumerate(headers):
            if header == "Upload photo:":
                photo_column = i + 1  # +1 because sheets are 1-indexed
                break
        
        if not photo_column:
            print("Photo column 'Upload photo:' not found in spreadsheet")
            return False
        
        # Find the row to update
        rows = sheet.get_all_records()
        for idx, row in enumerate(rows):
            if row.get("Project", "") == project and str(row.get("OBS ID#", "")) == str(obs_id):
                row_index = idx + 2  # +2 because sheets are 1-indexed and we skip header
                
                # Get existing photo URLs
                existing_urls = row.get("Upload photo:", "")
                
                # Parse and filter out the URL to remove
                if existing_urls:
                    url_list = [url.strip() for url in existing_urls.split(',') if url.strip()]
                    filtered_urls = [url for url in url_list if url != photo_url_to_remove.strip()]
                    
                    # Update the cell with remaining URLs
                    updated_urls = ', '.join(filtered_urls) if filtered_urls else ''
                    sheet.update_cell(row_index, photo_column, updated_urls)
                    
                    print(f"Removed photo URL from OBS {obs_id}: {photo_url_to_remove}")
                    return True
                else:
                    print(f"No photos found for OBS {obs_id}")
                    return False
        
        print(f"OBS {obs_id} not found for project {project}")
        return False
        
    except Exception as e:
        print(f"Error removing photo URL from spreadsheet: {e}")
        return False

def delete_photo_from_drive(photo_url):
    """Optionally delete photo from Google Drive (use with caution)"""
    try:
        # Extract file ID from URL
        import re
        file_id_match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', photo_url)
        if not file_id_match:
            print(f"Could not extract file ID from URL: {photo_url}")
            return False
        
        file_id = file_id_match.group(1)
        
        # Use OAuth to delete (requires drive scope)
        service = get_oauth_drive_service()
        if not service:
            print("Could not get OAuth Drive service")
            return False
        
        service.files().delete(fileId=file_id).execute()
        print(f"Deleted file from Drive: {file_id}")
        return True
        
    except Exception as e:
        print(f"Error deleting file from Drive: {e}")
        return False

def add_photos_to_pdf(pdf, photo_urls, page_width, margin):
    """Add multiple photos to PDF with proper layout"""
    if not photo_urls:
        return
    
    # Parse photo URLs
    urls = [url.strip() for url in photo_urls.split(',') if url.strip()]
    if not urls:
        return
    
    from reportlab.lib.units import inch
    from reportlab.platypus import Image
    import requests
    from io import BytesIO
    import tempfile
    import os
    
    # Calculate layout
    photos_per_row = 2 if len(urls) > 1 else 1
    photo_width = (page_width - 2 * margin - (photos_per_row - 1) * 0.25 * inch) / photos_per_row
    photo_height = photo_width * 0.75  # 4:3 aspect ratio
    
    current_x = margin
    current_y = pdf._y - photo_height - 0.25 * inch
    
    for i, url in enumerate(urls):
        try:
            # Convert Google Drive URL to downloadable format
            if 'drive.google.com' in url:
                # Extract file ID and create direct download URL
                import re
                file_id_match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
                if file_id_match:
                    file_id = file_id_match.group(1)
                    download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                else:
                    print(f"Could not extract file ID from URL: {url}")
                    continue
            else:
                download_url = url
            
            # Download the image
            response = requests.get(download_url, timeout=30)
            if response.status_code == 200:
                # Create temporary file
                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                    temp_file.write(response.content)
                    temp_path = temp_file.name
                
                try:
                    # Add image to PDF
                    img = Image(temp_path, width=photo_width, height=photo_height)
                    img.drawOn(pdf._doc, current_x, current_y)
                    
                    # Add photo caption
                    pdf.setFont("Helvetica", 8)
                    pdf.drawString(current_x, current_y - 15, f"Photo {i + 1}")
                    
                    # Update position for next photo
                    if (i + 1) % photos_per_row == 0:
                        # Move to next row
                        current_x = margin
                        current_y -= photo_height + 0.5 * inch
                    else:
                        # Move to next column
                        current_x += photo_width + 0.25 * inch
                    
                finally:
                    # Clean up temporary file
                    try:
                        os.unlink(temp_path)
                    except:
                        pass
            else:
                print(f"Failed to download image from {download_url}: {response.status_code}")
                
        except Exception as e:
            print(f"Error processing photo {url}: {e}")
            continue
    
    # Update PDF y position
    pdf._y = current_y - 0.25 * inch






