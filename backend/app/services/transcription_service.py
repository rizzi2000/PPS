import os
import json
import google.generativeai as genai
from ..utils.time_utils import format_timestamp
import whisper
from dotenv import load_dotenv

# 1. Configuración Inicial
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

TRANSCRIPTIONS_DIR = os.path.join(os.path.dirname(__file__), "../../transcriptions")
os.makedirs(TRANSCRIPTIONS_DIR, exist_ok=True)

print("⌛ Cargando modelo Whisper...")
whisper_model = whisper.load_model("base")
print("✅ Whisper listo.")

def transcribe_audio(audio_path: str, output_basename: str):
    print(f"--- 🎧 Procesando audio con Whisper: {output_basename} ---")
    
    try:
        # 2. Transcripción con Whisper
        result = whisper_model.transcribe(audio_path, language="es")
        
        segments_frontend = []
        full_text_clean = ""

        for segment in result["segments"]:
            start_fmt = format_timestamp(segment["start"])
            end_fmt = format_timestamp(segment["end"])
            text = segment["text"].strip()
            
            full_text_clean += f"[{start_fmt}] {text}\n"
            
            segments_frontend.append({
                "inicio": start_fmt,
                "fin": end_fmt,
                "texto": text,
                "hablante": "Analizando..." 
            })

        print("✅ Transcripción local terminada.")

        # 3. Análisis con Gemini
        print("--- 🧠 Analizando con Gemini Flash ---")
        model = genai.GenerativeModel(
            model_name="gemini-flash-latest",
            safety_settings={
                "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
            }
        )
        
        prompt = f"""
        Actúa como un psicólogo experto. Analiza esta transcripción.
        
        TAREA:
        1. Para cada una de las {len(segments_frontend)} frases, identifica si el hablante es 'Terapeuta' o 'Paciente'.
        2. Genera un resumen clínico.
        3. Evalúa el riesgo.
        
        TRANSCRIPCIÓN:
        {full_text_clean}
        
        Responde estrictamente en JSON:
        {{
            "resumen_clinico": "...",
            "riesgo": "...",
            "roles_detectados": ["Terapeuta", "Paciente", ...]
        }}
        """

        gemini_response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        
        # Validación de seguridad
        if not gemini_response.candidates or gemini_response.candidates[0].finish_reason == 4:
            return {"status": "error", "error": "Contenido bloqueado por seguridad de Google."}

        # Limpieza y carga de JSON
        raw_text = gemini_response.text
        # Quitamos posibles markdowns de triple comilla si existen
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0]
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0]

        analysis_data = json.loads(raw_text.strip())
        roles = analysis_data.get("roles_detectados", [])

        # 4. Fusión de datos (Whisper + Gemini)
        for i, segment in enumerate(segments_frontend):
            if i < len(roles):
                segment["hablante"] = roles[i]
            else:
                # Si Gemini mandó menos, intentamos deducir o ponemos el último conocido
                segment["hablante"] = roles[-1] if roles else "Desconocido"

        final_output = {
            "resumen": analysis_data.get("resumen_clinico", "No disponible"),
            "riesgo": analysis_data.get("riesgo", "No evaluado"),
            "transcripcion": segments_frontend
        }

        # 5. Guardar y retornar
        output_file = os.path.join(TRANSCRIPTIONS_DIR, f"{output_basename}_analysis.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_output, f, ensure_ascii=False, indent=2)

        print("✅ Todo el proceso completado con éxito.")
        return {"status": "success", "data": final_output}

    except Exception as e:
        print(f"❌ Error crítico: {e}")
        return {"status": "error", "error": str(e)}