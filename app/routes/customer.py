from annotated_types import doc
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
from typing import Union, List, Dict, Any
import io
import csv
from openpyxl import load_workbook

from app.db.connection import db
from app.utils.auth import require_roles, hash_password
from app.models.customer_model import CustomerCreate, CustomerOut
from fastapi import Request, UploadFile, File, Form
from app.services.storage import save_customer_file
from app.services.url import build_media_url
from fastapi import Request

router = APIRouter(prefix="/customer", tags=["Customer Management"])
print("Customer router loaded")

# --------------------------------------------------------
# 🟢 BULK UPLOAD: Excel + Logo Files
# --------------------------------------------------------
@router.post("/bulk-upload")
async def bulk_upload_customers(
    request: Request,
    user=Depends(require_roles("superadmin", "company")),
):
    """
    Upload customers from Excel or CSV file with optional logo files.
    
    Supported file formats: .xlsx, .xls, .csv
    
    CSV/Excel columns (headers):
    - username (required)
    - email (required)
    - password (required)
    - full_name (required)
    - customer_company_name, city, phone_number, telephone_number, address, status
    - logo_url OR logo_file_name (optional): filename like "customer_logo1.png" - must match uploaded logo filename
    
    Form data (multipart/form-data):
    - excel_file OR csv_file: Excel or CSV data file
    - logo OR logo_files: One or more logo files. Filename must match logo_url/logo_file_name in CSV.
      Same filename in multiple rows = one logo file reused for all.
    
    Example CSV:
    customer_company_name,full_name,username,email,password,city,phone_number,telephone_number,address,status,logo_url
    Company 1,Name 1,customer1,c1@ex.com,Abc@1234,Mumbai,9000000001,,Address 1,active,customer_logo1.png
    """
    try:
        form = await request.form()
        excel_file = form.get("excel_file") or form.get("csv_file")
        
        if not excel_file:
            raise HTTPException(status_code=400, detail="excel_file or csv_file is required")
        
        filename = excel_file.filename.lower()
        is_csv = filename.endswith('.csv')
        is_excel = filename.endswith(('.xlsx', '.xls'))
        
        if not (is_csv or is_excel):
            raise HTTPException(status_code=400, detail="File must be Excel format (.xlsx, .xls) or CSV (.csv)")
        
        # Read file content
        try:
            file_content = await excel_file.read()
            if not file_content:
                raise HTTPException(status_code=400, detail="File is empty")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")
        
        # Parse file based on type
        headers = []
        rows_data = []
        
        if is_csv:
            # Parse CSV file
            try:
                text_content = file_content.decode('utf-8')
                reader = csv.DictReader(io.StringIO(text_content))
                headers = reader.fieldnames or []
                rows_data = list(reader)
                print(f"📄 CSV headers: {headers}")
            except Exception as e:
                error_msg = str(e)
                print(f"❌ CSV read error: {error_msg}")
                raise HTTPException(status_code=400, detail=f"Failed to parse CSV file: {error_msg}")
        else:
            # Parse Excel file
            try:
                workbook = load_workbook(io.BytesIO(file_content))
                worksheet = workbook.active
                
                # Extract headers from first row
                for cell in worksheet[1]:
                    headers.append(cell.value)
                
                # Extract data rows
                for row in worksheet.iter_rows(min_row=2, values_only=True):
                    if not any(row):  # Skip empty rows
                        continue
                    row_dict = {}
                    for idx, header in enumerate(headers):
                        if header is not None and idx < len(row):
                            row_dict[header] = row[idx]
                    rows_data.append(row_dict)
                
                print(f"📄 Excel headers: {headers}")
            except Exception as e:
                error_msg = str(e)
                print(f"❌ Excel read error: {error_msg}")
                if "not a zip file" in error_msg:
                    raise HTTPException(status_code=400, detail="Invalid Excel file. Please upload a valid .xlsx or .xls file")
                else:
                    raise HTTPException(status_code=400, detail=f"Failed to read Excel file: {error_msg}")
        
        if not headers or headers[0] is None:
            raise HTTPException(status_code=400, detail="File must have headers in first row")
        
        # Collect logo files: map filename -> UploadFile
        # Supports: logo, logo_files (multiple), logo_xxx (named)
        logo_files_map = {}
        for key in ["logo", "logo_files"]:
            try:
                files = form.getlist(key)
                for f in files:
                    if isinstance(f, UploadFile) and f.filename:
                        logo_files_map[f.filename] = f
            except Exception:
                pass
        for key in form.keys():
            if key.startswith("logo_") or key == "logo":
                f = form.get(key)
                if isinstance(f, UploadFile) and f.filename:
                    logo_files_map[f.filename] = f
        print(f"🖼️  Logo files: {list(logo_files_map.keys())}")

        # Get company_id for storage (company user) or linked_company_id (superadmin)
        company_id = None
        if user["role"] == "company":
            company = await db.companies.find_one({"user_id": str(user["_id"])})
            if company:
                company_id = str(company["_id"])
        elif user["role"] == "superadmin":
            company_id = form.get("linked_company_id")
            if not company_id:
                raise HTTPException(status_code=400, detail="linked_company_id required in form for superadmin bulk upload")

        # Cache: logo_filename -> saved path (reuse for same logo in multiple rows)
        logo_path_cache = {}
        
        # Process rows
        results = []
        row_num = 2
        generic_logo_idx = 0  # Track which generic logo to use next
        
        for row_data in rows_data:
            # row_data is already a dict from CSV or Excel parsing
            # Skip empty rows
            if not any(row_data.get(h) for h in ["username", "email", "password", "full_name"]):
                print(f"⏭️  Skipping empty row {row_num}")
                row_num += 1
                continue
            
            print(f"\n📍 Processing row {row_num}: {row_data.get('full_name')}")
            
            # Validate required fields
            required_fields = ["username", "email", "password", "full_name"]
            missing = [f for f in required_fields if not row_data.get(f)]
            if missing:
                results.append({
                    "success": False,
                    "row": row_num,
                    "error": f"Missing required fields: {', '.join(missing)}",
                    "data": row_data
                })
                row_num += 1
                continue
            
            try:
                # Logo: get filename from logo_url OR logo_file_name column
                logo_filename = (
                    str(row_data.get("logo_url", "")).strip()
                    or str(row_data.get("logo_file_name", "")).strip()
                    or str(row_data.get("logo", "")).strip()
                )
                logo_url = None
                if logo_filename:
                    if logo_filename in logo_path_cache:
                        logo_url = logo_path_cache[logo_filename]
                        print(f"   ✓ Reusing cached logo: {logo_filename}")
                        matched_file = None
                        for fname, fobj in logo_files_map.items():
                            if fname.lower().strip() == logo_filename.lower().strip():
                                matched_file = fobj
                                break

                        if matched_file:
                            path, _ = await save_upload_file(matched_file, company_id)
                        logo_file = logo_files_map[logo_filename]
                        if company_id:
                            from app.services.storage import save_upload_file
                            path, _ = await save_upload_file(logo_file, company_id)
                            logo_url = f"./media/{path}"
                            logo_path_cache[logo_filename] = logo_url
                            print(f"   ✓ Logo saved: {logo_url}")
                        else:
                            print(f"   ⚠️  No company_id, skipping logo")
                    else:
                        print(f"   ⚠️  Logo file not uploaded: {logo_filename}")
                
                # Prepare customer data
                customer_data = {
                    "username": row_data.get("username"),
                    "email": row_data.get("email"),
                    "password": row_data.get("password"),
                    "full_name": row_data.get("full_name"),
                    "customer_company_name": row_data.get("customer_company_name"),
                    "city": row_data.get("city"),
                    "phone_number": row_data.get("phone_number"),
                    "telephone_number": row_data.get("telephone_number"),
                    "address": row_data.get("address"),
                    "linked_company_id": company_id,
                }
                
                if logo_url:
                    customer_data["logo_url"] = logo_url
                
                # Create customer
                result = await create_single_customer(customer_data, user)
                results.append({
                    "success": True,
                    "row": row_num,
                    "data": result
                })
                print(f"   ✓ Customer created: {result['customer_id']}")
                
            except HTTPException as e:
                results.append({
                    "success": False,
                    "row": row_num,
                    "error": e.detail,
                    "data": row_data
                })
                print(f"   ✗ Error: {e.detail}")
            except Exception as e:
                results.append({
                    "success": False,
                    "row": row_num,
                    "error": str(e),
                    "data": row_data
                })
                print(f"   ✗ Unexpected error: {str(e)}")
            
            row_num += 1
        
        # Summary
        successful = sum(1 for r in results if r.get("success"))
        failed = len(results) - successful
        
        return {
            "message": "Bulk upload completed",
            "total_rows": len(results),
            "successful": successful,
            "failed": failed,
            "results": results
        }
        
    except Exception as e:
        print(f"❌ Bulk upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Bulk upload failed: {str(e)}")


def to_oid(value: str):
    try:
        return ObjectId(value)
    except:
        raise HTTPException(status_code=400, detail=f"Invalid ObjectId: {value}")

# --------------------------------------------------------
# 🟢 Helper: Validate and Create Customer Document
# --------------------------------------------------------
async def create_single_customer(data: Dict[str, Any], user: Dict):
    print("Creating single customer with data:", data)

    # 1️⃣ If logged user is COMPANY → auto set linked_company_id
    if user["role"] == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})

        if not company:
            raise HTTPException(status_code=404,
                                detail="Company record not found for this user")
        
        data["linked_company_id"] = str(company["_id"])  # override automatically

    # 2️⃣ SUPERADMIN must give linked_company_id
    elif user["role"] == "superadmin":
        if "linked_company_id" not in data:
            raise HTTPException(status_code=400,
                                detail="linked_company_id is required for superadmin")

    # 3️⃣ Check Duplicate User
    if await db.users.find_one({"username": data["username"]}):
        raise HTTPException(status_code=400, detail="Username already exists")

    if await db.users.find_one({"email": data["email"]}):
        raise HTTPException(status_code=400, detail="Email already exists")

    # 4️⃣ Create User Record
    user_doc = {
        "username": data["username"],
        "email": data["email"],
        "password": hash_password(data["password"]),
        "role": "customer",
        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    inserted_user = await db.users.insert_one(user_doc)
    user_id = str(inserted_user.inserted_id)

    # 5️⃣ Prepare Customer Record
    customer_doc = {
        "customer_company_name": data.get("customer_company_name"),
        "full_name": data["full_name"],
        "logo_url": data.get("logo_url"),
        "city": data.get("city"),
        "phone_number": data.get("phone_number"),
        "telephone_number": data.get("telephone_number"),
        "address": data.get("address"),

        "linked_company_id": to_oid(data["linked_company_id"]),
        "user_id": to_oid(user_id),

        "status": "active",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    inserted = await db.customers.insert_one(customer_doc)

    return {
        "message": "Customer created successfully",
        "customer_id": str(inserted.inserted_id),
        "user_id": user_id,
    }

# --------------------------------------------------------
# 🟢 CREATE CUSTOMER (Single / Bulk)
# --------------------------------------------------------
@router.post("/")
async def create_customer_handler(
    request: Request,
    logo_file: UploadFile = File(None),  # optional
    user=Depends(require_roles("superadmin", "company")),
):
    content_type = request.headers.get("content-type", "")

    # ----------------------------------
    # 🔵 CASE 1: JSON → Bulk or Single
    # ----------------------------------
    if content_type.startswith("application/json"):
        data = await request.json()

        # 🔹 Bulk
        if isinstance(data, list):
            if not data:
                raise HTTPException(status_code=400, detail="Input list cannot be empty")

            results = []
            for item in data:
                try:
                    res = await create_single_customer(item, user)
                    results.append({"success": True, "data": res})
                except HTTPException as e:
                    results.append({"success": False, "error": e.detail, "data": item})

            return {
                "message": "Bulk creation completed",
                "total": len(data),
                "results": results,
            }

        # 🔹 Single JSON (no file)
        return await create_single_customer(data, user)

    # ----------------------------------
    # 🟢 CASE 2: FORM-DATA → Single + File
    # ----------------------------------
    elif content_type.startswith("multipart/form-data"):
        form = await request.form()
        print("Form data:", form)
        # Convert form-data → dict (NO bytes issue)
        data = dict(form)

        # Remove file object from dict
        data.pop("logo_file", None)

        # Save logo if provided
        if logo_file:
            
            path, _ = await save_customer_file(logo_file, data["username"])
            data["logo_url"] = path
            print("Logo saved at:", path)
        return await create_single_customer(data, user)

    else:
        raise HTTPException(status_code=415, detail="Unsupported Content-Type")

# @router.post("/")
# async def create_customer_handler(
#     data: Union[Dict, List[Dict]],
#     user=Depends(require_roles("superadmin", "company"))
# ):

#     # 🔵 Bulk Creation
#     if isinstance(data, list):
#         if not data:
#             raise HTTPException(status_code=400, detail="Input list cannot be empty")

#         results = []
#         for item in data:
#             try:
#                 result = await create_single_customer(item, user)
#                 results.append({"success": True, "data": result})
#             except HTTPException as e:
#                 results.append({"success": False, "error": e.detail, "data": item})

#         return {
#             "message": "Bulk creation completed",
#             "total": len(data),
#             "results": results,
#         }

#     else:
#         # 🔵 Single Creation
#         print("Single customer creation")
#         return await create_single_customer(data, user)

# --------------------------------------------------------
# 🔵 LIST CUSTOMERS WITH USER + COMPANY JOIN
# --------------------------------------------------------
@router.get("/")
async def list_customers(request: Request,user=Depends(require_roles("superadmin", "company"))):

    pipeline = [
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user",
            }
        },
        {"$unwind": "$user"},
        {
            "$lookup": {
                "from": "companies",
                "localField": "linked_company_id",
                "foreignField": "_id",
                "as": "company",
            }
        },
        {"$unwind": {"path": "$company", "preserveNullAndEmptyArrays": True}},
    ]

    data = []
    async for doc in db.customers.aggregate(pipeline):

        # Convert ObjectIds
        doc["id"] = str(doc.pop("_id"))
        doc["user_id"] = str(doc["user_id"])
        doc["linked_company_id"] = str(doc["linked_company_id"])

         # ✅ CUSTOMER LOGO FIX
        if doc.get("logo_url"):
            doc["logo_url"] = f"media/{doc['logo_url']}"

        doc["user"]["id"] = str(doc["user"].pop("_id"))
        doc["user"].pop("password")


        # ✅ COMPANY SAFE FIX
        # COMPANY
        if doc.get("company"):
            doc["company"]["id"] = str(doc["company"].pop("_id"))

            if doc["company"].get("logo_url") and not doc["company"]["logo_url"].startswith("media/"):
                doc["company"]["logo_url"] = f"media/{doc['company']['logo_url']}"
        else:
            doc["company"] = None

        data.append(doc)

    return data

# --------------------------------------------------------
# 🔵 GET SINGLE CUSTOMER
# --------------------------------------------------------
@router.get("/{customer_id}")
async def get_customer(customer_id: str, user=Depends(require_roles("superadmin", "company"))):

    pipeline = [
        {"$match": {"_id": to_oid(customer_id)}},
        {
            "$lookup": {
                "from": "users",
                "localField": "user_id",
                "foreignField": "_id",
                "as": "user"
            }
        },
        {"$unwind": "$user"},
        {
            "$lookup": {
                "from": "companies",
                "localField": "linked_company_id",
                "foreignField": "_id",
                "as": "company",
            }
        },
        {"$unwind": {"path": "$company", "preserveNullAndEmptyArrays": True}},
    ]

    result = await db.customers.aggregate(pipeline).to_list(1)
    if not result:
        raise HTTPException(status_code=404, detail="Customer not found")

    doc = result[0]

    doc["id"] = str(doc.pop("_id"))
    doc["user_id"] = str(doc["user_id"])
    doc["linked_company_id"] = str(doc["linked_company_id"])
    # ✅ CUSTOMER LOGO FIX
    if doc.get("logo_url"):
        doc["logo_url"] = f"media/{doc['logo_url']}"

    doc["user"]["id"] = str(doc["user"].pop("_id"))
    doc["user"].pop("password")

     # ========================
    # COMPANY SAFE FIX
    # ========================
    if doc.get("company"):
        company = doc["company"]

        company["id"] = str(company.pop("_id"))

        if company.get("logo_url") and not company["logo_url"].startswith("media/"):
            company["logo_url"] = f"media/{company['logo_url']}"
    else:
        doc["company"] = None

    return doc

# --------------------------------------------------------
# 🟠 UPDATE CUSTOMER
# --------------------------------------------------------
@router.patch("/{customer_id}")
async def update_customer(
    customer_id: str,

    customer_company_name: str = Form(None),
    full_name: str = Form(None),
    city: str = Form(None),
    phone_number: str = Form(None),
    telephone_number: str = Form(None),
    address: str = Form(None),
    status: str = Form(None),
    logo_url: UploadFile = File(None),


    user=Depends(require_roles("company"))
):
    # ---- Check customer exists ----
    customer = await db.customers.find_one({"_id": ObjectId(customer_id)})
    if not customer:
        raise HTTPException(404, "Customer not found")

    # ---- Build dynamic update dict ----
    update_data = {}

    if customer_company_name is not None:
        update_data["customer_company_name"] = customer_company_name
    if full_name is not None:
        update_data["full_name"] = full_name
    if city is not None:
        update_data["city"] = city
    if phone_number is not None:
        update_data["phone_number"] = phone_number
    if telephone_number is not None:
        update_data["telephone_number"] = telephone_number
    if address is not None:
        update_data["address"] = address
    if status is not None:
        update_data["status"] = status
    if logo_url is not None:
        from app.services.storage import save_upload_file
        path, _ = await save_upload_file(logo_url, f"customer_{customer_id}")
        update_data["logo_url"] = path

    if not update_data:
        raise HTTPException(400, "No fields provided to update")

    update_data["updated_at"] = datetime.utcnow()

    # ---- Update MongoDB ----
    await db.customers.update_one(
        {"_id": ObjectId(customer_id)},
        {"$set": update_data}
    )

    return {
        "message": "Customer updated successfully",
        "updated_fields": list(update_data.keys())
    }

'''@router.patch("/{customer_id}")
async def update_customer(customer_id: str, data: Dict, 
                          user=Depends(require_roles("superadmin", "company"))):

    data["updated_at"] = datetime.utcnow()

    # Can't manually change user_id
    data.pop("user_id", None)

    result = await db.customers.update_one(
        {"_id": to_oid(customer_id)},
        {"$set": data},
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Customer not found")

    return {"message": "Customer updated successfully"}'''

# --------------------------------------------------------
# 🔴 DELETE CUSTOMER + LINKED USER
# --------------------------------------------------------
@router.delete("/{customer_id}")
async def delete_customer(customer_id: str, user=Depends(require_roles("superadmin", "company"))):

    customer = await db.customers.find_one({"_id": to_oid(customer_id)})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    await db.customers.delete_one({"_id": to_oid(customer_id)})
    await db.users.delete_one({"_id": customer["user_id"]})

    return {"message": "Customer and linked user deleted successfully"}
