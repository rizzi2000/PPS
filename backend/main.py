from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import audio

app = FastAPI(title="API Análisis Terapéutico")

# Configurar CORS para permitir que el Frontend (React) se comunique
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # Puerto por defecto de Vite/React
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio.router, prefix="/api/audio", tags=["Audio"])

@app.get("/")
def read_root():
    return {"status": "API Online - Sistema de Pasantía"}