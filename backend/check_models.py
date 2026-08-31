"""Lista los modelos de Gemini disponibles para la API key configurada.

Uso:  python check_models.py
"""
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise SystemExit("Falta GEMINI_API_KEY en el .env")

print(f"--- Modelos para la API key ...{api_key[-5:]} ---")

client = genai.Client(api_key=api_key)

try:
    for m in client.models.list():
        acciones = m.supported_actions or []
        if "generateContent" in acciones:
            print(f"  {m.name}")
except Exception as e:  # noqa: BLE001
    print(f"Error al listar modelos: {e}")
