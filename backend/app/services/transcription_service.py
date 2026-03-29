import os
import json
import google.generativeai as genai
# Corregimos la ruta de importación según tu estructura de carpetas
from ..utils.time_utils import format_timestamp
import whisper
from dotenv import load_dotenv

# 1. Configuración Inicial
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Directorios de salida
TRANSCRIPTIONS_DIR = os.path.join(os.path.dirname(__file__), "../../transcriptions")
os.makedirs(TRANSCRIPTIONS_DIR, exist_ok=True)

# Inicializar Whisper
print("⌛ Cargando modelo Whisper...")
# "base" es el equilibrio ideal; cambia a "tiny" si necesitas más velocidad.
whisper_model = whisper.load_model("base") 
print("✅ Whisper listo.")

def transcribe_audio(audio_path: str, output_basename: str):
    print(f"--- 🎧 Procesando audio con Whisper: {output_basename} ---")
    
    try:
        # 2. Transcripción con Whisper
        result = whisper_model.transcribe(audio_path, language="es")
        raw_segments = result["segments"]
        
        if not raw_segments:
            return {"status": "error", "error": "No se detectó contenido en el audio."}

        # --- LÓGICA DE AGRUPACIÓN POR SILENCIOS ---
        grouped_segments = []
        current_seg = {
            "inicio": format_timestamp(raw_segments[0]["start"]),
            "fin": format_timestamp(raw_segments[0]["end"]),
            "texto_es": raw_segments[0]["text"].strip(),
            "end_raw": raw_segments[0]["end"]
        }

        for i in range(1, len(raw_segments)):
            silencio = raw_segments[i]["start"] - current_seg["end_raw"]
            
            # Si el silencio es menor a 1.8 segundos y el bloque no es gigante, los unimos
            if silencio < 1.8 and len(current_seg["texto_es"]) < 400:
                current_seg["texto_es"] += " " + raw_segments[i]["text"].strip()
                current_seg["fin"] = format_timestamp(raw_segments[i]["end"])
                current_seg["end_raw"] = raw_segments[i]["end"]
            else:
                grouped_segments.append(current_seg)
                current_seg = {
                    "inicio": format_timestamp(raw_segments[i]["start"]),
                    "fin": format_timestamp(raw_segments[i]["end"]),
                    "texto_es": raw_segments[i]["text"].strip(),
                    "end_raw": raw_segments[i]["end"]
                }
        grouped_segments.append(current_seg)

        # Preparamos el texto acumulado para la IA
        full_text_clean = ""
        for s in grouped_segments:
            full_text_clean += f"[{s['inicio']} - {s['fin']}] {s['texto_es']}\n"

        print(f"✅ Transcripción local terminada ({len(grouped_segments)} bloques agrupados).")

        # 3. Análisis con Gemini Flash
        print("--- 🧠 Analizando con Gemini Flash (Timeout extendido) ---")
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
        Actúa como un psicólogo clínico experto y traductor profesional. Tu objetivo es procesar una transcripción agrupada de una sesión psicoterapéutica.

        REGLAS CRÍTICAS DE SEGMENTACIÓN Y ROLES:
        1. IDENTIFICACIÓN DE ROLES: Analiza el contexto de cada frase. El 'Terapeuta' suele ser quien hace las preguntas, guía la sesión o realiza intervenciones. El 'Paciente' es quien responde, relata su experiencia o es el foco de la entrevista. 
        2. CONSISTENCIA: No asignes el mismo rol a toda la sesión a menos que sea un monólogo. Identifica los cambios de turno de palabra.
        3. PRECISIÓN DE BLOQUES: Debes procesar exactamente {len(grouped_segments)} bloques. Si detectas que dentro de un bloque hay un cambio evidente de hablante que Whisper no separó bien, asigna el rol del hablante que predomine en ese tiempo específico.

        TAREA:
        1. Para cada bloque de tiempo:
        - Identifica el Rol ('Paciente' o 'Terapeuta').
        - Determina el nombre o etiqueta del 'hablante' (ej: 'Psicólogo Marco', 'Entrevistador', 'Paciente').
        - Analiza la emoción predominante (ej: Ansiedad, Neutro, Alegría, Reflexión).
        - Evalúa la fluidez física: 'Normal', 'Lenta' (pausas largas) o 'Bloqueo' (tartamudeo o interrupciones).
        2. Traduce el contenido íntegramente al inglés (texto_en).
        3. Redacta un resumen_clinico profundo basado en la narrativa y evalúa el riesgo.

        TRANSCRIPCIÓN:
        {full_text_clean}

        Responde ESTRICTAMENTE en JSON con esta estructura:
        {{
            "resumen_clinico": "...",
            "riesgo": "Bajo/Medio/Alto",
            "dialogo": [
                {{
                    "hablante": "...",
                    "rol": "Paciente/Terapeuta",
                    "emocion": "...",
                    "fluidez": "Normal/Lenta/Bloqueo",
                    "texto_en": "..."
                }}
            ]
        }}
        """

        # Timeout de 150 segundos para evitar errores 503 en audios largos
        gemini_response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1
            ),
            request_options={"timeout": 150}
        )
        
        if not gemini_response.candidates or gemini_response.candidates[0].finish_reason == 4:
            return {"status": "error", "error": "La IA bloqueó el contenido por seguridad."}

        raw_text = gemini_response.text
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0]
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0]

        analysis_data = json.loads(raw_text.strip())
        dialogo_ia = analysis_data.get("dialogo", [])

        # 4. Fusión de datos (Whisper Agrupado + Gemini)
        for i in range(len(grouped_segments)):
            if i < len(dialogo_ia):
                info_ia = dialogo_ia[i]
                grouped_segments[i]["hablante"] = info_ia.get("hablante", "Hablante")
                grouped_segments[i]["rol"]      = info_ia.get("rol", "Desconocido")
                grouped_segments[i]["emocion"]  = info_ia.get("emocion", "Neutral")
                grouped_segments[i]["fluidez"]  = info_ia.get("fluidez", "Normal")
                grouped_segments[i]["texto_en"] = info_ia.get("texto_en", "")
            else:
                # Fallback para segmentos finales
                grouped_segments[i]["rol"] = grouped_segments[i-1]["rol"] if i > 0 else "Desconocido"
                grouped_segments[i]["hablante"] = "Hablante"
                grouped_segments[i]["texto_en"] = "Translation missing"

        final_output = {
            "resumen": analysis_data.get("resumen_clinico", "No disponible"),
            "riesgo": analysis_data.get("riesgo", "No evaluado"),
            "dialogo": grouped_segments
        }

        # 5. Guardado
        output_file = os.path.join(TRANSCRIPTIONS_DIR, f"{output_basename}_analysis.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(final_output, f, ensure_ascii=False, indent=2)

        print(f"✅ Proceso completado con éxito. Archivo: {output_file}")
        return {"status": "success", "data": final_output}

    except Exception as e:
        print(f"❌ Error crítico: {e}")
        return {"status": "error", "error": str(e)}