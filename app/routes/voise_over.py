import logging
import subprocess
from fastapi import APIRouter, UploadFile, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from typing import Optional
from bson import ObjectId
from app.utils.auth import require_roles
from app.db.connection import db
from datetime import datetime
from app.services.kokoro_tts import (
    CUDA_AVAILABLE,
    get_model,
    get_pipeline,
    synthesize_and_store_media,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kokoro", tags=["kokoro-tts"])
logger.info(f"Kokoro: CUDA available: {CUDA_AVAILABLE}")

# Voice catalogue (kept identical to official app choices)
VOICES = [
    {"id": "af_heart",    "name": "Heart",    "lang": "en-us", "gender": "Female"},
    {"id": "af_bella",    "name": "Bella",    "lang": "en-us", "gender": "Female"},
    {"id": "af_nicole",   "name": "Nicole",   "lang": "en-us", "gender": "Female"},
    {"id": "af_aoede",    "name": "Aoede",    "lang": "en-us", "gender": "Female"},
    {"id": "af_kore",     "name": "Kore",     "lang": "en-us", "gender": "Female"},
    {"id": "af_sarah",    "name": "Sarah",    "lang": "en-us", "gender": "Female"},
    {"id": "af_nova",     "name": "Nova",     "lang": "en-us", "gender": "Female"},
    {"id": "af_sky",      "name": "Sky",      "lang": "en-us", "gender": "Female"},
    {"id": "af_alloy",    "name": "Alloy",    "lang": "en-us", "gender": "Female"},
    {"id": "af_jessica",  "name": "Jessica",  "lang": "en-us", "gender": "Female"},
    {"id": "af_river",    "name": "River",    "lang": "en-us", "gender": "Female"},
    {"id": "am_michael",  "name": "Michael",  "lang": "en-us", "gender": "Male"},
    {"id": "am_fenrir",   "name": "Fenrir",   "lang": "en-us", "gender": "Male"},
    {"id": "am_puck",     "name": "Puck",     "lang": "en-us", "gender": "Male"},
    {"id": "am_echo",     "name": "Echo",     "lang": "en-us", "gender": "Male"},
    {"id": "am_eric",     "name": "Eric",     "lang": "en-us", "gender": "Male"},
    {"id": "am_liam",     "name": "Liam",     "lang": "en-us", "gender": "Male"},
    {"id": "am_onyx",     "name": "Onyx",     "lang": "en-us", "gender": "Male"},
    {"id": "am_santa",    "name": "Santa",    "lang": "en-us", "gender": "Male"},
    {"id": "am_adam",     "name": "Adam",     "lang": "en-us", "gender": "Male"},
    {"id": "bf_emma",     "name": "Emma",     "lang": "en-gb", "gender": "Female"},
    {"id": "bf_isabella", "name": "Isabella", "lang": "en-gb", "gender": "Female"},
    {"id": "bf_alice",    "name": "Alice",    "lang": "en-gb", "gender": "Female"},
    {"id": "bf_lily",     "name": "Lily",     "lang": "en-gb", "gender": "Female"},
    {"id": "bm_george",   "name": "George",   "lang": "en-gb", "gender": "Male"},
    {"id": "bm_fable",    "name": "Fable",    "lang": "en-gb", "gender": "Male"},
    {"id": "bm_lewis",    "name": "Lewis",    "lang": "en-gb", "gender": "Male"},
    {"id": "bm_daniel",   "name": "Daniel",   "lang": "en-gb", "gender": "Male"},
]

VOICE_IDS = {v["id"] for v in VOICES}


# ---- Request schema -----------------------------------------------------
CHAR_LIMIT = 5000

class TTSRequest(BaseModel):
    voisetext: str
    voice: str = "af_heart"
    speed: float = 1.0
    company_id: Optional[str] = None

    @field_validator("voisetext")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        v = v.strip()[:CHAR_LIMIT]
        if not v:
            raise ValueError("Text cannot be empty")
        return v

    @field_validator("voice")
    @classmethod
    def voice_valid(cls, v: str) -> str:
        if v not in VOICE_IDS:
            raise ValueError(f"Unknown voice '{v}'")
        return v

    @field_validator("speed")
    @classmethod
    def speed_valid(cls, v: float) -> float:
        if not (0.5 <= v <= 2.0):
            raise ValueError("Speed must be 0.5–2.0")
        return v

# -----------------------------------------------------------
# ObjectId Serializer
# -----------------------------------------------------------
def serialize_mongo(data):
    if isinstance(data, list):
        return [serialize_mongo(i) for i in data]

    if isinstance(data, dict):
        new_data = {}
        for k, v in data.items():
            if isinstance(v, ObjectId):
                new_data[k] = str(v)
            else:
                new_data[k] = serialize_mongo(v)
        return new_data

    return data

# ---- Routes -------------------------------------------------------------
@router.get("/voices")
def list_voices():
    return {"voices": VOICES}

@router.post("/tts")
async def tts_to_media(
    request: TTSRequest,
    user=Depends(require_roles("superadmin", "company"))
):
    # 1. Resolve company_id
    if user["role"] == "company":
        company = await db.companies.find_one({"user_id": str(user["_id"])})
        if not company:
            raise HTTPException(404, "Company record not found for this user")
        company_id = str(company["_id"])
    else:
        company_id = request.company_id  # superadmin provides it in body

    if not company_id:
        raise HTTPException(400, "company_id is required")

    voicetext = request.voisetext
    voice = request.voice
    speed = request.speed

    # 3. Generate + store audio
    try:
        stored = await synthesize_and_store_media(
            company_id=company_id,
            voisetext=voicetext,
            voice=voice,
            speed=speed,
        )
        local_path = stored["file_url"]
        size = stored["size"]
        filename = stored["original_name"]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("TTS generation failed")
        raise HTTPException(500, f"TTS generation failed: {e}")

    # 6. Insert media document
    media_doc = {
        "company_id": company_id,
        "file_url": local_path,
        "file_type": "audio",
        "original_name": filename,
        "size": size,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    result = await db.media.insert_one(media_doc)
    media_doc["id"] = str(result.inserted_id)

    return {"media": serialize_mongo(media_doc)}

@router.get("/health")
def health():
    return {"status": "ok", "cuda": CUDA_AVAILABLE, "device": "cuda" if CUDA_AVAILABLE else "cpu"}

async def warmup():
    """Pre-load model + both pipelines so the first request isn't slow."""
    try:
        get_model()
        get_pipeline("a")
        get_pipeline("b")
        logger.info("Kokoro warmup complete ✓")
    except Exception as e:
        logger.warning(f"Kokoro warmup skipped: {e}")
