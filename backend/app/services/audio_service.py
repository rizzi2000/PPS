import os
import shutil
from fastapi import UploadFile, HTTPException

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "../../uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def validate_and_save_audio(file: UploadFile):
    if not file.filename.lower().endswith(('.mp3', '.wav', '.m4a')):
        raise HTTPException(status_code=400, detail="Formato no permitido. Use MP3 o WAV.")
    
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    return {"filename": file.filename, "message": "Audio subido correctamente."}