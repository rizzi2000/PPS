"""Capa LLM (Gemini): traducción, emoción textual y resumen clínico.

Cambio de responsabilidad respecto de la versión anterior:
  * YA NO le pedimos al LLM el hablante, el rol ni la fluidez numérica.
    Eso ahora sale de la señal (diarize.py / prosody.py).
  * El LLM hace lo único que hace bien acá: traducir e interpretar contenido.
  * Las emociones se validan contra un enum cerrado; lo que no matchea
    cae a "Neutral" en vez de contaminar el dataset con etiquetas libres.
  * Los chunks se procesan EN PARALELO. Son llamadas de red (I/O), así que
    los hilos escalan aunque la CPU tenga 2 núcleos: 6 chunks en paralelo
    bajan la etapa LLM de ~90 s a ~20 s.
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor

import google.generativeai as genai

from ..core.config import EMOTIONS, GEMINI_API_KEY, GEMINI_MODEL

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

CHUNK_SIZE = 25          # enunciados por request
MAX_PARALLEL = 6

_SAFETY = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
}

_EMO_LOOKUP = {e.lower(): e for e in EMOTIONS}


def _model():
    return genai.GenerativeModel(model_name=GEMINI_MODEL, safety_settings=_SAFETY)


def _parse_json(raw: str):
    raw = raw.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
        if m:
            raw = m.group(1)
    return json.loads(raw.strip())


def _normalize_emotion(value: str) -> str:
    """Fuerza la etiqueta al enum cerrado. Sin esto el LLM devuelve
    'Entusiasmo', 'Empatía', 'Determinación'... y las métricas no agregan."""
    if not value:
        return "Neutral"
    key = str(value).strip().lower()
    key = (key.replace("í", "i").replace("ó", "o").replace("á", "a")
              .replace("é", "e").replace("ú", "u"))
    if key in _EMO_LOOKUP:
        return _EMO_LOOKUP[key]
    aliases = {
        "neutro": "Neutral", "alegre": "Alegria", "felicidad": "Alegria",
        "entusiasmo": "Alegria", "agrado": "Alegria", "inspiracion": "Alegria",
        "miedo": "Ansiedad", "preocupacion": "Ansiedad", "nervios": "Ansiedad",
        "angustia": "Ansiedad", "frustacion": "Enojo", "frustracion": "Enojo",
        "ira": "Enojo", "molestia": "Enojo", "pena": "Tristeza",
        "dolor": "Tristeza", "melancolia": "Tristeza", "duda": "Confusion",
        "seguridad": "Certeza", "determinacion": "Certeza",
        "reflexivo": "Reflexion", "interes": "Reflexion", "empatia": "Reflexion",
        "relajacion": "Neutral", "calma": "Neutral",
    }
    return aliases.get(key, "Neutral")


def _chunk_prompt(items: list[dict]) -> str:
    lines = "\n".join(
        f'{i}. [{it["speaker_label"]}] {it["text"]}' for i, it in enumerate(items)
    )
    return f"""Sos un traductor profesional y psicólogo clínico. Procesá estos enunciados de una sesión de psicoterapia en español.

Para CADA enunciado, devolvé:
- "i": el índice exacto que te di.
- "en": traducción fiel al inglés (natural, no literal).
- "emocion": UNA sola etiqueta, obligatoriamente de esta lista exacta:
  {", ".join(EMOTIONS)}
- "tema": tópico en 1-3 palabras (ej: "familia", "trabajo", "insomnio").

No agregues ni omitas enunciados. Devolvé exactamente {len(items)} objetos.

ENUNCIADOS:
{lines}

Respondé SOLO JSON: {{"items": [{{"i": 0, "en": "...", "emocion": "...", "tema": "..."}}]}}"""


def _process_chunk(args):
    offset, items = args
    try:
        resp = _model().generate_content(
            _chunk_prompt(items),
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json", temperature=0.1),
            request_options={"timeout": 120},
        )
        data = _parse_json(resp.text)
        out = {}
        for it in data.get("items", []):
            idx = int(it.get("i", -1))
            if 0 <= idx < len(items):
                out[offset + idx] = {
                    "text_en": it.get("en", ""),
                    "emocion": _normalize_emotion(it.get("emocion")),
                    "tema": (it.get("tema") or "").strip().lower()[:30],
                }
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[LLM] chunk {offset} falló: {e}")
        return {}


def translate_and_tag(segments: list[dict], on_chunk=None) -> None:
    """Enriquece los segmentos in-place con traducción, emoción y tema."""
    if not GEMINI_API_KEY:
        for s in segments:
            s.setdefault("text_en", "")
            s.setdefault("emocion", "Neutral")
        return

    payload = [{"text": s["text"], "speaker_label": s.get("role", "?")} for s in segments]
    chunks = [(i, payload[i:i + CHUNK_SIZE]) for i in range(0, len(payload), CHUNK_SIZE)]

    done = 0
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        for result in pool.map(_process_chunk, chunks):
            for idx, vals in result.items():
                segments[idx].update(vals)
            done += 1
            if on_chunk:
                on_chunk(done, len(chunks))

    for s in segments:
        s.setdefault("text_en", "")
        s.setdefault("emocion", "Neutral")
        s.setdefault("tema", "")


def clinical_summary(segments: list[dict], stats: dict) -> dict:
    """Resumen clínico apoyado en las métricas objetivas ya calculadas."""
    if not GEMINI_API_KEY:
        return {"resumen": "GEMINI_API_KEY no configurada.", "riesgo": "No evaluado",
                "temas": [], "observaciones": ""}

    transcript = "\n".join(
        f'[{s["start"]:.0f}s] {s.get("role", "?")}: {s["text"]}' for s in segments
    )[:60000]

    metrics_txt = json.dumps(stats, ensure_ascii=False, indent=1)

    prompt = f"""Sos un psicólogo clínico. Analizá esta sesión de psicoterapia.

MÉTRICAS ACÚSTICAS OBJETIVAS (medidas sobre la señal, no estimadas):
{metrics_txt}

TRANSCRIPCIÓN:
{transcript}

Devolvé JSON con:
- "resumen": 150-250 palabras EN ESPAÑOL. Narrativa clínica: motivo de consulta,
  temas centrales, estado emocional, recursos y dificultades observadas.
- "riesgo": "Bajo" | "Medio" | "Alto" (riesgo clínico global).
- "justificacion_riesgo": 1-2 frases EN ESPAÑOL explicando el nivel asignado.
- "temas": array de 4-7 temas principales, en español, 1-3 palabras cada uno.
- "indicadores": array de 3-5 observaciones clínicas concretas EN ESPAÑOL,
  citando momentos (segundos) cuando aplique.
- "sugerencias": array de 2-4 líneas de trabajo posibles para próximas sesiones.

TODO el texto debe estar en ESPAÑOL. Respondé SOLO JSON."""

    try:
        resp = _model().generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json", temperature=0.25),
            request_options={"timeout": 180},
        )
        data = _parse_json(resp.text)
        return {
            "resumen": data.get("resumen", ""),
            "riesgo": data.get("riesgo", "No evaluado"),
            "justificacion_riesgo": data.get("justificacion_riesgo", ""),
            "temas": data.get("temas", []),
            "indicadores": data.get("indicadores", []),
            "sugerencias": data.get("sugerencias", []),
        }
    except Exception as e:  # noqa: BLE001
        print(f"[LLM] resumen falló: {e}")
        return {"resumen": f"No se pudo generar el resumen: {e}",
                "riesgo": "No evaluado", "temas": [], "indicadores": [],
                "sugerencias": []}
