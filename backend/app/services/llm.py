"""Capa LLM: traducción, emoción textual y resumen clínico.

Soporta dos proveedores. Por defecto se elige solo segun que API key haya
configurada; LLM_PROVIDER lo fuerza:

    LLM_PROVIDER=claude   -> API de Anthropic (necesita ANTHROPIC_API_KEY)
    LLM_PROVIDER=gemini   -> Google Gemini (necesita GEMINI_API_KEY)

OJO: la suscripcion Claude Pro/Max no habilita la API. Son productos con
facturacion separada; la API se paga con creditos en console.anthropic.com.

La interfaz pública no cambia: `translate_and_tag()` y `clinical_summary()`.
El pipeline no sabe ni le importa qué proveedor está detrás.

Responsabilidad del LLM en este sistema: traducir e interpretar contenido.
NO mide ritmo, NO identifica hablantes, NO calcula fluidez — eso sale de la
señal (diarize.py / prosody.py). Un modelo de lenguaje no escucha el audio.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from ..core.config import EMOTIONS

# Anthropic
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Google
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
# El plan gratuito limita requests por dia Y POR MODELO. Mandar las traducciones
# (muchas requests) al modelo lite reparte la carga en dos cupos distintos y deja
# el modelo bueno libre para el resumen, que es una sola llamada y la que mas
# calidad necesita.
GEMINI_MODEL_BULK = os.getenv("GEMINI_MODEL_BULK", "gemini-flash-lite-latest")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def _pick_provider() -> str:
    """Elige proveedor segun las credenciales disponibles.

    LLM_PROVIDER fuerza uno explicitamente. Sin esa variable se usa el que
    tenga API key: Claude si esta configurada, si no Gemini. Asi el proyecto
    arranca con lo que haya sin tocar codigo.

    Nota: la suscripcion Claude Pro/Max NO habilita la API. El acceso a la API
    se factura aparte desde console.anthropic.com.
    """
    forced = os.getenv("LLM_PROVIDER", "").strip().lower()
    if forced in ("claude", "gemini"):
        return forced
    if ANTHROPIC_API_KEY:
        return "claude"
    if GEMINI_API_KEY:
        return "gemini"
    return "claude"


PROVIDER = _pick_provider()

CHUNK_SIZE = int(os.getenv("LLM_CHUNK_SIZE", "40"))
MAX_PARALLEL = int(os.getenv("LLM_MAX_PARALLEL", "3" if PROVIDER == "gemini" else "6"))

RIESGOS = ["Bajo", "Medio", "Alto"]

_EMO_LOOKUP = {e.lower(): e for e in EMOTIONS}


# ---------------------------------------------------------------------------
# Esquemas de salida.
#
# El enum de emociones va DENTRO del esquema, así el proveedor garantiza
# estructuralmente una etiqueta válida en vez de que la corrijamos después.
# Esto elimina el zoológico de etiquetas libres ("Entusiasmo", "Empatía",
# "Determinación"...) que devolvía la versión anterior.
# ---------------------------------------------------------------------------

CHUNK_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "en": {"type": "string"},
                    "emocion": {"type": "string", "enum": EMOTIONS},
                    "tema": {"type": "string"},
                },
                "required": ["i", "en", "emocion", "tema"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        "riesgo": {"type": "string", "enum": RIESGOS},
        "justificacion_riesgo": {"type": "string"},
        "temas": {"type": "array", "items": {"type": "string"}},
        "indicadores": {"type": "array", "items": {"type": "string"}},
        "sugerencias": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["resumen", "riesgo", "justificacion_riesgo",
                 "temas", "indicadores", "sugerencias"],
    "additionalProperties": False,
}


def is_configured() -> bool:
    return bool(ANTHROPIC_API_KEY if PROVIDER == "claude" else GEMINI_API_KEY)


# Version concreta que devolvio el proveedor en la ultima llamada.
# "gemini-flash-latest" es un alias: sin esto no hay forma de saber que modelo
# corrio realmente, lo cual importa para poder citar la fuente en el informe.
_resolved: dict[str, str] = {}


def describe() -> dict:
    """Que proveedor y modelos estan en uso, para /api/health y para dejar
    constancia en el JSON de cada sesion."""
    if PROVIDER == "claude":
        cfg = {"resumen": CLAUDE_MODEL, "traduccion": CLAUDE_MODEL}
    else:
        cfg = {"resumen": GEMINI_MODEL, "traduccion": GEMINI_MODEL_BULK}
    return {
        "proveedor": PROVIDER,
        "configurado": is_configured(),
        "modelos": cfg,
        # Se completa despues de la primera llamada real.
        "version_resuelta": dict(_resolved),
        "chunk_size": CHUNK_SIZE,
        "paralelismo": MAX_PARALLEL,
    }


# ---------------------------------------------------------------------------
# Prompts (compartidos por ambos proveedores)
# ---------------------------------------------------------------------------

SYSTEM_TRANSLATE = (
    "Sos un traductor profesional especializado en material clínico. "
    "Traducís transcripciones de sesiones de psicoterapia en español rioplatense "
    "al inglés, de forma fiel y natural, preservando el registro coloquial y las "
    "vacilaciones propias del habla espontánea. También clasificás la emoción "
    "predominante del texto."
)

SYSTEM_SUMMARY = (
    "Sos un psicólogo clínico que redacta notas de sesión. Escribís SIEMPRE en "
    "español rioplatense, con lenguaje técnico pero legible. Te apoyás tanto en el "
    "contenido de la sesión como en las métricas acústicas objetivas que se te dan."
)


def _chunk_prompt(items):
    lines = "\n".join(
        "{}. [{}] {}".format(i, it["speaker_label"], it["text"])
        for i, it in enumerate(items)
    )
    n = len(items)
    emociones = ", ".join(EMOTIONS)
    return f"""Procesá estos {n} enunciados de una sesión de psicoterapia.

Para CADA enunciado devolvé:
- "i": el índice exacto que te di (no lo cambies).
- "en": traducción fiel al inglés, natural y no literal.
- "emocion": UNA etiqueta de la lista permitida.
- "tema": tópico en 1 a 3 palabras, en español (ej: "familia", "trabajo", "insomnio").

Devolvé exactamente {n} objetos, uno por enunciado. No agregues ni omitas.

ENUNCIADOS:
{lines}

Respondé SOLO con este JSON, sin texto alrededor:
{{"items": [{{"i": 0, "en": "...", "emocion": "...", "tema": "..."}}]}}

"emocion" debe ser exactamente una de: {emociones}"""


def _summary_prompt(segments, stats):
    transcript = "\n".join(
        "[{:.0f}s] {}: {}".format(s["start"], s.get("role", "?"), s["text"])
        for s in segments
    )[:120000]
    metrics_txt = json.dumps(stats, ensure_ascii=False, indent=1)

    return f"""Analizá esta sesión de psicoterapia y redactá la nota clínica.

MÉTRICAS ACÚSTICAS OBJETIVAS (medidas sobre la señal, no estimadas):
{metrics_txt}

Cómo interpretarlas: en español rioplatense la tasa de articulación normal ronda
5-7 sílabas/s. `talk_share` es el porcentaje del tiempo total de habla.

TRANSCRIPCIÓN:
{transcript}

Devolvé:
- "resumen": 150-250 palabras. Motivo de consulta, temas centrales, estado
  emocional, recursos y dificultades observadas.
- "riesgo": nivel de riesgo clínico global.
- "justificacion_riesgo": 1-2 frases explicando por qué asignaste ese nivel.
- "temas": 4 a 7 temas principales, 1-3 palabras cada uno.
- "indicadores": 3 a 5 observaciones clínicas concretas, citando el segundo
  cuando corresponda.
- "sugerencias": 2 a 4 líneas de trabajo para próximas sesiones.

TODO en español."""


# ---------------------------------------------------------------------------
# Backend: Anthropic
# ---------------------------------------------------------------------------

_client = None


def _anthropic():
    global _client
    if _client is None:
        import anthropic
        # Sin argumentos: resuelve ANTHROPIC_API_KEY o el perfil de `ant auth login`.
        _client = anthropic.Anthropic()
    return _client


def _claude_json(system, prompt, schema, effort):
    """Una llamada con salida estructurada garantizada por esquema.

    Va con el fallback de servidor activado: el material clínico (ideación
    suicida, autolesiones) puede activar los clasificadores de seguridad, y sin
    fallback la sesión entera se quedaría sin resumen.
    """
    resp = _anthropic().beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={
            "format": {"type": "json_schema", "schema": schema},
            "effort": effort,
        },
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    if resp.stop_reason == "refusal":
        detail = getattr(resp, "stop_details", None)
        cat = getattr(detail, "category", None) if detail else None
        raise RuntimeError(
            "El modelo rechazó el contenido"
            + (" (categoría: {})".format(cat) if cat else "")
        )

    # El modelo que respondio puede diferir del pedido si actuo un fallback.
    _resolved[CLAUDE_MODEL] = getattr(resp, "model", CLAUDE_MODEL)

    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("Respuesta sin contenido de texto")
    return json.loads(text)


# ---------------------------------------------------------------------------
# Backend: Gemini
# ---------------------------------------------------------------------------

_SAFETY = {
    "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
}


def _gemini_json(system, prompt, schema, effort, model_name=None):
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=model_name or GEMINI_MODEL,
        system_instruction=system,
        safety_settings=_SAFETY,
    )
    resp = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.15,
        ),
        request_options={"timeout": 180},
    )
    # "gemini-flash-latest" es un alias movil; model_version trae la version
    # concreta que atendio la request (ej: "gemini-3.5-flash-lite").
    alias = model_name or GEMINI_MODEL
    _resolved[alias] = getattr(resp, "model_version", None) or alias

    raw = resp.text.strip()
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
        if m:
            raw = m.group(1).strip()
    return json.loads(raw)


def _coerce(data, schema):
    """Tolera que el proveedor devuelva el array sin el objeto contenedor.

    Gemini no aplica el esquema de salida, asi que a veces responde
    `[{...}]` en vez de `{"items": [{...}]}`. En Claude no pasa porque el
    esquema es vinculante, pero la correccion es inofensiva para ambos.
    """
    if not isinstance(data, list):
        return data
    array_props = [k for k, v in schema.get("properties", {}).items()
                   if v.get("type") == "array"]
    return {array_props[0]: data} if len(array_props) == 1 else data


def _is_rate_limit(exc) -> bool:
    txt = str(exc).lower()
    return "429" in txt or "quota" in txt or "rate limit" in txt or "resource_exhausted" in txt


def _is_daily_quota(exc) -> bool:
    """Cupo diario agotado: esperar no lo recupera, no tiene sentido reintentar."""
    return "perday" in str(exc).lower().replace("_", "").replace("-", "")


def _ask(system, prompt, schema, effort="high", attempts=3, bulk=False):
    """Ejecuta la consulta reintentando ante limite de tasa.

    Con Gemini gratuito el 429 es esperable: los chunks en paralelo consumen
    el cupo por minuto y la llamada siguiente rebota. Esperar y reintentar
    recupera la sesion en vez de dejarla sin resumen.
    """
    delay = 8.0
    for attempt in range(attempts):
        try:
            if PROVIDER == "gemini":
                mdl = GEMINI_MODEL_BULK if bulk else GEMINI_MODEL
                return _coerce(_gemini_json(system, prompt, schema, effort, mdl), schema)
            return _claude_json(system, prompt, schema, effort)
        except Exception as e:  # noqa: BLE001
            if not _is_rate_limit(e) or _is_daily_quota(e) or attempt == attempts - 1:
                raise
            print("[LLM/{}] limite de tasa, reintento {}/{} en {:.0f}s".format(
                PROVIDER, attempt + 1, attempts - 1, delay))
            time.sleep(delay)
            delay *= 2


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def _normalize_emotion(value):
    """Red de seguridad. Con el esquema activo casi nunca hace falta, pero
    protege si el proveedor devuelve algo fuera del enum."""
    if not value:
        return "Neutral"
    key = str(value).strip().lower()
    for a, b in (("í", "i"), ("ó", "o"), ("á", "a"), ("é", "e"), ("ú", "u")):
        key = key.replace(a, b)
    if key in _EMO_LOOKUP:
        return _EMO_LOOKUP[key]
    aliases = {
        "neutro": "Neutral", "alegre": "Alegria", "felicidad": "Alegria",
        "entusiasmo": "Alegria", "agrado": "Alegria", "inspiracion": "Alegria",
        "miedo": "Ansiedad", "preocupacion": "Ansiedad", "nervios": "Ansiedad",
        "angustia": "Ansiedad", "frustracion": "Enojo", "ira": "Enojo",
        "molestia": "Enojo", "pena": "Tristeza", "dolor": "Tristeza",
        "melancolia": "Tristeza", "duda": "Confusion", "seguridad": "Certeza",
        "determinacion": "Certeza", "reflexivo": "Reflexion",
        "interes": "Reflexion", "empatia": "Reflexion", "calma": "Neutral",
    }
    return aliases.get(key, "Neutral")


def _normalize_summary(data, empty):
    """Ajusta la forma de la respuesta del resumen.

    Sin esquema vinculante (ruta Gemini) el modelo devuelve variantes: "Moderado"
    en vez de "Medio", o un string donde se esperaba una lista. Con Claude el
    esquema lo impide, pero normalizar es inofensivo y protege ambas rutas.
    """
    out = {**empty, **{k: data.get(k, empty[k]) for k in empty}}

    riesgo = str(out.get("riesgo") or "").strip().lower()
    riesgo = riesgo.replace("í", "i").replace("á", "a").replace("é", "e")
    alias = {
        "bajo": "Bajo", "leve": "Bajo", "minimo": "Bajo", "nulo": "Bajo",
        "medio": "Medio", "moderado": "Medio", "intermedio": "Medio",
        "alto": "Alto", "elevado": "Alto", "severo": "Alto", "grave": "Alto",
    }
    out["riesgo"] = alias.get(riesgo, "No evaluado")

    for key in ("temas", "indicadores", "sugerencias"):
        val = out.get(key)
        if isinstance(val, str):
            # Un string donde iba una lista: lo partimos por saltos o viñetas.
            partes = [x.strip(" -*•") for x in re.split(r"[\n;]+", val)]
            out[key] = [x for x in partes if x]
        elif not isinstance(val, list):
            out[key] = []
        else:
            out[key] = [str(x).strip() for x in val if str(x).strip()]

    for key in ("resumen", "justificacion_riesgo"):
        if not isinstance(out.get(key), str):
            out[key] = ""

    return out


def _process_chunk(args):
    offset, items = args
    try:
        # Traducir es mecánico: esfuerzo bajo baja costo y latencia sin perder
        # calidad. El razonamiento profundo se reserva para el resumen.
        data = _ask(SYSTEM_TRANSLATE, _chunk_prompt(items), CHUNK_SCHEMA,
                    effort="low", bulk=True)
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
        print("[LLM/{}] chunk {} falló: {}: {}".format(
            PROVIDER, offset, type(e).__name__, e))
        return {}


def translate_and_tag(segments, on_chunk=None):
    """Enriquece los segmentos in-place con traducción, emoción y tema."""
    if not is_configured():
        for s in segments:
            s.setdefault("text_en", "")
            s.setdefault("emocion", "Neutral")
            s.setdefault("tema", "")
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


def clinical_summary(segments, stats):
    """Resumen clínico apoyado en las métricas objetivas ya calculadas."""
    empty = {"resumen": "", "riesgo": "No evaluado", "justificacion_riesgo": "",
             "temas": [], "indicadores": [], "sugerencias": []}

    if not is_configured():
        var = "ANTHROPIC_API_KEY" if PROVIDER == "claude" else "GEMINI_API_KEY"
        return {**empty, "resumen": "{} no configurada.".format(var)}

    prompt = _summary_prompt(segments, stats)
    try:
        return _normalize_summary(_ask(SYSTEM_SUMMARY, prompt, SUMMARY_SCHEMA), empty)
    except Exception as e:  # noqa: BLE001
        # Si se agoto el cupo diario del modelo principal, un resumen del modelo
        # liviano es mejor que ninguno: la sesion no se queda sin nota clinica.
        if PROVIDER == "gemini" and _is_rate_limit(e):
            print("[LLM/gemini] cupo agotado en {}, reintento con {}".format(
                GEMINI_MODEL, GEMINI_MODEL_BULK))
            try:
                out = _normalize_summary(
                    _ask(SYSTEM_SUMMARY, prompt, SUMMARY_SCHEMA, bulk=True), empty)
                out["resumen"] += (
                    "\n\n[Generado con el modelo liviano por límite de cuota.]")
                return out
            except Exception as e2:  # noqa: BLE001
                e = e2
        print("[LLM/{}] resumen falló: {}: {}".format(PROVIDER, type(e).__name__, e))
        return {**empty, "resumen": "No se pudo generar el resumen: {}".format(e)}
