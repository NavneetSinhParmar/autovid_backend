🧪 POSTMAN TEST - SIMPLE METHOD (No Logo Keys)
================================================

This is the EASIEST way to test the bulk upload API in Postman.


✅ OPTION 1: TEST WITHOUT LOGOS (RECOMMENDED FOR TESTING)
===========================================================

This is the simplest approach - just upload Excel, no logos.

STEP 1: Create Excel File (No logo column needed)
──────────────────────────────────────────────────

Headers:
  username | email | password | full_name | customer_company_name | city

Example Data:
  john_doe | john@test.com | pass123 | John Doe | Doe Inc | New York
  jane_smith | jane@test.com | pass456 | Jane Smith | Smith Corp | LA
  bob_wilson | bob@test.com | pass789 | Bob Wilson | Wilson LLC | Chicago

Save as: customers.xlsx


STEP 2: Open Postman
─────────────────────

1. Create new request
2. Method: POST
3. URL: http://localhost:8000/api/customer/bulk-upload


STEP 3: Add Authorization Header
─────────────────────────────────

Tab: "Authorization"
  Type: Bearer Token
  Token: YOUR_TOKEN_HERE

(Get token from: POST /api/auth/login)


STEP 4: Add Form Data
─────────────────────

Tab: "Body"
Select: "form-data"

Add ONE field:
  Key: excel_file
  Type: File (dropdown on right)
  Value: Select customers.xlsx from your computer


STEP 5: Send
────────────

Click blue "Send" button

Should see:
{
  "message": "Bulk upload completed",
  "total_rows": 3,
  "successful": 3,
  "failed": 0,
  "results": [...]
}

✓ DONE! 3 customers created.


⚡ OPTION 2: WITH LOGOS (If You Want Them)
============================================

Only if you want to attach logos to customers.

STEP 1: Create Excel WITH Logo Column
──────────────────────────────────────

Headers:
  username | email | password | full_name | logo_file_name

Example:
  john_doe | john@test.com | pass123 | John Doe | logo_john.png
  jane_smith | jane@test.com | pass456 | Jane Smith | logo_jane.jpg


STEP 2: Postman - Same as Above, But Add Logos
───────────────────────────────────────────────

Body → form-data

Fields to add:
  
  Field 1:
    Key: excel_file
    Type: File
    Value: customers.xlsx
  
  Field 2:
    Key: logo_john.png
    Type: File
    Value: Select your logo_john.png image file
  
  Field 3:
    Key: logo_jane.jpg
    Type: File
    Value: Select your logo_jane.jpg image file

(Filenames in form fields MUST match logo_file_name in Excel)


STEP 3: Send
────────────

Click Send

Logos will be attached to customers automatically.


📋 STEP-BY-STEP POSTMAN SCREENSHOTS
===================================

Step 1: Method & URL
┌──────────────────────────────────────────┐
│ POST | http://localhost:8000/api/...     │
└──────────────────────────────────────────┘

Step 2: Headers Tab
┌──────────────────────────────────────────┐
│ Authorization | Bearer TOKEN_HERE        │
│ (Auto-set by selecting Authorization)   │
└──────────────────────────────────────────┘

Step 3: Body Tab
┌──────────────────────────────────────────┐
│ ⦿ form-data                              │
│  □ x-www-form-urlencoded                │
│                                          │
│ Key           | Value                    │
│ excel_file    | [File] customers.xlsx    │
│               |                          │
│ logo_john.png | [File] logo_john.png     │
│               | (optional)               │
└──────────────────────────────────────────┘

Step 4: Send
┌──────────────────────────────────────────┐
│ [Send ▼]                                 │
│ (Blue button, top right)                │
└──────────────────────────────────────────┘


✨ QUICK COPY-PASTE VALUES
==========================

Postman Fields to Create:

WITHOUT LOGOS:
──────────────
Key: excel_file
Type: File
Value: (Select your Excel file)


WITH LOGOS:
───────────
Key: excel_file
Type: File
Value: (Select customers.xlsx)

Key: logo_john.png
Type: File
Value: (Select logo_john.png image)

Key: logo_jane.jpg
Type: File
Value: (Select logo_jane.jpg image)

Key: logo_bob.jpg
Type: File
Value: (Select logo_bob.jpg image)


🔑 HOW TO GET TOKEN
===================

In Postman:

1. Create new request
2. Method: POST
3. URL: http://localhost:8000/api/auth/login
4. Body → raw (JSON)
   {
     "username": "admin",
     "password": "admin_password"
   }
5. Send
6. Copy "access_token" from response
7. Use in next request under Authorization tab


💡 IMPORTANT NOTES
==================

✓ Form Type: MUST be "form-data" (not JSON)
✓ Excel Field: Name MUST be exactly "excel_file"
✓ Logo Names: Must match Excel column exactly
✓ Token Format: "Bearer YOUR_TOKEN" (with space)
✓ Content-Type: Auto-set by Postman


✅ SUCCESS CHECKLIST
====================

Before clicking Send:
  ☑ Method is POST
  ☑ URL is correct
  ☑ Authorization header has valid token
  ☑ Body is form-data (not JSON)
  ☑ excel_file field has file selected
  ☑ If logos: filenames match Excel column


❌ COMMON ERRORS & FIXES
========================

Error: "excel_file is required"
  ✓ Fix: Check field name is exactly "excel_file"
  ✓ Fix: Make sure file is selected (blue upload icon)

Error: "Logo file not found"
  ✓ Fix: Logo filename in Postman must match Excel exactly
  ✓ Fix: Example: Excel has "logo_john.png" → Postman field "logo_john.png"

Error: 401 Unauthorized
  ✓ Fix: Token is invalid or expired
  ✓ Fix: Get new token from login endpoint
  ✓ Fix: Use format: "Bearer YOUR_TOKEN"

Error: Missing required fields
  ✓ Fix: Excel must have columns: username, email, password, full_name
  ✓ Fix: All rows must have values in these 4 columns


🎯 EASIEST TEST (3 MINUTES)
===========================

1. Create customers.xlsx with this data:
   
   username  | email          | password | full_name
   test1     | test1@test.com | pass123  | Test User 1
   test2     | test2@test.com | pass456  | Test User 2

2. In Postman:
   
   POST http://localhost:8000/api/customer/bulk-upload
   
   Header:
     Authorization: Bearer [YOUR_TOKEN]
   
   Body → form-data:
     excel_file: [Select customers.xlsx]
   
   Send

3. Response:
   {
     "successful": 2,
     "failed": 0,
     ...
   }

✓ Done!


📊 EXPECTED RESPONSES
====================

Success:
  Status: 200
  {
    "message": "Bulk upload completed",
    "total_rows": 2,
    "successful": 2,
    "failed": 0,
    "results": [...]
  }

Partial Success:
  Status: 200
  {
    "message": "Bulk upload completed",
    "total_rows": 2,
    "successful": 1,
    "failed": 1,
    "results": [
      {"success": true, ...},
      {"success": false, "error": "Email already exists", ...}
    ]
  }

Error:
  Status: 400/500
  {
    "detail": "Error message here"
  }


🔗 RELATED ENDPOINTS
====================

Login (get token):
  POST /api/auth/login
  Body (JSON):
    {
      "username": "admin",
      "password": "password"
    }

Get Customers:
  GET /api/customer
  Header:
    Authorization: Bearer TOKEN

Get Single Customer:
  GET /api/customer/{customer_id}
  Header:
    Authorization: Bearer TOKEN


✨ FINAL NOTES
==============

1. Test WITHOUT logos first (simpler)
2. Once working, add logos if needed
3. Always use form-data (not JSON)
4. Keep filenames simple and consistent
5. Check Postman console for detailed responses


Need help?
→ See BULK_UPLOAD_API.md for full docs
→ See API_REQUESTS.md for other methods (curl, Python, JS)
