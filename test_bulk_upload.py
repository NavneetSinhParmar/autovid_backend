"""
Test script for bulk customer upload API
"""
import requests
import sys
from pathlib import Path
from openpyxl import Workbook

# ============================================================
# 1️⃣ CREATE SAMPLE EXCEL FILE
# ============================================================
def create_sample_excel():
    """Create sample Excel with customer data"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Customers"
    
    # Headers
    headers = [
        "username",
        "email", 
        "password",
        "full_name",
        "customer_company_name",
        "city",
        "phone_number",
        "telephone_number",
        "address",
        "logo_file_name"
    ]
    ws.append(headers)
    
    # Sample data (3 customers)
    data = [
        [
            "john_doe",
            "john@example.com",
            "password123",
            "John Doe",
            "Doe Enterprises",
            "New York",
            "+1-555-0001",
            "+1-555-0011",
            "123 Main St, NY 10001",
            "logo_john.png"  # References logo file
        ],
        [
            "jane_smith",
            "jane@example.com",
            "password456",
            "Jane Smith",
            "Smith Industries",
            "Los Angeles",
            "+1-555-0002",
            "+1-555-0022",
            "456 Oak Ave, LA 90001",
            "logo_jane.jpg"  # References logo file
        ],
        [
            "bob_wilson",
            "bob@example.com",
            "password789",
            "Bob Wilson",
            "Wilson Corp",
            "Chicago",
            "+1-555-0003",
            "+1-555-0033",
            "789 Pine Rd, Chicago 60601",
            None  # No logo
        ],
    ]
    
    for row in data:
        ws.append(row)
    
    # Save
    file_path = "sample_customers.xlsx"
    wb.save(file_path)
    print(f"✓ Created: {file_path}")
    return file_path


# ============================================================
# 2️⃣ TEST API WITH CURL
# ============================================================
def test_with_curl():
    """Print cURL commands for testing"""
    print("\n" + "="*80)
    print("📋 CURL COMMAND FOR TESTING")
    print("="*80)
    
    command = """
curl -X POST "http://localhost:8000/api/customer/bulk-upload" \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -F "excel_file=@sample_customers.xlsx" \\
  -F "logo_john.png=@path/to/logo_john.png" \\
  -F "logo_jane.jpg=@path/to/logo_jane.jpg"
    """
    print(command)


# ============================================================
# 3️⃣ TEST API WITH PYTHON REQUESTS
# ============================================================
def test_with_requests(token: str, excel_path: str, logo_paths: dict):
    """
    Test bulk upload API with Python requests
    
    Args:
        token: Bearer token for authentication
        excel_path: Path to Excel file
        logo_paths: Dict mapping logo filename -> file path
                   e.g., {"logo_john.png": "path/to/logo_john.png"}
    """
    url = "http://localhost:8000/api/customer/bulk-upload"
    headers = {"Authorization": f"Bearer {token}"}
    
    # Prepare multipart data
    files = [
        ("excel_file", (Path(excel_path).name, open(excel_path, "rb"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    ]
    
    # Add logo files
    for logo_name, logo_path in logo_paths.items():
        if Path(logo_path).exists():
            files.append((f"logo_{Path(logo_path).stem}", (logo_name, open(logo_path, "rb"), "image/png")))
    
    try:
        response = requests.post(url, headers=headers, files=files)
        print("\n" + "="*80)
        print("📊 API RESPONSE")
        print("="*80)
        print(f"Status Code: {response.status_code}")
        print(f"Response:\n{response.json()}")
        
        return response.json()
    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    finally:
        # Close files
        for _, file_tuple in files[1:]:
            if hasattr(file_tuple[1], 'close'):
                file_tuple[1].close()


# ============================================================
# 4️⃣ MAIN TEST FLOW
# ============================================================
def main():
    print("🚀 BULK CUSTOMER UPLOAD TEST")
    print("="*80)
    
    # Step 1: Create sample Excel
    excel_file = create_sample_excel()
    
    # Step 2: Show cURL command
    test_with_curl()
    
    # Step 3: Ask for token
    print("\n" + "="*80)
    print("🔑 AUTHENTICATION")
    print("="*80)
    token = input("Enter your Bearer token (or press Enter to skip API test): ").strip()
    
    if token:
        # Step 4: Test API
        print("\n" + "="*80)
        print("🧪 TESTING API")
        print("="*80)
        
        # Define logo files (in real scenario, these would be actual image files)
        logo_paths = {
            "logo_john.png": "sample_logo.png",  # Replace with actual image path
            "logo_jane.jpg": "sample_logo.jpg",  # Replace with actual image path
        }
        
        # Only include logos that exist
        existing_logos = {k: v for k, v in logo_paths.items() if Path(v).exists()}
        
        if not existing_logos:
            print("⚠️  No logo files found. Upload will proceed without logos.")
            print("   Place image files as: sample_logo.png, sample_logo.jpg")
        
        result = test_with_requests(token, excel_file, existing_logos)
        
        if result and result.get("successful", 0) > 0:
            print("\n✅ Test completed successfully!")
        else:
            print("\n❌ Test completed with errors")
    else:
        print("\n⏭️  Skipping API test. You can test manually using the cURL command above.")
    
    print("\n" + "="*80)
    print("📝 EXCEL FILE STRUCTURE")
    print("="*80)
    print("""
Required columns:
  - username (unique, alphanumeric)
  - email (valid email format)
  - password (at least 8 chars recommended)
  - full_name (customer's full name)

Optional columns:
  - customer_company_name
  - city
  - phone_number
  - telephone_number  
  - address
  - logo_file_name (filename of uploaded logo)
    """)
    
    print("\n✓ Test setup complete!")
    print(f"✓ Excel file created: {excel_file}")


if __name__ == "__main__":
    main()
