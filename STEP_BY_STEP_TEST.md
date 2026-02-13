🧪 STEP-BY-STEP TEST GUIDE
==========================

Follow these steps in order. Each step should work before moving to next.


STEP 1: CREATE VALID EXCEL FILE
================================

Run this command:
  python test_bulk_upload.py

What it does:
  ✓ Creates sample_customers.xlsx
  ✓ Creates 3 sample customers
  ✓ Validates Excel format

Expected output:
  ✓ Created: sample_customers.xlsx
  Enter your Bearer token:

Result:
  ✓ File sample_customers.xlsx exists
  ✓ Can open in Excel, see headers + data


STEP 2: GET YOUR TOKEN
======================

In Postman:

1. Create new request
   Method: POST
   URL: http://localhost:8000/api/auth/login

2. Body (JSON):
   {
     "username": "admin",
     "password": "admin_password"
   }

3. Send

4. Look at response, find:
   "access_token": "eyJ0eXAi..."

5. Copy just the token value (long string starting with eyJ)

Result:
  ✓ You have a valid token
  ✓ Example: eyJ0eXAiOiJKV1QiLC...


STEP 3: TEST WITHOUT LOGOS (SIMPLEST)
======================================

In Postman:

1. Create new request
   Method: POST
   URL: http://localhost:8000/api/customer/bulk-upload

2. Authorization Tab:
   Type: Bearer Token
   Token: [paste your token]

3. Body Tab:
   Select: form-data
   
   Add ONE field:
   Key: excel_file
   Type: File
   Value: [Click, select sample_customers.xlsx]

4. Verify:
   ☑ Blue upload icon appears next to file
   ☑ Filename shows: sample_customers.xlsx
   ☑ Authorization shows your token

5. Click Send

Expected Response (200 OK):
  {
    "message": "Bulk upload completed",
    "total_rows": 3,
    "successful": 3,
    "failed": 0,
    "results": [...]
  }

✅ SUCCESS! Move to next step.

❌ ERROR? 
  - Check troubleshooting guide
  - Check server logs (uvicorn terminal)
  - Make sure Excel file selected (blue icon)


STEP 4: TEST WITH SINGLE LOGO
=============================

Now add one logo image:

1. Same as STEP 3, but add another field

2. Body → form-data:
   
   Field 1:
   Key: excel_file
   Type: File
   Value: sample_customers.xlsx
   
   Field 2:
   Key: logo
   Type: File
   Value: [Select any image file]

3. Verify:
   ☑ Both fields have files selected
   ☑ Blue upload icons visible

4. Click Send

Expected Response:
  {
    "successful": 3,
    "failed": 0,
    ...
  }

✅ SUCCESS! First customer should have logo.


STEP 5: TEST WITH MULTIPLE LOGOS
==================================

Add more logo images:

Body → form-data:
  
  Field 1:
  Key: excel_file
  Type: File
  Value: sample_customers.xlsx
  
  Field 2:
  Key: logo
  Type: File
  Value: [First image]
  
  Field 3:
  Key: logo
  Type: File
  Value: [Second image]
  
  Field 4:
  Key: logo
  Type: File
  Value: [Third image]

(All logo fields use same key "logo")

Click Send

Expected:
  Row 2 (John) → Gets logo 1
  Row 3 (Jane) → Gets logo 2
  Row 4 (Bob) → Gets logo 3


STEP 6: TEST WITH YOUR OWN EXCEL
==================================

1. Create your own Excel file:
   - Save as .xlsx (not .csv)
   - Headers: username, email, password, full_name
   - Your customer data

2. Same Postman test:
   - excel_file field: Your file
   - logo fields: Your images (optional)

3. Send and verify


✅ COMPLETE TEST FLOW
====================

Test 1: Excel only (no logos)
  ✓ Create Excel
  ✓ Upload in Postman
  → Should succeed

Test 2: Excel + 1 logo
  ✓ Add 1 logo field
  → Should succeed

Test 3: Excel + 3 logos
  ✓ Add 3 logo fields
  → Should succeed

Test 4: Your own Excel
  ✓ Create your file
  ✓ Upload with/without logos
  → Should succeed


🔍 IF STEP FAILS
================

At any step, if you get error:

1. Check error message:
   "File is not a zip file" → Excel file issue
   "excel_file is required" → Field name wrong
   "401 Unauthorized" → Token invalid/expired
   "Other" → Check server logs

2. Look at server logs (uvicorn terminal):
   $ uvicorn app.main:app --reload
   
   Look for:
   ✓ "📄 Excel headers: ..."
   ✓ "❌ Excel read error: ..."
   ✓ "❌ Bulk upload error: ..."

3. Fix issue:
   - Re-create Excel file
   - Re-select file in Postman
   - Get fresh token
   - Check file format

4. Try step again


💡 DEBUG TIPS
=============

✓ Watch server logs while sending
✓ Check Postman console (View → Show Postman Console)
✓ Verify blue upload icon appears
✓ Verify filename is correct (.xlsx)
✓ Try test_bulk_upload.py generated file first
✓ Use simple customer data (no special chars)


📋 WHAT EACH STEP TESTS
========================

Step 1: Excel file creation ✓
Step 2: Authentication ✓
Step 3: Basic upload (Excel only) ✓
Step 4: Single logo support ✓
Step 5: Multiple logos support ✓
Step 6: Custom data support ✓


🎯 QUICK SUMMARY
================

Can't upload?
  1. Run: python test_bulk_upload.py
  2. Select generated file in Postman
  3. Send without logos first
  4. Check error message
  5. Follow troubleshooting guide

Can upload without logos?
  1. It works! ✓
  2. Now add logos
  3. Use "logo" field (multiple times)
  4. Should work now

Works with logos?
  1. Perfect! ✓
  2. Use for your data
  3. Extract logos customers
  4. Upload together


🚀 NEXT: PRODUCTION USE
=======================

Once tests pass:
  1. Create real Excel with your customers
  2. Save as .xlsx
  3. Prepare customer logos
  4. Upload using same Postman flow
  5. Verify in database


Need help? See:
  → TROUBLESHOOTING_ZIP_ERROR.md
  → POSTMAN_GENERIC_LOGO.md
  → BULK_UPLOAD_API.md
