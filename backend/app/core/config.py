"""Configuración central y rutas del proyecto."""
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
CACHE_DIR = os.path.join(BASE_DIR, "cache")          # WAV 16k mono normalizados
RESULTS_DIR = os.path.join(BASE_DIR, "results")      # JSON final por sesión

for _d in (UPLOAD_DIR, CACHE_DIR, RESULTS_DIR):
    os.makedirs(_d, exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# --- ASR ---------------------------------------------------------------
# En CPU de 2 núcleos, "small" con cuantización int8 es el punto dulce:
# ~4x más rápido que openai-whisper "base" y mucho más preciso.
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
CPU_THREADS = int(os.getenv("CPU_THREADS", "4"))

SAMPLE_RATE = 16000        # tasa de trabajo de todo el pipeline
PEAKS_BUCKETS = 2000       # resolución del waveform enviado al front

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "300"))
ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mp4"}

# Etiquetas cerradas: el LLM debe elegir de acá o se descarta el valor.
EMOTIONS = [
    "Neutral", "Alegria", "Tristeza", "Ansiedad",
    "Enojo", "Reflexion", "Confusion", "Certeza",
]
