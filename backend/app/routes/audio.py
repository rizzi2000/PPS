import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from ..schemas.audio_schema import AudioUploadResponse, FilenameRequest
from ..services.audio_service import validate_and_save_audio
from ..services.transcription_service import transcribe_audio
from ..services.visualization_service import analyze_rhythm

router = APIRouter()

def get_upload_path(filename: str):
    # Ruta absoluta hacia la carpeta uploads
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_dir, "uploads", filename)

@router.post("/upload", response_model=AudioUploadResponse)
async def upload_audio_endpoint(file: UploadFile = File(...)):
    return await validate_and_save_audio(file)

@router.post("/process-ai")
async def process_ai_endpoint(data: FilenameRequest):
    audio_path = get_upload_path(data.filename)
    basename = os.path.splitext(data.filename)[0]
    
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio no encontrado")

    # 1. Transcripción y Análisis IA (Genera el _analysis.json)
    trans_res = transcribe_audio(audio_path, basename)
    if trans_res["status"] == "error":
        raise HTTPException(status_code=500, detail=trans_res["error"])

    # 2. Análisis de Ritmo (Lee el _analysis.json y genera el _rhythm.json)
    rhythm_res = analyze_rhythm(audio_path, basename)
    
    # Devolvemos ambos al Frontend en una sola respuesta
    return {
        "message": "Procesamiento completo",
        "ai_data": trans_res["data"],    # Datos para tabla y resumen
        "rhythm_data": rhythm_res["data"] # Datos para el gráfico
    }