# Quick Test Checklist

## Before Starting
- [ ] Redis server is running (for background PDF generation)
- [ ] `service-account.json` is in the project folder
- [ ] Python dependencies are installed

## Quick Start
```bash
# Terminal 1 - Start the app
python app.py

# Terminal 2 - Start the worker (for PDF generation)
python worker.py
```

## Test Checklist

### 1. Test New Issue Types
- [ ] Add 3 new rows to "Patch Cost Estimates" spreadsheet with:
  - Column A: Issue type name (e.g., "Extra Large Patch", "Custom Rework", etc.)
  - Column B: Cost estimate number (e.g., 850)
- [ ] Go to http://localhost:5000/edit_obs
- [ ] Select any project and OBS
- [ ] Click on an OBS to edit
- [ ] Check that "Issue:" dropdown includes your 3 new issue types
- [ ] Select a new issue type
- [ ] Verify the cost updates in the "Estimated Cost" field
- [ ] Click "Save Changes"
- [ ] Check the spreadsheet to confirm it saved

### 2. Test New Form Questions
- [ ] Open your Google Form
- [ ] Submit a test response with all fields filled, including the 2 new questions
- [ ] Wait 30 seconds for it to sync to spreadsheet
- [ ] Go to http://localhost:5000
- [ ] Select the project you submitted to
- [ ] Click "Generate PDF Report"
- [ ] Wait for generation to complete
- [ ] Download and open the PDF
- [ ] Verify the 2 new questions appear in the PDF (between "Issue Caused By" and "Estimated Cost")
- [ ] Verify the answers are correct

### 3. Test Existing Functionality Still Works
- [ ] Create a new OBS (click "Start Observation Report")
- [ ] Fill out the form with regular data
- [ ] Go back to app and generate PDF
- [ ] Verify PDF looks correct with all standard fields

### 4. Test Edit Form with New Data
- [ ] Edit an OBS that has the new form fields filled
- [ ] Verify all fields display correctly (including new ones)
- [ ] Make a change to a new field (if editable in UI)
- [ ] Save and verify in spreadsheet

## Common Issues & Solutions

**Can't connect to Redis:**
```bash
# Install Redis
# Windows: Download from https://github.com/microsoftarchive/redis/releases
# Mac: brew install redis
# Linux: sudo apt-get install redis-server

# Start Redis
# Windows: Run redis-server.exe
# Mac/Linux: redis-server
```

**PDF generation fails:**
- Make sure wkhtmltopdf is installed
- Check WKHTMLTOPDF_PATH in generate_pdf.py (line ~24)
- For Windows: Set to `"C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe"`
- For Mac/Linux: Set to `"/usr/bin/wkhtmltopdf"`

**Issue types don't load:**
- Check console for errors (F12 in browser)
- Verify service account has access to Patch Cost Estimates spreadsheet
- Check spreadsheet ID matches in code

**New form fields don't show:**
- Verify they're in the spreadsheet as column headers
- Check that the form response was actually submitted
- Look at network tab (F12) to see the data being returned

## If Everything Works...

You're ready to add new features! The app is now flexible enough to:
- Add any number of new questions to the form (they'll automatically appear in PDFs)
- Add any number of new issue types (they'll automatically appear in edit dropdown with costs)
- No code changes needed for these additions

## Next Steps

Once testing is complete:
1. Commit your changes: `git add . && git commit -m "Make app handle dynamic form fields and issue types"`
2. Deploy to production (if applicable)
3. Add any new features you mentioned wanting to add

Let me know what new features you'd like to add next!
