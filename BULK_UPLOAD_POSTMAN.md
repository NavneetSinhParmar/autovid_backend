# Bulk Upload Customers - Postman Test Guide

## Endpoint
```
POST /customer/bulk-upload
```

## Headers
- `Authorization`: Bearer \<your_token\>
- `Content-Type`: (leave empty – Postman sets `multipart/form-data` automatically)

## Form-data (Body → form-data)

| Key | Type | Value |
|-----|------|-------|
| `excel_file` or `csv_file` | File | Select your CSV or Excel file |
| `logo` or `logo_files` | File | Select logo file(s). Filename must match `logo_url` column in CSV. |
| `linked_company_id` | Text | (Superadmin only) Company ObjectId to link all customers |

## CSV Format Example
Save as `customer_dummy_data.csv`:
```csv
customer_company_name,full_name,username,email,password,city,phone_number,telephone_number,address,status,logo_url
Customer Company 1,Customer Name 1,customer1,customer1@example.com,Abc@1234,Mumbai,9000000001,8000000001,"1 Example Street, City 1, India",active,customer_logo1.png
Customer Company 2,Customer Name 2,customer2,customer2@example.com,Abc@1234,Delhi,9000000002,,Address 2,active,customer_logo1.png
```

**Required columns:** `username`, `email`, `password`, `full_name`

**Logo:** Use `logo_url` or `logo_file_name` column. Value = exact filename (e.g. `customer_logo1.png`).  
If multiple rows use same name, upload one file and it will be reused.

## Steps in Postman

1. Method: **POST**
2. URL: `http://localhost:8000/customer/bulk-upload`
3. **Body** → **form-data**
4. Add row:
   - Key: `csv_file` (or `excel_file`)
   - Type: **File**
   - Value: Choose your CSV file
5. Add row:
   - Key: `logo` (or `logo_files`)
   - Type: **File**
   - Value: Choose `customer_logo1.png` (name must match CSV)
6. (Superadmin) Add row:
   - Key: `linked_company_id`
   - Type: **Text**
   - Value: Your company ObjectId
7. Send request

## cURL Example
```bash
curl -X POST "http://localhost:8000/customer/bulk-upload" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "csv_file=@customer_dummy_data.csv" \
  -F "logo=@customer_logo1.png" \
  -F "linked_company_id=691c6d686ad325a3e62e7e75"
```
(Replace YOUR_TOKEN and linked_company_id. Omit linked_company_id if logged in as company user.)
