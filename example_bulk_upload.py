"""
COMPLETE EXAMPLE: Bulk Customer Upload with Excel + Logos

This example shows everything you need to know about using the bulk upload API
"""

# ============================================================================
# STEP 1: CREATE SAMPLE DATA
# ============================================================================

from openpyxl import Workbook
from pathlib import Path

def create_example_excel():
    """Create example Excel file with customer data"""
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Customers"
    
    # Headers (required + optional)
    headers = [
        "username",                  # ✓ REQUIRED
        "email",                     # ✓ REQUIRED
        "password",                  # ✓ REQUIRED
        "full_name",                 # ✓ REQUIRED
        "customer_company_name",     # optional
        "city",                      # optional
        "phone_number",              # optional
        "telephone_number",          # optional
        "address",                   # optional
        "logo_file_name",            # optional - must match uploaded file
    ]
    ws.append(headers)
    
    # Example customers (with logo references)
    customers = [
        # Row 2: Complete data with logo
        {
            "username": "acme_corp",
            "email": "contact@acme.com",
            "password": "SecurePass123!",
            "full_name": "ACME Corporation",
            "customer_company_name": "ACME Corp",
            "city": "New York",
            "phone_number": "+1-555-0001",
            "telephone_number": "+1-555-0011",
            "address": "123 Broadway, NY 10001",
            "logo_file_name": "logo_acme.png",  # ← Will match uploaded logo_acme.png
        },
        
        # Row 3: Partial data with logo
        {
            "username": "tech_solutions",
            "email": "info@techsol.com",
            "password": "TechPass456!",
            "full_name": "Tech Solutions Inc",
            "customer_company_name": "TechSol",
            "city": "San Francisco",
            "phone_number": "+1-555-0002",
            "telephone_number": "",  # Empty is OK for optional fields
            "address": "456 Market St, SF 94103",
            "logo_file_name": "logo_techsol.jpg",  # ← Will match uploaded logo_techsol.jpg
        },
        
        # Row 4: Minimal data (no logo)
        {
            "username": "startup_xyz",
            "email": "hello@startupxyz.io",
            "password": "StartupPass789!",
            "full_name": "Startup XYZ",
            "customer_company_name": "StartupXYZ",
            "city": "Austin",
            "phone_number": "+1-555-0003",
            "telephone_number": "",
            "address": "789 Congress Ave, Austin TX 78701",
            "logo_file_name": "",  # No logo for this customer
        },
    ]
    
    # Add rows
    for customer in customers:
        row = [customer.get(h, "") for h in headers]
        ws.append(row)
    
    # Adjust column widths
    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 25
    ws.column_dimensions['D'].width = 20
    ws.column_dimensions['J'].width = 20
    
    # Save
    path = "example_customers.xlsx"
    wb.save(path)
    print(f"✓ Created Excel file: {path}")
    return path


# ============================================================================
# STEP 2: TEST WITH PYTHON REQUESTS
# ============================================================================

import requests
from typing import Dict, List

def upload_customers(
    token: str,
    excel_path: str,
    logo_files: Dict[str, str] = None
) -> Dict:
    """
    Upload customers to API
    
    Args:
        token: Bearer token for authentication
        excel_path: Path to Excel file
        logo_files: Dict mapping filename -> file path
                   Example: {"logo_acme.png": "path/to/logo_acme.png"}
    
    Returns:
        API response as dict
    """
    
    url = "http://localhost:8000/api/customer/bulk-upload"
    
    # Prepare headers
    headers = {"Authorization": f"Bearer {token}"}
    
    # Prepare files for upload
    files = [
        ("excel_file", (
            Path(excel_path).name,
            open(excel_path, "rb"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ))
    ]
    
    # Add logo files
    if logo_files:
        for filename, filepath in logo_files.items():
            if Path(filepath).exists():
                files.append((f"logo_{Path(filepath).stem}", (
                    filename,
                    open(filepath, "rb"),
                    f"image/{Path(filepath).suffix[1:]}"  # Detect mime type
                )))
                print(f"  ✓ Added logo: {filename}")
            else:
                print(f"  ⚠️  Warning: Logo not found: {filepath}")
    
    try:
        # Send request
        print("\n📤 Sending request to API...")
        response = requests.post(url, headers=headers, files=files, timeout=30)
        
        # Parse response
        result = response.json()
        
        # Close files
        for _, file_info in files:
            if hasattr(file_info[1], 'close'):
                file_info[1].close()
        
        return response.status_code, result
        
    except requests.exceptions.ConnectionError:
        print("❌ Error: Cannot connect to API")
        print("   Make sure server is running: uvicorn app.main:app --reload")
        return None, None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None, None


def print_results(status_code: int, result: Dict):
    """Pretty print API response"""
    
    print("\n" + "="*80)
    print("📊 API RESPONSE")
    print("="*80)
    print(f"\nStatus Code: {status_code}")
    
    if result:
        print(f"\n{result.get('message')}")
        print(f"  Total rows: {result.get('total_rows')}")
        print(f"  ✓ Successful: {result.get('successful')}")
        print(f"  ✗ Failed: {result.get('failed')}")
        
        # Show details
        print("\nDetails:")
        for r in result.get("results", []):
            if r.get("success"):
                cid = r.get("data", {}).get("customer_id", "?")
                print(f"  ✓ Row {r['row']}: Customer created ({cid})")
            else:
                print(f"  ✗ Row {r['row']}: {r.get('error', 'Unknown error')}")


# ============================================================================
# STEP 3: MAIN EXECUTION
# ============================================================================

def main():
    """Main test flow"""
    
    print("\n" + "="*80)
    print("🚀 BULK CUSTOMER UPLOAD - COMPLETE EXAMPLE")
    print("="*80)
    
    # Step 1: Create Excel
    print("\n1️⃣  Creating sample Excel file...")
    excel_file = create_example_excel()
    
    # Step 2: Get authentication token
    print("\n2️⃣  Authentication")
    print("-" * 80)
    token = input("Enter your Bearer token: ").strip()
    
    if not token:
        print("⚠️  Token required for API test")
        print("\nTo get token, login first:")
        print("  curl -X POST 'http://localhost:8000/api/auth/login' \\")
        print("    -H 'Content-Type: application/json' \\")
        print("    -d '{\"username\":\"admin\",\"password\":\"password\"}'")
        return
    
    # Step 3: Prepare logo files
    print("\n3️⃣  Logo files (optional)")
    print("-" * 80)
    
    logo_files = {}
    
    # Map Excel "logo_file_name" to actual file paths
    logo_mapping = {
        "logo_acme.png": "path/to/actual/logo_acme.png",      # ← Update path
        "logo_techsol.jpg": "path/to/actual/logo_techsol.jpg", # ← Update path
    }
    
    for recommended_name, actual_path in logo_mapping.items():
        if Path(actual_path).exists():
            logo_files[recommended_name] = actual_path
        else:
            print(f"  ⚠️  Logo not found: {actual_path}")
    
    if not logo_files:
        print("  ℹ️  No logo files found. Upload will proceed without logos.")
    
    # Step 4: Upload
    print("\n4️⃣  Uploading to API...")
    print("-" * 80)
    
    status_code, result = upload_customers(token, excel_file, logo_files)
    
    # Step 5: Display results
    if status_code:
        print_results(status_code, result)
        
        if status_code == 200:
            print("\n✅ Upload completed!")
            if result.get("failed", 0) > 0:
                print(f"   ⚠️  {result.get('failed')} customers had errors")
        else:
            print("\n❌ API returned error status")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    main()


# ============================================================================
# QUICK REFERENCE
# ============================================================================
"""
EXCEL FILE STRUCTURE:
├─ Header row (Row 1): Column names
├─ Data rows (Row 2+): Customer data
└─ Each row must have: username, email, password, full_name

LOGO FILE MAPPING:
├─ Excel column: "logo_file_name" = "logo_acme.png"
├─ Upload form: File named "logo_acme.png"
└─ Result: Logo automatically linked to customer

API ENDPOINT:
POST /api/customer/bulk-upload
Authorization: Bearer {token}
Content-Type: multipart/form-data

FORM FIELDS:
├─ excel_file: The Excel workbook
├─ logo_acme.png: Logo image file
├─ logo_techsol.jpg: Logo image file
└─ (repeat for each logo)

SUCCESS RESPONSE:
{
  "message": "Bulk upload completed",
  "total_rows": 3,
  "successful": 3,
  "failed": 0,
  "results": [...]
}

ERROR RESPONSE:
{
  "detail": "Error message here"
}
"""
