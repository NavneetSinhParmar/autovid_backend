import subprocess
import uuid
import logging
from functools import lru_cache
from io import BytesIO

import numpy as np
import soundfile as sf
import torch

from fastapi import UploadFile, HTTPException

from app.services.storage import save_upload_file

logger = logging.getLogger(__name__)

CUDA_AVAILABLE = torch.cuda.is_available()


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


def synthesize_audio_numpy(voisetext: str, voice: str, speed: float) -> np.ndarray:
    if not voisetext or not str(voisetext).strip():
        raise HTTPException(400, "Text cannot be empty")

    lang_code = str(voice)[0] if voice else "a"
    model, _device = get_model()
    pipeline = get_pipeline(lang_code)

    pack = pipeline.load_voice(voice)
    audio_chunks = []

    for _, ps, _ in pipeline(voisetext, voice, speed):
        if ps is None:
            continue
        ref_s = pack[len(ps) - 1]
        with torch.no_grad():
            audio_tensor = model(ps, ref_s, speed)
        audio_chunks.append(audio_tensor.cpu().numpy())

    if not audio_chunks:
        raise HTTPException(500, "No audio chunks produced")

    return np.concatenate(audio_chunks)


def encode_wav_bytes(audio_data: np.ndarray, samplerate: int = 24000) -> bytes:
    wav_buffer = BytesIO()
    sf.write(wav_buffer, audio_data, samplerate=samplerate, format="WAV")
    return wav_buffer.getvalue()


def try_convert_wav_to_mp3(wav_bytes: bytes) -> tuple[bytes, str]:
    """
    Returns (bytes, ext) where ext is 'mp3' or 'wav' (fallback).
    """
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                "pipe:0",
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "2",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=wav_bytes,
            capture_output=True,
            timeout=30,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout, "mp3"
    except Exception:
        pass
    return wav_bytes, "wav"


async def synthesize_and_store_media(
    *,
    company_id: str,
    voisetext: str,
    voice: str,
    speed: float,
) -> dict:
    """
    Generates TTS audio, stores it under ./media/<company_id>/..., and returns:
      { "file_url": "<relative path>", "file_type": "audio", "size": <int>, "original_name": <str> }
    """
    if not company_id:
        raise HTTPException(400, "company_id is required")

    audio_data = synthesize_audio_numpy(voisetext=voisetext, voice=voice, speed=speed)
    wav_bytes = encode_wav_bytes(audio_data)
    final_bytes, ext = try_convert_wav_to_mp3(wav_bytes)

    uid = uuid.uuid4().hex
    filename = f"tts_{uid}.{ext}"
    fake_upload = UploadFile(filename=filename, file=BytesIO(final_bytes))
    local_path, size = await save_upload_file(fake_upload, company_id)

    return {
        "file_url": local_path,  # relative path (no ./media prefix)
        "file_type": "audio",
        "original_name": filename,
        "size": size,
    }

