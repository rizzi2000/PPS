import os
import json
import google.generativeai as genai
import typing_extensions
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Directorio para guardar los JSONs de la IA
TRANSCRIPTIONS_DIR = os.path.join(os.path.dirname(__file__), "../../transcriptions")
os.makedirs(TRANSCRIPTIONS_DIR, exist_ok=True)

class RolInfo(typing_extensions.TypedDict):
    hablante: str # Ej: "Speaker A"
    rol: str      # Ej: "paciente"

# Definición estricta de tipos para el JSON
class SegmentoDialogo(typing_extensions.TypedDict):
    inicio: str       # "MM:SS"
    fin: str          # "MM:SS"
    hablante: str     # "Speaker A"
    rol: str          # "paciente" o "profesional"
    texto_es: str     
    texto_en: str     
    emocion: str      # "ansioso", "neutro"
    fluidez: str      # "normal", "bloqueo", "lento"

class AnalisisSesion(typing_extensions.TypedDict):
    resumen_clinico: str
    roles_identificados: list[RolInfo]
    dialogo: list[SegmentoDialogo]

def transcribe_audio(audio_path: str, output_basename: str):
    print(f"--- 🧠 Procesando con Gemini: {output_basename} ---")
    
    # Usamos el nombre exacto que salió en tu lista
    model = genai.GenerativeModel("models/gemini-flash-latest")
    
    try:
        audio_file = genai.upload_file(audio_path)
        
        prompt = """
        Eres un transcripctor clínico estricto. Tu prioridad es la precisión temporal.
        
        TAREA:
        1. Identifica roles (Paciente/Profesional).
        2. Transcribe el audio SEGMENTO POR SEGMENTO. No resumas grandes bloques.
        3. Traduce al inglés.
        4. Detecta emociones/bloqueos.
        
        IMPORTANTE SOBRE TIEMPOS:
        - Los tiempos deben ser REALES relativos al audio.
        - No inventes duración. Si el audio dura 5 min, los tiempos no pueden superar eso.
        - Formato MM:SS.
        
        Responde en JSON estricto según el esquema.
        """

        result = model.generate_content(
            [audio_file, prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=AnalisisSesion
            )
        )
        
        data = json.loads(result.text)
        
        json_path = os.path.join(TRANSCRIPTIONS_DIR, f"{output_basename}_analysis.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        return {"status": "success", "data": data}

    except Exception as e:
        print(f"Error IA: {e}")
        return {"status": "error", "error": str(e)}