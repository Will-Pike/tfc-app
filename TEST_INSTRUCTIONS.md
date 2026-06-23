# Testing Instructions for Updated Observation Report App

## Changes Made

The app has been updated to automatically handle:
1. **New Questions** - Any new questions added to the Google Form will automatically appear in:
   - The spreadsheet (Google Forms handles this)
   - The PDF reports
   - The OBS details when editing

2. **New Issue Types** - Any new issue types added to the "Patch Cost Estimates" spreadsheet will:
   - Automatically appear in the edit form dropdown
   - Have their costs automatically pulled from the spreadsheet
   - Work with the PDF generation

## What Was Changed

### 1. `generate_pdf.py`
- Updated `generate_report_for_project()` to capture all additional form fields dynamically
- Updated `get_obs_details()` to return any new columns from the spreadsheet
- Added `get_all_issue_types()` function to fetch issue types and costs from Patch Cost Estimates

### 2. `app.py`
- Added `/get_issue_types` route to serve issue types to the frontend

### 3. `templates/report.html`
- Added section to display any additional fields in the PDF report
- New fields will appear between "Issue Caused By" and "Estimated Cost" sections

### 4. `templates/edit_obs.html`
- Changed issue type dropdown to load dynamically from the server
- Removed hardcoded cost mapping - now fetches from Patch Cost Estimates spreadsheet

## How to Test Locally

### Step 1: Ensure Dependencies Are Installed
```bash
pip install Flask gspread oauth2client pdfkit PyPDF2 Jinja2 google-api-python-client google-auth-oauthlib redis rq requests
```

### Step 2: Verify Configuration Files
Make sure you have:
- `service-account.json` (Google Sheets API credentials)
- `app_config.json` (your current config is fine)
- `client_secret.json` (for OAuth, if using photo uploads)

### Step 3: Start the App
```bash
python app.py
```

The app should start on `http://localhost:5000`

### Step 4: Test New Issue Types

1. **Add New Issue Types to Patch Cost Estimates Spreadsheet:**
   - Open the Patch Cost Estimates spreadsheet (ID: 1DBpjjmtaiUeGV_eeCwrihEOBrDk8aRKdDUQERFQBLRA)
   - Add your 3 new issue types with their cost estimates
   - Format: Column A = "Issue Type", Column B = "Cost Estimate"

2. **Verify Issue Types Load:**
   - Go to http://localhost:5000
   - Click "Edit an OBS Report"
   - Select a project and OBS
   - In the edit modal, the "Issue:" dropdown should show ALL issue types including your new ones
   - The cost should update automatically when you select an issue type

### Step 5: Test New Form Questions

1. **Submit a Test Form Response:**
   - Go to your Google Form
   - Fill out all fields including the 2 new questions you added
   - Submit the form

2. **Generate a PDF Report:**
   - Go to http://localhost:5000
   - Select the project you just submitted to
   - Click "Generate PDF Report"
   - Download the PDF when ready

3. **Verify PDF Contains New Fields:**
   - Open the generated PDF
   - Look for a new section between "Issue Caused By" and "Estimated Cost"
   - The 2 new questions should appear there with their answers

### Step 6: Test Edit Functionality

1. **Edit an OBS with New Data:**
   - Click "Edit an OBS Report"
   - Select the test OBS you just created
   - Try changing the issue type to one of the new ones
   - Verify the cost updates correctly
   - Save changes

2. **Verify Spreadsheet Updated:**
   - Open your Google Sheets spreadsheet
   - Find the OBS you edited
   - Confirm the changes were saved

## Troubleshooting

### Issue: "Error loading issue types"
- Check that `service-account.json` has access to the Patch Cost Estimates spreadsheet
- Verify the spreadsheet ID in `generate_pdf.py` (line ~140) matches your spreadsheet
- Check the sheet name is "Sheet1" or update the code if different

### Issue: New form fields don't appear in PDF
- Verify the form responses are actually in the spreadsheet
- Check that the column headers in the spreadsheet match the form question text
- Look at the browser console for any errors

### Issue: Photos don't load
- This is a separate feature - photos require OAuth setup
- If not using photos, this won't affect your testing

## Expected Behavior

✅ **New issue types automatically appear in dropdowns**
✅ **Costs automatically pulled from Patch Cost Estimates**
✅ **New form questions automatically appear in PDFs**
✅ **Edit form shows all current data including new fields**
✅ **All data saves back to Google Sheets correctly**

## Notes

- The app now reads the spreadsheet structure dynamically
- You don't need to modify code when adding new questions or issue types
- Standard fields (Project, OBS ID#, User, Floor, Room, Issue, Responsible, Photos) are handled specifically
- All other fields are treated as "additional fields" and displayed generically in the PDF

## Contact

If you encounter any issues during testing, check:
1. Browser console (F12) for JavaScript errors
2. Terminal/command prompt for Python errors
3. Google Sheets API quota limits (unlikely but possible)
