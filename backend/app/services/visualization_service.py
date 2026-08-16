import os
import json
import librosa
import numpy as np
from ..utils.time_utils import time_str_to_seconds

VISUALIZATIONS_DIR = os.path.join(os.path.dirname(__file__), "../../visualizations")
TRANSCRIPTIONS_DIR = os.path.join(os.path.dirname(__file__), "../../transcriptions")
os.makedirs(VISUALIZATIONS_DIR, exist_ok=True)

def analyze_rhythm(audio_path: str, output_basename: str):
    print(f"--- 📊 Analizando señales físicas: {output_basename} ---")
    
    # Cargamos el audio con librosa
    y, sr = librosa.load(audio_path, sr=None)
    
    # Calculamos la energía (RMS) para detectar silencios físicos
    rms = librosa.feature.rms(y=y)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)

    # Cargar análisis de IA previo
    json_ai_path = os.path.join(TRANSCRIPTIONS_DIR, f"{output_basename}_analysis.json")
    segmentos_interes = []
    
    if os.path.exists(json_ai_path):
        with open(json_ai_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for seg in data.get("dialogo", []):
                s = time_str_to_seconds(seg.get("inicio", "00:00"))
                e = time_str_to_seconds(seg.get("fin", "00:00"))
                
                # Guardamos info de CUALQUIER hablante para el gráfico
                rol = str(seg.get("rol", "")).lower()
                segmentos_interes.append({
                    "rango": (s, e),
                    "es_paciente": "paciente" in rol,
                    # AQUI LEEMOS EL VALOR NUMÉRICO CONTINUO PARA EL GRÁFICO
                    "fluidez_ia": seg.get("nivel_fluidez", 0.5) 
                })

    rhythm_data = []
    prev_type = None
    rms_mean = np.mean(rms)
    
    for t, val in zip(times, rms):
        tipo = "silencio" # Por defecto
        en_segmento = False
        
        for interv in segmentos_interes:
            start, end = interv["rango"]
            if (start - 0.1) <= t <= (end + 0.1):
                en_segmento = True
                
                # Aseguramos que la fluidez sea un número flotante
                try:
                    fluidez_val = float(interv.get("fluidez_ia", 0.5))
                except (ValueError, TypeError):
                    fluidez_val = 0.5

                # Lógica de colores/tipos actualizada a números
                if val < 0.005: 
                    tipo = "pausa"
                elif not interv["es_paciente"]:
                    tipo = "terapeuta" # Color distinto para el terapeuta
                
                # Rango de Baja Fluidez (Lenta o Bloqueo: <= 0.0)
                elif fluidez_val <= 0.0:
                    tipo = "fluidez_alterada"
                
                # Rango de Alta Fluidez (> 1.0) o Pico físico de energía
                elif fluidez_val > 1.0 or val > (rms_mean * 2):
                    tipo = "acelerado"
                
                # Rango Normal (0.1 a 1.0)
                else:
                    tipo = "normal_paciente"
                
                break
        
        # Guardar solo cambios de estado (compresión de datos)
        if tipo != prev_type:
            rhythm_data.append({"timestamp": round(float(t), 2), "tipo": tipo})
            prev_type = tipo

    # Guardar JSON de ritmo
    out_path = os.path.join(VISUALIZATIONS_DIR, f"{output_basename}_rhythm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rhythm_data, f, ensure_ascii=False)

    return {"data": rhythm_data}