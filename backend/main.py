import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import audio

app = FastAPI(
    title="NeuroVoice API",
    description="Análisis acústico y clínico de sesiones terapéuticas",
    version="2.0.0",
)

origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Necesario para que el front pueda leer los headers de Range del audio.
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

app.include_router(audio.router, prefix="/api", tags=["Sesiones"])


@app.get("/api/health")
def health():
    from app.core.config import (GEMINI_API_KEY, WHISPER_COMPUTE,
                                 WHISPER_MODEL)
    return {
        "status": "ok",
        "whisper_model": WHISPER_MODEL,
        "compute_type": WHISPER_COMPUTE,
        "gemini_configured": bool(GEMINI_API_KEY),
    }


@app.on_event("startup")
def warmup():
    """Precarga los modelos en background para que la primera sesión no pague
    la carga (~30 s Whisper + ~7 s ECAPA)."""
    import threading

    def load():
        from app.services.asr import get_model
        from app.services.diarize import _get_encoder
        get_model()
        _get_encoder()

    threading.Thread(target=load, daemon=True).start()
