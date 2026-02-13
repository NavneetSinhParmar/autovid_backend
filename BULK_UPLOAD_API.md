# 📊 BULK CUSTOMER UPLOAD - API DOCUMENTATION

## Overview

The bulk customer upload API allows you to create multiple customers at once by uploading an Excel file with optional logo files.

---

## 🔗 API ENDPOINT

```
POST /api/customer/bulk-upload
```

**Authentication Required:** Yes (Bearer Token)  
**Roles Allowed:** `superadmin`, `company`

---

## 📋 Excel File Structure

### Required Columns (Headers)

```
username          - Unique username (no spaces)
email             - Valid email address
password          - Account password
full_name         - Customer's full name
```

### Optional Columns

```
customer_company_name  - Company name associated with customer
city                   - City
phone_number           - Primary phone
telephone_number       - Secondary phone
address                - Street address
logo_file_name         - Name of logo file (must match uploaded filename)
```

### Example Excel Structure

```
| username   | email              | password    | full_name   | customer_company_name | city          | phone_number  | logo_file_name  |
|------------|-------------------|-------------|-------------|----------------------|---------------|---------------|-----------------|
| john_doe   | john@example.com  | pass123!   | John Doe    | Doe Enterprises     | New York      | +1-555-0001   | logo_john.png   |
| jane_smith | jane@example.com  | pass456!   | Jane Smith  | Smith Industries    | Los Angeles   | +1-555-0002   | logo_jane.jpg   |
| bob_wilson | bob@example.com   | pass789!   | Bob Wilson  | Wilson Corp         | Chicago       | +1-555-0003   | (empty)         |
```

---

## 🖼️ Logo Files Mapping

- **Excel Column:** `logo_file_name` - Contains the exact filename of the logo
- **Upload:** Send logo files as multipart form fields
- **Naming:** Must match exactly (case-sensitive on Linux, case-insensitive on Windows)

### Example Mapping

```
Excel row has: logo_file_name = "logo_john.png"
Upload file: logo_john.png (same name)
→ Logo automatically associated with that customer
```

---

## 🧪 Testing Guide

### Method 1: Using cURL (Command Line)

```bash
# Basic single customer with logo
curl -X POST "http://localhost:8000/api/customer/bulk-upload" \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -F "excel_file=@sample_customers.xlsx" \
  -F "logo_john.png=@path/to/logo_john.png" \
  -F "logo_jane.jpg=@path/to/logo_jane.jpg"
```

**Replace:**

- `YOUR_TOKEN_HERE` - Your authentication Bearer token
- `sample_customers.xlsx` - Path to your Excel file
- `path/to/logo_john.png` - Path to logo file

### Method 2: Using Python Script

```bash
# Run the test script
python test_bulk_upload.py
```

**This script will:**

1. ✓ Create a sample Excel file (`sample_customers.xlsx`)
2. ✓ Show cURL command for testing
3. ✓ Test the API if you provide a token
4. ✓ Display results and summary

### Method 3: Using Postman

1. **Create New Request**
   - Method: `POST`
   - URL: `http://localhost:8000/api/customer/bulk-upload`

2. **Headers**
   - Key: `Authorization`
   - Value: `Bearer YOUR_TOKEN_HERE`

3. **Body → form-data**
   - Key: `excel_file` | Type: `File` | Value: Select Excel file
   - Key: `logo_john.png` | Type: `File` | Value: Select logo image
   - Key: `logo_jane.jpg` | Type: `File` | Value: Select logo image
   - (Add more logo fields as needed, using exact filenames from Excel)

4. **Send** and view response

---

## 📊 API Response Format

### Success Response (200)

```json
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
    {
      "success": true,
      "row": 3,
      "data": {
        "message": "Customer created successfully",
        "customer_id": "507f1f77bcf86cd799439013",
        "user_id": "507f1f77bcf86cd799439014"
      }
    },
    {
      "success": true,
      "row": 4,
      "data": {
        "message": "Customer created successfully",
        "customer_id": "507f1f77bcf86cd799439015",
        "user_id": "507f1f77bcf86cd799439016"
      }
    }
  ]
}
```

### Partial Failure Response (200)

```json
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
    {
      "success": true,
      "row": 4,
      "data": { ... }
    }
  ]
}
```

### Error Response (400/500)

```json
{
  "detail": "excel_file is required"
}
```

---

## 🔍 Response Fields Explained

| Field        | Type   | Description                    |
| ------------ | ------ | ------------------------------ |
| `message`    | string | Overall operation status       |
| `total_rows` | number | Total rows processed           |
| `successful` | number | Successfully created customers |
| `failed`     | number | Failed customer creations      |
| `results`    | array  | Details for each row           |

### Result Object Fields

| Field     | Type    | Description                                         |
| --------- | ------- | --------------------------------------------------- |
| `success` | boolean | Whether row processed successfully                  |
| `row`     | number  | Excel row number (1-indexed from header)            |
| `data`    | object  | Customer ID/User ID if successful, or error details |
| `error`   | string  | Error message if failed                             |

---

## ✅ Validation Rules

### Required Fields

- ✓ `username` - Must be unique, no spaces
- ✓ `email` - Must be valid email format, unique
- ✓ `password` - Any length (min 8 recommended)
- ✓ `full_name` - Cannot be empty

### Optional Fields

- Logo will only be attached if `logo_file_name` matches uploaded file
- Missing optional fields are ok (will be omitted from customer record)

### Error Scenarios

```
❌ Missing required field
❌ Email already exists
❌ Username already exists
❌ Logo file not found in upload
❌ Invalid Excel format
```

---

## 🚀 Quick Start Example

**Step 1: Create Excel File**

```
Download or create Excel with headers and data as shown above
```

**Step 2: Get Authentication Token**

```bash
# Login to get token (your login endpoint)
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"password"}'
# Response: {"access_token": "eyJ0eXAi..."}
```

**Step 3: Upload**

```bash
curl -X POST "http://localhost:8000/api/customer/bulk-upload" \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -F "excel_file=@customers.xlsx" \
  -F "logo_john.png=@john_logo.png"
```

**Step 4: Check Response**

- Look for `successful` count
- Check `results` array for any failures
- Review error messages in failed rows

---

## 💡 Pro Tips

1. **Excel Row Numbering:** Row 1 = Headers, Row 2 = First customer, etc.
   - Example: If customer fails on "row: 3", it's the second customer

2. **Logo Matching:** Use simple, consistent names
   - Good: `logo_john.png`, `logo_jane.jpg`
   - Bad: `John's Logo (2024).png`, `LOGO - Final.jpg`

3. **Batch Size:** Test with 5-10 customers first
   - No hard limit, but monitor performance
   - Larger batches = longer processing time

4. **Error Recovery:** Fix errors in Excel and re-upload
   - Duplicates (email/username) will fail
   - Remove processed customers to avoid duplicates

5. **Logging:** Check server logs for detailed error info
   - Helps debug file path and encoding issues

---

## 🔧 Troubleshooting

### Issue: "excel_file is required"

**Solution:** Make sure form field name is exactly `excel_file`

### Issue: "Logo file not found"

**Solution:** Verify filename in Excel matches uploaded file name (case-sensitive on Linux)

### Issue: "Email already exists"

**Solution:** This customer already exists in database. Update username/email and retry.

### Issue: "Missing required fields"

**Solution:** Ensure Excel has all required columns with non-empty values

### Issue: Invalid Content-Type

**Solution:** Make sure request is `multipart/form-data`, not JSON

---

## 📈 Performance Notes

- **For 10-50 customers:** < 5 seconds
- **For 50-200 customers:** 5-30 seconds
- **For 200+ customers:** Consider splitting into multiple uploads

---

## 🔐 Security Notes

- ✓ Bearer token required for authentication
- ✓ Only `superadmin` and `company` roles allowed
- ✓ Passwords are hashed before storage
- ✓ Uploaded logos stored securely
- ✓ All data validated before insertion

---

Created: 2026-02-11  
Last Updated: 2026-02-11
