from annotated_types import doc
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from bson import ObjectId
from typing import Union, List, Dict, Any
import io
import csv
import os
import logging
import re
from openpyxl import load_workbook

from app.db.connection import db
from app.utils.auth import require_roles, hash_password
from app.models.customer_model import CustomerCreate, CustomerOut
from fastapi import Request, UploadFile, File, Form
from app.services.media_validator import validate_image
from app.core.tenancy import company_id_for_user, company_object_id_filter
from app.core.pagination import PaginationParams, page_result
from app.services.storage import delete_media_file, delete_media_folder, save_customer_file
from app.services.url import build_media_url
from fastapi import Request
from app.services.storage import customer_folder_path
import random
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel

router = APIRouter(prefix="/customer", tags=["Customer Management"])
logger = logging.getLogger(__name__)

CUSTOMER_LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg")
CUSTOMER_LOGO_EXTENSION_PRIORITY = {".png": 0, ".jpeg": 1, ".jpg": 2}
CUSTOMER_LOGO_FORM_FIELDS = {
    "logo_files",
    "logo_files[]",
    "logo_file",
    "logoFiles",
    "logos",
    "files",
}

class DeleteCustomersRequest(BaseModel):
    customer_ids: List[str]


def _normalize_logo_filename(value: Any) -> str:
    """Return a safe filename reference from a CSV/Excel cell."""
    if value is None:
        return ""
    return os.path.basename(str(value).strip().replace("\\", "/"))


def _build_logo_maps(logo_files: List[UploadFile]):
    by_filename = {}
    by_stem = {}

    for logo_file in logo_files:
        filename = _normalize_logo_filename(logo_file.filename)
        if not filename:
            continue

        filename_key = filename.casefold()
        by_filename[filename_key] = logo_file

        stem, extension = os.path.splitext(filename_key)
        if extension not in CUSTOMER_LOGO_EXTENSIONS:
            continue
        existing = by_stem.get(stem)
        if existing is None:
            by_stem[stem] = logo_file
            continue

        existing_extension = os.path.splitext(
            _normalize_logo_filename(existing.filename).casefold()
        )[1]
        if (
            CUSTOMER_LOGO_EXTENSION_PRIORITY[extension]
            < CUSTOMER_LOGO_EXTENSION_PRIORITY[existing_extension]
        ):
            by_stem[stem] = logo_file

    return by_filename, by_stem


def _logo_files_from_form(form, logo_files: List[UploadFile]) -> List[UploadFile]:
    if logo_files:
        return list(logo_files)

    return [
        value
        for key, value in form.multi_items()
        if key in CUSTOMER_LOGO_FORM_FIELDS
        and getattr(value, "filename", None)
        and callable(getattr(value, "read", None))
    ]


def _resolve_logo_file(
    logo_filename: str,
    logo_files_by_filename: Dict[str, UploadFile],
    logo_files_by_stem: Dict[str, UploadFile],
    row_num: int,
) -> UploadFile:
    filename_key = logo_filename.casefold()
    stem, extension = os.path.splitext(filename_key)

    if extension:
        if extension not in CUSTOMER_LOGO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Row {row_num}: Logo must be a PNG, JPG, or JPEG file",
            )
        logo_file = logo_files_by_filename.get(filename_key)
        if logo_file is None:
            logo_file = logo_files_by_stem.get(stem)
    else:
        logo_file = logo_files_by_stem.get(stem)

    if logo_file is None:
        raise HTTPException(
            status_code=400,
            detail=f"Row {row_num}: Logo '{logo_filename}' was not found in uploaded logo files",
        )
    return logo_file

async def generate_distributed_id() -> str:
    """
    Generate a globally-unique 8-digit numeric distributed_id for customer login.
    """
    for _ in range(50):
        candidate = str(random.randint(10_000_000, 99_999_999))
        # distributed_id is used as `users.username` too, so ensure uniqueness across both collections.
        exists_customer = await db.customers.find_one({"distributed_id": candidate})
        exists_user = await db.users.find_one({"username": candidate})
        if not exists_customer and not exists_user:
            return candidate
    raise HTTPException(status_code=500, detail="Unable to generate distributed_id")

def validate_image_file(file: UploadFile):
    allowed_extensions = (".png", ".jpg", ".jpeg")
    allowed_types = ["image/png", "image/jpeg", "image/jpg"]

    filename = file.filename.lower()

    if not filename.endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"{file.filename} must be PNG or JPG/JPEG format"
        )

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"{file.filename} has invalid content type"
        )


def delete_customer_media(customer: dict):
    company_id = str(customer["linked_company_id"])
    customer_id = str(customer["_id"])
    delete_media_folder(customer_folder_path(company_id, customer_id))

    distributed_id = customer.get("distributed_id")
    if distributed_id:
        delete_media_folder(customer_folder_path(company_id, str(distributed_id)))

    delete_media_folder(f"customer_{customer_id}")

    logo_url = customer.get("logo_url")
    if logo_url:
        logo_path = str(logo_url).replace("\\", "/").replace("./media/", "").replace("media/", "").lstrip("/")
        if not logo_path:
            return
        if logo_path.startswith(("http://", "https://")):
            return
        logo_folder = os.path.dirname(logo_path).replace("\\", "/")
        if "/customers/" in logo_folder or logo_folder.startswith("customer_"):
            delete_media_folder(logo_folder)
        else:
            delete_media_file(logo_path)

# --------------------------------------------------------
# 🟢 BULK UPLOAD: Excel + Logo Files
# --------------------------------------------------------

@router.post("/bulk-upload")
async def bulk_upload_customers(
    request: Request,
    excel_file: UploadFile = File(...),
    logo_files: List[UploadFile] = File(default=[]),
    linked_company_id: str = Form(None),
    user=Depends(require_roles("superadmin", "company")),
):


    try:
        filename = excel_file.filename.lower()
        is_csv = filename.endswith(".csv")
        is_excel = filename.endswith((".xlsx", ".xls"))

        if not (is_csv or is_excel):
            raise HTTPException(
                status_code=400,
                detail="File must be Excel (.xlsx, .xls) or CSV (.csv)",
            )

        file_content = await excel_file.read()
        if not file_content:
            raise HTTPException(status_code=400, detail="File is empty")

        # -------- Parse File --------
        headers = []
        rows_data = []

        if is_csv:
            text_content = file_content.decode("utf-8")
            reader = csv.DictReader(io.StringIO(text_content))
            headers = [h.strip() for h in (reader.fieldnames or [])]
            rows_data = list(reader)

        else:
            workbook = load_workbook(io.BytesIO(file_content))
            worksheet = workbook.active

            headers = [str(cell.value).strip() for cell in worksheet[1]]

            for row in worksheet.iter_rows(min_row=2, values_only=True):
                if not any(row):
                    continue
                row_dict = {}
                for idx, header in enumerate(headers):
                    if idx < len(row):
                        row_dict[header] = row[idx]
                rows_data.append(row_dict)

        if not headers:
            raise HTTPException(status_code=400, detail="Headers missing")

        if not logo_files:
            logo_files = _logo_files_from_form(await request.form(), logo_files)

        # An import may use either "customer_logo1" or "customer_logo1.png".
        logo_files_map, logo_files_map_no_ext = _build_logo_maps(logo_files)


        # -------- Resolve Company --------
        company_id = None

        if user["role"] == "company":
            company = await db.companies.find_one({"user_id": str(user["_id"])})
            if company:
                company_id = str(company["_id"])

        elif user["role"] == "superadmin":
            if not linked_company_id:
                raise HTTPException(
                    status_code=400,
                    detail="linked_company_id required for superadmin"
                )
            company_id = linked_company_id

        # -------- Process Rows --------
        results = []
        row_num = 2
        for row_data in rows_data:

            if not any(row_data.get(f) for f in ["password", "full_name", "distributed_id"]):
                row_num += 1
                continue

            try:
                logo_filename = (
                    _normalize_logo_filename(row_data.get("logo_url"))
                    or _normalize_logo_filename(row_data.get("logo_file_name"))
                )

                logo_file = None
                logo_url = None

                if logo_filename:

                        # 🔴 Case 1: Logo name given but no files uploaded
                        if not logo_files_map:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Row {row_num}: Logo '{logo_filename}' mentioned but no logo files uploaded"
                            )

                        logo_file = _resolve_logo_file(
                            logo_filename,
                            logo_files_map,
                            logo_files_map_no_ext,
                            row_num,
                        )
                        await logo_file.seek(0)
                        await validate_image(logo_file)
                        await logo_file.seek(0)

                customer_data = {
                    "distributed_id": str(row_data.get("distributed_id") or "").strip() or None,
                    "email": str(row_data.get("email") or "").strip() or None,
                    "password": str(row_data.get("password")).strip(),
                    "full_name": str(row_data.get("full_name")).strip(),
                    "customer_company_name": row_data.get("customer_company_name"),
                    "city": row_data.get("city"),
                    "phone_number": row_data.get("phone_number"),
                    "telephone_number": row_data.get("telephone_number"),
                    "address": row_data.get("address"),
                    "linked_company_id": company_id,
                    "customer_category": str(row_data.get("customer_category")).strip()
                }

                if logo_url:
                    customer_data["logo_url"] = logo_url

                result = await create_single_customer(customer_data, user)
                if logo_file and company_id:
                    await logo_file.seek(0)
                    path, _ = await save_customer_file(logo_file, company_id, result["customer_id"])
                    await db.customers.update_one(
                        {"_id": ObjectId(result["customer_id"])},
                        {"$set": {"logo_url": path, "updated_at": datetime.utcnow()}}
                    )
                    result["logo_url"] = path

                results.append({
                    "success": True,
                    "row": row_num,
                    "data": result
                })

            except Exception as e:
                results.append({
                    "success": False,
                    "row": row_num,
                    "error": str(e),
                    "data": row_data
                })

            row_num += 1

        successful = sum(1 for r in results if r["success"])
        failed = len(results) - successful

        return {
            "message": "Bulk upload completed",
            "total_rows": len(results),
            "successful": successful,
            "failed": failed,
            "results": results,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def to_oid(value: str):
    try:
        return ObjectId(value)
    except:
        raise HTTPException(status_code=400, detail=f"Invalid ObjectId: {value}")

# --------------------------------------------------------
# 🟢 Helper: Validate and Create Customer Document
# --------------------------------------------------------
async def create_single_customer(data: Dict[str, Any], user: Dict):
    try:

        # -----------------------------
        # ✅ REQUIRED FIELD VALIDATION
        # -----------------------------
        required_fields = ["password", "full_name"]

        for field in required_fields:
            if not data.get(field):
                raise HTTPException(
                    status_code=400,
                    detail=f"{field} is required"
                )

        # -----------------------------
        # COMPANY AUTO LINK
        # -----------------------------
        if user["role"] == "company":
            company = await db.companies.find_one({"user_id": str(user["_id"])})
            if not company:
                raise HTTPException(404, "Company record not found")
            data["linked_company_id"] = str(company["_id"])

        elif user["role"] == "superadmin":
            if not data.get("linked_company_id"):
                raise HTTPException(
                    400,
                    "linked_company_id is required for superadmin"
                )

        # -----------------------------
        # distributed_id (login id) generation + uniqueness
        # -----------------------------
        distributed_id = str(data.get("distributed_id") or "").strip()
        if distributed_id:
            if not distributed_id.isdigit() or len(distributed_id) != 8:
                raise HTTPException(status_code=400, detail="distributed_id must be exactly 8 digits")
            if await db.customers.find_one({"distributed_id": distributed_id}):
                raise HTTPException(status_code=400, detail="distributed_id already exists")
        else:
            distributed_id = await generate_distributed_id()

        # ------------------------------------------------------------
        # Email rules:
        # - Same email is allowed across different companies
        # - Same email is NOT allowed inside the SAME company
        #
        # We enforce this on `customers` using (linked_company_id + email).
        # For the linked `users` record we generate a deterministic unique email
        # from distributed_id to avoid breaking existing DB constraints.
        # ------------------------------------------------------------
        customer_email = str(data.get("email") or "").strip().lower() or None

        if customer_email:
            exists_in_company = await db.customers.find_one(
                {"linked_company_id": company_object_id_filter(str(data["linked_company_id"])), "email": customer_email}
            )
            if exists_in_company:
                raise HTTPException(
                    status_code=400,
                    detail="Email already exists in this company",
                )

        user_email = f"{distributed_id}@autovid.local"

        # -----------------------------
        # CREATE USER
        # -----------------------------
        user_doc = {
            "username": distributed_id,
            "email": user_email,
            "password": hash_password(data["password"]),
            "role": "customer",
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        try:
            inserted_user = await db.users.insert_one(user_doc)
        except DuplicateKeyError:
            # Should not happen because distributed_id is globally unique
            raise HTTPException(status_code=400, detail="User already exists")
        user_id = inserted_user.inserted_id

        # -----------------------------
        # CREATE CUSTOMER
        # -----------------------------
        customer_doc = {
            "distributed_id": distributed_id,
            "customer_company_name": data.get("customer_company_name"),
            "full_name": data["full_name"],
            "email": customer_email,
            "logo_url": data.get("logo_url"),
            "city": data.get("city"),
            "phone_number": data.get("phone_number"),
            "telephone_number": data.get("telephone_number"),
            "address": data.get("address"),
            "linked_company_id": str(data["linked_company_id"]),
            "customer_category": data.get("customer_category"),  
            "user_id": user_id,
            "status": "active",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        inserted = await db.customers.insert_one(customer_doc)

        return {
            "message": "Customer created successfully",
            "customer_id": str(inserted.inserted_id),
            "user_id": str(user_id),
            "distributed_id": distributed_id,
        }

    except HTTPException:
        raise  # re-raise validation errors

    except Exception as e:
        logger.exception("Customer creation failed")
        raise HTTPException(
            status_code=500,
            detail=f"Internal error: {str(e)}"
        )

# --------------------------------------------------------
# 🟢 CREATE CUSTOMER (Single / Bulk)
# --------------------------------------------------------
@router.post("/")
async def create_customer_handler(
    request: Request,
    logo_file: UploadFile = File(None),  # optional
    linked_company_id: str = Form(None),
    user=Depends(require_roles("superadmin", "company")),
):
    content_type = request.headers.get("content-type", "")
    if user["role"] == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})
        if company:
            company_id = str(company["_id"])

    elif user["role"] == "superadmin":
        if not linked_company_id:
            raise HTTPException(
                status_code=400,
                detail="linked_company_id required for superadmin"
            )
        company_id = linked_company_id
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
        # Convert form-data → dict (NO bytes issue)
        data = dict(form)

        # Remove file object from dict
        data.pop("logo_file", None)

        if logo_file:
            await validate_image(logo_file)
            await logo_file.seek(0)

        result = await create_single_customer(data, user)
        if logo_file:
            await logo_file.seek(0)
            path, _ = await save_customer_file(logo_file, company_id, result["customer_id"])
            await db.customers.update_one(
                {"_id": ObjectId(result["customer_id"])},
                {"$set": {"logo_url": path, "updated_at": datetime.utcnow()}}
            )
            result["logo_url"] = path
        return result

    else:
        raise HTTPException(status_code=415, detail="Unsupported Content-Type")

# --------------------------------------------------------
# 🔵 LIST CUSTOMERS WITH USER + COMPANY JOIN
# --------------------------------------------------------
@router.get("/")
async def list_customers(
    request: Request,
    pagination: PaginationParams = Depends(),
    status: str | None = None,
    category: str | None = None,
    user=Depends(require_roles("superadmin", "company")),
):

    # ✅ FILTER: Company users can only see their own customers
    match_stage = {}
    if user["role"] == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})
        if not company:
            raise HTTPException(status_code=404, detail="Company not found for this user")
        match_stage["linked_company_id"] = company_object_id_filter(str(company["_id"]))
    if status:
        match_stage["status"] = status
    if category:
        match_stage["customer_category"] = category
    if pagination.search:
        escaped = re.escape(pagination.search)
        match_stage["$or"] = [
            {"full_name": {"$regex": escaped, "$options": "i"}},
            {"email": {"$regex": escaped, "$options": "i"}},
            {"distributed_id": {"$regex": escaped, "$options": "i"}},
            {"customer_company_name": {"$regex": escaped, "$options": "i"}},
        ]

    pipeline = []
    
    # Add match stage only if there are filters
    if match_stage:
        pipeline.append({"$match": match_stage})
    
    total = await db.customers.count_documents(match_stage)
    sort_field, sort_direction = pagination.sort({"created_at", "updated_at", "full_name", "distributed_id"})
    pipeline.extend([
        {"$sort": {sort_field: sort_direction}},
        {"$skip": pagination.skip},
        {"$limit": pagination.limit},
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
                "let": {"company_id": "$linked_company_id"},
                "pipeline": [{
                    "$match": {"$expr": {"$eq": [
                        "$_id",
                        {"$convert": {"input": "$$company_id", "to": "objectId", "onError": None, "onNull": None}},
                    ]}}
                }],
                "as": "company",
            }
        },
        {"$unwind": {"path": "$company", "preserveNullAndEmptyArrays": True}},
    ])

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

    result = page_result(data, total, pagination)
    result["customers"] = result.pop("items")
    return result

# --------------------------------------------------------
# 🔵 GET SINGLE CUSTOMER
# --------------------------------------------------------
@router.get("/{customer_id}")
async def get_customer(customer_id: str, user=Depends(require_roles("superadmin", "company"))):

    # ✅ AUTHORIZATION: Company users can only access their own customers
    match_filter = {"_id": to_oid(customer_id)}
    
    if user["role"] == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})
        if not company:
            raise HTTPException(status_code=404, detail="Company not found for this user")
        match_filter["linked_company_id"] = company_object_id_filter(str(company["_id"]))

    pipeline = [
        {"$match": match_filter},
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
                "let": {"company_id": "$linked_company_id"},
                "pipeline": [{
                    "$match": {"$expr": {"$eq": [
                        "$_id",
                        {"$convert": {"input": "$$company_id", "to": "objectId", "onError": None, "onNull": None}},
                    ]}}
                }],
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
    customer_category: str = Form(None),  # NEW FIELD
    user=Depends(require_roles("company"))
):
    company_id = await company_id_for_user(user)
    customer = await db.customers.find_one({
        "_id": ObjectId(customer_id),
        "linked_company_id": company_object_id_filter(company_id),
    })
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
        await validate_image(logo_url)
        await logo_url.seek(0)

        path, _ = await save_customer_file(
            logo_url,
            str(customer["linked_company_id"]),
            customer_id
        )
        update_data["logo_url"] = path
    if customer_category is not None:  # NEW FIELD
        update_data["customer_category"] = customer_category    

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

# --------------------------------------------------------
# 🔴 DELETE MULTIPLE CUSTOMERS + LINKED USERS
# --------------------------------------------------------
@router.delete("/delete-multiple")   # ✅ Must come FIRST
async def delete_customers(
    payload: DeleteCustomersRequest,
    user=Depends(require_roles("superadmin", "company"))
):

    object_ids = [to_oid(cid) for cid in payload.customer_ids]
    query = {"_id": {"$in": object_ids}}
    if user.get("role") == "company":
        company_id = await company_id_for_user(user)
        query["linked_company_id"] = company_object_id_filter(company_id)
    customers = await db.customers.find(query).to_list(length=None)

    if not customers:
        raise HTTPException(status_code=404, detail="Customers not found")

    user_ids = [customer["user_id"] for customer in customers]

    # Delete customers
    await db.customers.delete_many({"_id": {"$in": [customer["_id"] for customer in customers]}})

    # Delete linked users
    await db.users.delete_many({
        "_id": {"$in": user_ids}
    })

    for customer in customers:
        delete_customer_media(customer)

    return {
        "message": "Customers and linked users deleted successfully"
    }


# --------------------------------------------------------
# 🔴 DELETE CUSTOMER + LINKED USER
# --------------------------------------------------------
@router.delete("/{customer_id}")
async def delete_customer(customer_id: str, user=Depends(require_roles("superadmin", "company"))):
    query = {"_id": to_oid(customer_id)}
    if user.get("role") == "company":
        company_id = await company_id_for_user(user)
        query["linked_company_id"] = company_object_id_filter(company_id)
    customer = await db.customers.find_one(query)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    await db.customers.delete_one({"_id": to_oid(customer_id)})
    await db.users.delete_one({"_id": customer["user_id"]})
    delete_customer_media(customer)

    return {"message": "Customer and linked user deleted successfully"}
    
