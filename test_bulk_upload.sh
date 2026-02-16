#!/bin/bash

################################################################################
# BULK CUSTOMER UPLOAD - UNIX/LINUX TEST SCRIPT
################################################################################
# This script tests the bulk customer upload API
# 
# Prerequisites:
# 1. Excel file: sample_customers.xlsx
# 2. Logo files in current directory (optional)
# 3. Bearer Token: Get from login endpoint
################################################################################

echo ""
echo "=============================================================================="
echo "  BULK CUSTOMER UPLOAD - UNIX/LINUX TEST SCRIPT"
echo "=============================================================================="
echo ""

# Ask for token
read -p "Enter your Bearer token: " TOKEN

if [ -z "$TOKEN" ]; then
    echo "Error: Token is required"
    exit 1
fi

# Check if Excel file exists
if [ ! -f "sample_customers.xlsx" ]; then
    echo "⚠️  Error: sample_customers.xlsx not found"
    echo "   Run: python test_bulk_upload.py"
    exit 1
fi

echo ""
echo "📤 Uploading customers from Excel file..."
echo ""

# Build curl command dynamically with logo files
# Find all logo files and add them to curl
LOGO_FILES=""
for file in logo_*.* *.png *.jpg *.jpeg; do
    if [ -f "$file" ] && [[ "$file" =~ ^logo ]]; then
        LOGO_FILES="$LOGO_FILES -F \"$file=@$file\""
    fi
done

# Execute curl
eval "curl -X POST 'http://localhost:8000/api/customer/bulk-upload' \
  -H 'Authorization: Bearer $TOKEN' \
  -F 'excel_file=@sample_customers.xlsx' \
  $LOGO_FILES"

echo ""
echo ""
echo "=============================================================================="
echo "  Upload Complete - Check response above"
echo "=============================================================================="
