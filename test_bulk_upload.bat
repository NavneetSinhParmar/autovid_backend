@echo off
REM ============================================================================
REM BULK CUSTOMER UPLOAD - TEST SCRIPT
REM ============================================================================
REM This script tests the bulk customer upload API
REM 
REM Prerequisites:
REM 1. Excel file: sample_customers.xlsx (or modified filename below)
REM 2. Logo files: Logo files in same directory (optional)
REM 3. Bearer Token: Get from login endpoint
REM ============================================================================

echo.
echo ============================================================================
echo  BULK CUSTOMER UPLOAD - WINDOWS TEST SCRIPT
echo ============================================================================
echo.

REM Ask for token
set /p TOKEN="Enter your Bearer token: "

if "%TOKEN%"=="" (
    echo Error: Token is required
    pause
    exit /b 1
)

echo.
echo Uploading customers...
echo.

REM Build curl command dynamically
REM Adjust filenames as needed
curl -X POST "http://localhost:8000/api/customer/bulk-upload" ^
  -H "Authorization: Bearer %TOKEN%" ^
  -F "excel_file=@sample_customers.xlsx" ^
  -F "logo_john.png=@logo_john.png" ^
  -F "logo_jane.jpg=@logo_jane.jpg"

echo.
echo.
echo ============================================================================
echo  Upload Complete - Check response above
echo ============================================================================
pause
