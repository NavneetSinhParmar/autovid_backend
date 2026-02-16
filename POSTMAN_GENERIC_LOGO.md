🚀 POSTMAN - GENERIC LOGO METHOD (EASIEST!)
============================================

Updated! Now supports uploading multiple logos with a single "logo" field.


✨ METHOD 1: SIMPLE - LOGOS ASSIGNED IN ORDER
==============================================

Use a single "logo" field with multiple files.
Logos assigned to customers in the order they appear in Excel.

**STEP 1: Create Excel WITHOUT logo column**

Headers:
  username | email | password | full_name | customer_company_name

Data:
  john_doe | john@test.com | pass123 | John Doe | Doe Inc
  jane_smith | jane@test.com | pass456 | Jane Smith | Smith Corp
  bob_wilson | bob@test.com | pass789 | Bob Wilson | Wilson LLC

Save as: customers.xlsx


**STEP 2: In Postman**

Method: POST
URL: http://localhost:8000/api/customer/bulk-upload

Headers Tab:
  Authorization: Bearer YOUR_TOKEN_HERE

Body Tab:
  Select: form-data
  
  Add Fields:
  
  Field 1:
    Key: excel_file
    Type: File
    Value: [Select customers.xlsx]
  
  Field 2:
    Key: logo
    Type: File
    Value: [Select logo_john.png]
  
  Field 3:
    Key: logo
    Type: File
    Value: [Select logo_jane.jpg]
  
  Field 4:
    Key: logo
    Type: File
    Value: [Select logo_bob.jpg]


**STEP 3: Send**

Click Send button

Result:
  Row 2 (John) → Gets logo_john.png
  Row 3 (Jane) → Gets logo_jane.jpg
  Row 4 (Bob) → Gets logo_bob.jpg


✅ HOW TO ADD MULTIPLE "logo" FIELDS IN POSTMAN
================================================

1. Click in Body → form-data
2. Add first field:
   Key: logo
   Type: File (dropdown)
   Value: [Select file]
   
3. Press Tab or click the row below
   → New field appears automatically
   
4. Add more "logo" fields:
   Key: logo
   Type: File
   Value: [Select another file]
   
5. Repeat until all logos are added

(Each field has same key name "logo", different values)


📊 POSTMAN SCREENSHOT
======================

┌─────────────────────────────────────────────────────────┐
│ POST | http://localhost:8000/api/customer/bulk-upload   │
├─────────────────────────────────────────────────────────┤
│ Authorization | Headers | Body | Scripts | Settings    │
├─────────────────────────────────────────────────────────┤
│ Body: form-data                                         │
│                                                         │
│ Key          │ Type   │ Value                           │
│──────────────┼────────┼──────────────────────────────   │
│ excel_file   │ File   │ customers.xlsx                  │
│ logo         │ File   │ logo_john.png                   │
│ logo         │ File   │ logo_jane.jpg                   │
│ logo         │ File   │ logo_bob.jpg                    │
└─────────────────────────────────────────────────────────┘


🎯 STEP-BY-STEP GUIDE
====================

1️⃣ Create your Excel file with these columns:
   - username (required)
   - email (required)
   - password (required)
   - full_name (required)
   - Any optional columns (customer_company_name, city, etc.)

   DO NOT include "logo_file_name" column

   Example:
   ┌───────────┬──────────────┬──────────┬──────────────┐
   │ username  │ email        │ password │ full_name    │
   ├───────────┼──────────────┼──────────┼──────────────┤
   │ john_doe  │ john@t.com   │ pass123  │ John Doe     │
   │ jane_smith│ jane@t.com   │ pass456  │ Jane Smith   │
   │ bob_wilson│ bob@t.com    │ pass789  │ Bob Wilson   │
   └───────────┴──────────────┴──────────┴──────────────┘


2️⃣ Prepare your logo files (in same order as Excel rows):
   - logo_john.png (for row 2 - john_doe)
   - logo_jane.jpg (for row 3 - jane_smith)
   - logo_bob.jpg (for row 4 - bob_wilson)


3️⃣ Open Postman. Create new request:
   Method: POST
   URL: http://localhost:8000/api/customer/bulk-upload


4️⃣ Add Authorization Header:
   Click "Authorization" tab
   Type: Bearer Token
   Token: (paste your token)


5️⃣ Add Form Data (Body):
   Click "Body" tab
   Select "form-data" radio button
   
   Add fields:
   
   Row 1: Key=excel_file, Type=File, Value=[Select .xlsx]
   Row 2: Key=logo, Type=File, Value=[Select logo 1]
   Row 3: Key=logo, Type=File, Value=[Select logo 2]
   Row 4: Key=logo, Type=File, Value=[Select logo 3]


6️⃣ Click "Send" button

7️⃣ Check response:
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
           "customer_id": "...",
           "user_id": "..."
         }
       },
       ...
     ]
   }

✅ Done! All customers created with logos.


💡 TIPS & TRICKS
================

✓ The order matters:
  - First "logo" field → First customer (row 2)
  - Second "logo" field → Second customer (row 3)
  - etc.

✓ You can skip logos:
  - Just upload excel_file only
  - No need to upload any "logo" fields

✓ Partial logos OK:
  - 3 customers but only 2 logos?
  - First 2 get logos, last 1 doesn't

✓ Same name OK:
  - All logo files can have same name
  - Postman will handle it
  - (Just upload in correct order)

✓ File formats:
  - .png, .jpg, .jpeg, .gif, .webp
  - Any standard image format

✓ Reorder in Postman:
  - Drag and drop rows in form-data
  - Reorder before sending if needed


❌ COMMON MISTAKES & FIXES
===========================

❌ "Different number of logos"
   ✓ Fix: You have 3 customers but added 5 logos?
   ✓ Fix: Remove extra logo fields
   ✓ Fix: Or add more customers to Excel

❌ "Logos in wrong order"
   ✓ Fix: Postman rows order matters
   ✓ Fix: Drag logo fields to correct order
   ✓ Fix: excel_file should be first
   ✓ Fix: Then logo fields in same order as Excel rows

❌ "Some logos not uploaded"
   ✓ Fix: Check each "logo" field has a file selected
   ✓ Fix: (Blue upload icon should appear)

❌ "Error: excel_file is required"
   ✓ Fix: First field must be "excel_file"
   ✓ Fix: Make sure file is actually selected

❌ "401 Unauthorized"
   ✓ Fix: Token is invalid/expired
   ✓ Fix: Get new token from login endpoint
   ✓ Fix: Format: "Bearer YOUR_TOKEN"


📈 COMPARISON: OLD vs NEW METHOD
=================================

OLD Method (Still Works):
  ├─ Excel has "logo_file_name" column
  ├─ Upload form fields: logo_john.png, logo_jane.jpg
  ├─ Postman keys must match Excel exactly
  ├─ More complex but allows non-ordered mapping
  └─ Use if logos are named differently from Excel

NEW Method (Simpler):
  ├─ Excel WITHOUT "logo_file_name" column
  ├─ Upload form fields: all named "logo"
  ├─ Logos assigned in order by row
  ├─ Much simpler in Postman
  └─ Use if you want quick, simple testing


🎓 CHOICE: Which Method?
=========================

Use NEW (Generic "logo") if:
  ✓ Testing quickly
  ✓ Don't need precise logo mapping
  ✓ Just want to verify feature works
  ✓ Logos in same order as Excel rows

Use OLD (Named logos) if:
  ✓ Logos have specific names
  ✓ Non-sequential assignment needed
  ✓ Some rows skip logos but others don't
  ✓ Complex mapping required


🎯 FASTEST TEST (3 MINUTES)
============================

1. Create customers.xlsx:
   
   username | email | password | full_name
   test1 | t1@t.com | p123 | User 1
   test2 | t2@t.com | p456 | User 2

2. In Postman:
   
   POST http://localhost:8000/api/customer/bulk-upload
   
   Authorization: Bearer TOKEN
   
   Body → form-data:
     excel_file: customers.xlsx
     logo: image1.png
     logo: image2.jpg
   
   Send

Result: 2 customers created with logos!


✨ SUMMARY
===========

NEW Feature:
  ✓ Single "logo" field for multiple images
  ✓ Logos assigned in order by row
  ✓ Much simpler Postman setup
  ✓ No complex filename matching

How to Use:
  1. Create Excel (no logo column)
  2. Prepare logos (in Excel row order)
  3. Postman: Add multiple "logo" fields
  4. Send and done!

Benefits:
  ✓ Cleaner Postman setup
  ✓ Easier to understand
  ✓ Less error-prone
  ✓ Still supports named logos if needed


🚀 READY TO TEST?
=================

1. Create Excel file with 3 customers
2. Prepare 3 logo images
3. Open Postman
4. Follow STEP 1-7 above
5. Click Send

That's it! Let me know if you hit any issues.
