# 🚀 BULK CUSTOMER UPLOAD - QUICK START GUIDE

This guide walks you through testing the bulk upload API.

# 📁 FILES CREATED FOR YOU

1. ✓ test_bulk_upload.py
   → Python test script with example data generation
   → Run: python test_bulk_upload.py

2. ✓ example_bulk_upload.py  
   → Complete working example
   → Includes all error handling
   → Run: python example_bulk_upload.py

3. ✓ test_bulk_upload.bat (Windows)
   → Batch script for quick testing
   → Run: test_bulk_upload.bat

4. ✓ test_bulk_upload.sh (Linux/Mac)
   → Bash script for quick testing
   → Run: bash test_bulk_upload.sh

5. ✓ BULK_UPLOAD_API.md
   → Full API documentation
   → All details and troubleshooting

# 🎯 QUICK START (5 MINUTES)

## STEP 1: Generate Sample Excel File

Windows PowerShell:
python test_bulk_upload.py

Linux/Mac Terminal:
python test_bulk_upload.py

→ Creates: sample_customers.xlsx

## STEP 2: Get Your Authentication Token

Windows PowerShell:
curl -X POST "http://localhost:8000/api/auth/login" `    -H "Content-Type: application/json"`
-d '{"username":"admin","password":"password"}'

Linux/Mac:
curl -X POST "http://localhost:8000/api/auth/login" \
 -H "Content-Type: application/json" \
 -d '{"username":"admin","password":"password"}'

→ Copy the "access_token" value from response

## STEP 3: Upload Customers

Windows PowerShell:
$TOKEN = "YOUR_TOKEN_HERE"
curl -X POST "http://localhost:8000/api/customer/bulk-upload" `    -H "Authorization: Bearer $TOKEN"`
-F "excel_file=@sample_customers.xlsx"

Linux/Mac:
TOKEN="YOUR_TOKEN_HERE"
curl -X POST "http://localhost:8000/api/customer/bulk-upload" \
 -H "Authorization: Bearer $TOKEN" \
 -F "excel_file=@sample_customers.xlsx"

→ Check response for success/failure count

# 📊 EXCEL FILE FORMAT

Required Columns (Must Have):
• username - Unique ID (no spaces)
• email - Valid email
• password - Any password
• full_name - Customer name

Optional Columns:
• customer_company_name
• city
• phone_number
• telephone_number
• address
• logo_file_name ← Special: must match uploaded logo file

Example:
┌──────────┬──────────────┬──────────┬───────────┬─────────────────────────────┐
│username │email │password │full_name │logo_file_name │
├──────────┼──────────────┼──────────┼───────────┼─────────────────────────────┤
│john_doe │john@test.com │pass123 │John Doe │logo_john.png │
│jane_smith│jane@test.com │pass456 │Jane Smith │logo_jane.jpg │
│bob_wilson│bob@test.com │pass789 │Bob Wilson │ │
└──────────┴──────────────┴──────────┴───────────┴─────────────────────────────┘

# 🖼️ LOGO FILES EXPLAINED

How Logo Mapping Works:

1. Excel has column: logo_file_name
2. Excel row 2 has value: "logo_john.png"
3. When uploading, send file named: logo_john.png
4. API matches them automatically
5. Logo saved to that customer

Example Upload with Logos:
curl -X POST "http://localhost:8000/api/customer/bulk-upload" \
 -H "Authorization: Bearer $TOKEN" \
 -F "excel_file=@customers.xlsx" \
 -F "logo_john.png=@path/to/logo_john.png" \
 -F "logo_jane.jpg=@path/to/logo_jane.jpg"

Important:
✓ Filenames must match exactly (case-sensitive on Linux)
✓ Leave logo_file_name empty if no logo
✓ Logo files are optional

# ✅ API RESPONSE EXAMPLES

SUCCESS (3 customers, all created):
{
"message": "Bulk upload completed",
"total_rows": 3,
"successful": 3,
"failed": 0,
"results": [
{
"success": true,
"row": 2,
"data": {
"message": "Customer created successfully",
"customer_id": "507f1f77bcf86cd799439011",
"user_id": "507f1f77bcf86cd799439012"
}
},
...
]
}

PARTIAL SUCCESS (2 created, 1 failed):
{
"message": "Bulk upload completed",
"total_rows": 3,
"successful": 2,
"failed": 1,
"results": [
{
"success": true,
"row": 2,
"data": { ... }
},
{
"success": false,
"row": 3,
"error": "Email already exists",
"data": { ... }
},
...
]
}

# 🔧 TESTING SCENARIOS

Test 1: Simple Upload (No Logos)

1. Create Excel with 3 customers
2. Leave logo_file_name empty for all
3. Upload only Excel file
   ✓ All 3 should succeed

Test 2: With Logo Files

1. Create Excel with logo_file_name values
2. Prepare matching logo files
3. Upload Excel + logos together
   ✓ Logos should be attached

Test 3: Partial Failures

1. Include duplicate email in Excel
2. Upload
   ✓ Duplicate row should fail, others should succeed

Test 4: Missing Required Fields

1. Excel row with empty username
2. Upload
   ✓ That row should fail with validation error

# 🐛 COMMON ISSUES & FIXES

Issue: "excel_file is required"
✓ Fix: Make sure form field is named "excel_file" (exact)

Issue: "Logo file not found"
✓ Fix: Check filename matches exactly (including case)
✓ Fix: Make sure logic_file_name in Excel isn't empty

Issue: "Email already exists"
✓ Fix: Check customer doesn't exist
✓ Fix: Use unique emails for each row

Issue: Connection refused
✓ Fix: Make sure API server is running
uvicorn app.main:app --reload

Issue: 401 Unauthorized
✓ Fix: Check token is valid and not expired
✓ Fix: Use correct "Authorization: Bearer TOKEN" format

# 📝 STEP-BY-STEP EXAMPLE

Goal: Upload 2 customers with logos

1. Create sample_customers.xlsx:
   username | email | password | full_name | logo_file_name
   acme_corp | acme@test.com | pass123 | ACME Corp | logo_acme.png
   tech_solutions|tech@test.com | pass456 | Tech Inc | logo_tech.jpg

2. Have ready:
   - logo_acme.png (actual image file)
   - logo_tech.jpg (actual image file)

3. Get token:
   curl -X POST "http://localhost:8000/api/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"password"}'

   → Get access_token from response: "eyJ0eXAi..."

4. Upload:
   curl -X POST "http://localhost:8000/api/customer/bulk-upload" \
    -H "Authorization: Bearer eyJ0eXAi..." \
    -F "excel_file=@sample_customers.xlsx" \
    -F "logo_acme.png=@logo_acme.png" \
    -F "logo_tech.jpg=@logo_tech.jpg"

5. Check response:
   {
   "message": "Bulk upload completed",
   "total_rows": 2,
   "successful": 2,
   "failed": 0,
   ...
   }
   ✓ Both customers created with logos!

# 📞 NEED HELP?

See: BULK_UPLOAD_API.md for full documentation - Complete API reference - All error scenarios - Troubleshooting guide - Performance notes

Or run example scripts:
python example_bulk_upload.py

# 🎓 API DETAILS

Endpoint: POST /api/customer/bulk-upload

Authentication: Bearer Token (required)

- Roles: superadmin, company

Content-Type: multipart/form-data

Required Form Fields:

- excel_file: Excel workbook

Optional Form Fields:

- logo\__._ : Logo image files (names must match Excel)

Returns: JSON with results

- status: 200 ok, 400 bad request, 500 error
- message: Overall status
- total_rows: Rows processed
- successful: Count of successes
- failed: Count of failures
- results: Array with per-row details

# ✨ SUMMARY

What you can do now:
✓ Upload multiple customers from Excel
✓ Attach logos to each customer
✓ Handle partial failures gracefully
✓ Get detailed error messages for each row
✓ Create customers in bulk (10+) or individually

Next steps:

1. Run test script: python test_bulk_upload.py
2. Create your Excel file with customer data
3. Get authentication token
4. Upload and verify results

Happy uploading! 🚀
