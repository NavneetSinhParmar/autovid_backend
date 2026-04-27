import uuid
import time
import logging
import subprocess
from pathlib import Path
from functools import lru_cache

import torch
import numpy as np
import soundfile as sf
from fastapi import APIRouter, UploadFile, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator
from typing import Optional
from bson import ObjectId
from app.utils.auth import require_roles
from app.db.connection import db
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kokoro", tags=["kokoro-tts"])

CUDA_AVAILABLE = torch.cuda.is_available()
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


# ---- Model & pipeline helpers (cached) ---------------------------------
@lru_cache(maxsize=1)
def get_model():
    from kokoro import KModel
    device = "cuda" if CUDA_AVAILABLE else "cpu"
    logger.info(f"Loading KModel on {device}…")
    model = KModel().to(device).eval()
    logger.info(f"KModel ready ✓ (device={device})")
    return model, device


@lru_cache(maxsize=2)
def get_pipeline(lang_code: str):
    from kokoro import KPipeline
    logger.info(f"Loading KPipeline lang_code='{lang_code}'…")
    pipeline = KPipeline(lang_code=lang_code, model=False)
    pipeline.g2p.lexicon.golds["kokoro"] = "kˈOkəɹO" if lang_code == "a" else "kˈQkəɹQ"
    logger.info(f"KPipeline '{lang_code}' ready ✓")
    return pipeline


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

    # 2. Unpack the rest of the request
    voicetext = request.voisetext  # already stripped/validated by Pydantic
    voice = request.voice
    speed = request.speed

    # 3. Generate audio
    try:
        lang_code = voice[0]
        model, device = get_model()
        pipeline = get_pipeline(lang_code)

        pack = pipeline.load_voice(voice)
        audio_chunks = []

        for _, ps, _ in pipeline(voicetext, voice, speed):
            if ps is None:
                continue
            ref_s = pack[len(ps) - 1]
            with torch.no_grad():
                audio_tensor = model(ps, ref_s, speed)
            audio_chunks.append(audio_tensor.cpu().numpy())

        if not audio_chunks:
            raise HTTPException(500, "No audio chunks produced")

        audio_data = np.concatenate(audio_chunks)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("TTS generation failed")
        raise HTTPException(500, f"TTS generation failed: {e}")

    # 4. Encode to WAV, optionally convert to MP3
    from io import BytesIO
    from app.services.storage import save_upload_file

    uid = uuid.uuid4().hex
    wav_buffer = BytesIO()
    sf.write(wav_buffer, audio_data, samplerate=24000, format="WAV")
    wav_bytes = wav_buffer.getvalue()

    final_bytes = wav_bytes
    ext = "wav"

    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", "pipe:0",
             "-codec:a", "libmp3lame", "-q:a", "2", "-f", "mp3", "pipe:1"],
            input=wav_bytes,
            capture_output=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            final_bytes = proc.stdout
            ext = "mp3"
    except Exception:
        pass  # fall back to WAV

    # 5. Save file
    filename = f"tts_{uid}.{ext}"
    fake_upload = UploadFile(filename=filename, file=BytesIO(final_bytes))
    local_path, size = await save_upload_file(fake_upload, company_id)

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
