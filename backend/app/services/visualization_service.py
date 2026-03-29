import os
import json
import librosa
import numpy as np
from ..utils.time_utils import time_str_to_seconds

# Asegúrate de que las rutas sean correctas (2 niveles atrás)
VISUALIZATIONS_DIR = os.path.join(os.path.dirname(__file__), "../../visualizations")
TRANSCRIPTIONS_DIR = os.path.join(os.path.dirname(__file__), "../../transcriptions")
os.makedirs(VISUALIZATIONS_DIR, exist_ok=True)

def analyze_rhythm(audio_path: str, output_basename: str):
    print(f"--- 📊 Analizando señales físicas: {output_basename} ---")
    
    # 1. Carga física del audio (Librosa)
    y, sr = librosa.load(audio_path, sr=None)
    hop_length = 512
    frame_length = 2048
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

    # 2. Intentar cargar filtro de IA
    json_ai_path = os.path.join(TRANSCRIPTIONS_DIR, f"{output_basename}_analysis.json")
    intervalos_paciente = []
    usar_filtro = False

    if os.path.exists(json_ai_path):
        try:
            with open(json_ai_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Buscamos segmentos del paciente (ignorando mayúsculas)
                dialogos = data.get("transcripcion", [])
                for seg in dialogos:
                    # Convertimos el rol a minúsculas para comparar
                    rol = seg.get("rol", "").lower().strip()
                    
                    # Aceptamos "paciente" o "patient" por si acaso
                    if "paciente" in rol or "patient" in rol:
                        s = time_str_to_seconds(seg.get("inicio", "00:00"))
                        e = time_str_to_seconds(seg.get("fin", "00:00"))
                        intervalos_paciente.append((s, e))
                
                # SOLO activamos el filtro si realmente encontramos al paciente
                if len(intervalos_paciente) > 0:
                    usar_filtro = True
                    print(f"✅ Filtro IA activado: {len(intervalos_paciente)} segmentos de paciente.")
                else:
                    print("⚠️ JSON encontrado pero no se detectó rol 'paciente'. Mostrando todo el audio.")
                    
        except Exception as e:
            print(f"⚠️ Error leyendo JSON de IA: {e}")
    else:
        print("ℹ️ No existe análisis de IA previo. Se mostrará todo el audio.")

    # 3. Clasificación y Filtrado
    rhythm_data = []
    prev_type = None
    rms_mean = np.mean(rms)
    
    for t, val in zip(times, rms):
        tipo = "normal"
        
        # Lógica de filtro:
        es_paciente = True
        if usar_filtro:
            es_paciente = False
            for (start, end) in intervalos_paciente:
                # Damos un margen de error pequeño (0.5s) para que no corte palabras
                if (start - 0.5) <= t <= (end + 0.5):
                    es_paciente = True
                    break
        
        # Si el filtro dice que no es paciente, marcamos como "ajeno"
        if not es_paciente:
            tipo = "ajeno"
        elif val < 0.01:
            tipo = "pausa"
        elif val > (rms_mean * 1.5):
            tipo = "acelerado"
        
        # Compresión: Solo guardamos si cambia el tipo de segmento
        if tipo != prev_type:
            rhythm_data.append({"timestamp": round(float(t), 2), "tipo": tipo})
            prev_type = tipo

    # Guardar
    out_path = os.path.join(VISUALIZATIONS_DIR, f"{output_basename}_rhythm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rhythm_data, f, ensure_ascii=False)

    return {"data": rhythm_data}