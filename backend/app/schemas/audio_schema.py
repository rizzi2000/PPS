from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class AudioUploadResponse(BaseModel):
    filename: str
    message: str

class FilenameRequest(BaseModel):
    filename: str

# Para documentación (opcional)
class AnalisisResponse(BaseModel):
    message: str
    analysis: Dict[str, Any]