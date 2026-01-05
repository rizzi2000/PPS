import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from ..schemas.audio_schema import AudioUploadResponse, FilenameRequest
from ..services.audio_service import validate_and_save_audio
from ..services.transcription_service import transcribe_audio
from ..services.visualization_service import analyze_rhythm

router = APIRouter()

def get_upload_path(filename: str):
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) # Llega a 'backend'
    return os.path.join(base_dir, "uploads", filename)

@router.post("/upload", response_model=AudioUploadResponse)
async def upload_audio_endpoint(file: UploadFile = File(...)):
    return await validate_and_save_audio(file)

@router.post("/process-ai")
async def process_ai_endpoint(data: FilenameRequest):
    # CORRECCIÓN AQUÍ: Usamos la ruta absoluta calculada correctamente
    audio_path = get_upload_path(data.filename)
    
    print(f"🔍 Buscando audio en: {audio_path}") # Debug para ver en consola
    
    if not os.path.exists(audio_path):
        print("❌ Archivo no encontrado en la ruta especificada.")
        raise HTTPException(status_code=404, detail=f"Audio no encontrado en: {audio_path}")

    basename = os.path.splitext(data.filename)[0]
    
    # Llamamos al servicio
    result = transcribe_audio(audio_path, basename)
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["error"])
        
    return {"message": "IA Completada", "data": result["data"]}

@router.post("/process-rhythm")
async def process_rhythm_endpoint(data: FilenameRequest):
    # CORRECCIÓN AQUÍ TAMBIÉN
    audio_path = get_upload_path(data.filename)
    basename = os.path.splitext(data.filename)[0]
    
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=404, detail="Audio no encontrado")
    
    result = analyze_rhythm(audio_path, basename)
    return {"message": "Ritmo Calculado", "data": result["data"]}