# NeuroVoice — Análisis de sesiones terapéuticas

Procesa audios de sesiones de psicoterapia y produce: transcripción sincronizada
(español + inglés), identificación de hablantes (terapeuta / paciente), métricas
acústicas del paciente y un resumen clínico.

**Principio de diseño:** las métricas se **miden** sobre la señal con DSP.
El LLM sólo traduce, clasifica emoción del texto y redacta el resumen — nunca
inventa números de ritmo ni adivina quién habla.

---

## Arquitectura

```
audio ──► ffmpeg ──► PCM 16 kHz mono (se decodifica UNA sola vez)
                          │
      ┌───────────────────┼────────────────────┬───────────────────┐
      ▼                   ▼                    ▼                   ▼
  peaks (numpy)     faster-whisper        diarización         prosodia
   ~4 ms            + VAD + palabras     MFCC/ECAPA           numpy/FFT
      │                   │                    │                   │
      └── waveform ◄──────┴────► corte por turnos ◄────────────────┘
          (0.3 s)                      │
                                       ▼
                        Gemini/Claude (chunks en paralelo)
                            traducción + emoción + resumen
```

Cada etapa emite su resultado por **SSE** apenas termina. La interfaz nunca
espera al final: el waveform aparece a los pocos segundos, la transcripción se
va llenando en vivo y las métricas se pintan cuando están listas.

---

## Stack

| Capa | Tecnología | Por qué |
|---|---|---|
| API | **FastAPI** + Uvicorn | async, SSE nativo, tipado |
| ASR | **faster-whisper** (CTranslate2) | ~4× más rápido que `openai-whisper` en CPU con `int8`, y da timestamps por palabra |
| VAD | **Silero** (integrado en faster-whisper) | saltea silencios: −20/40 % de cómputo en sesiones con pausas largas |
| Diarización | **scikit-learn** (clustering) + MFCC, o **ECAPA-TDNN** opcional | separa voces por señal, no por texto |
| Prosodia | **numpy** / **scipy** / **librosa** | F0 por autocorrelación FFT, RMS, tasa silábica |
| LLM | **Gemini Flash** (o **Claude**) | traducción, emoción textual, resumen clínico — intercambiable con `LLM_PROVIDER` |
| Front | **React 19** + Vite | — |
| Waveform | **wavesurfer.js 7** | acepta peaks precalculados → dibuja sin decodificar |
| Gráficos | **Recharts** | paleta validada para daltonismo, modo claro/oscuro |

---

## Requisitos previos

1. **Python 3.10+** — probado en 3.13
2. **Node.js 18+**
3. **ffmpeg** en el `PATH` — imprescindible

```powershell
# Windows (una de estas)
winget install Gyan.FFmpeg
choco install ffmpeg

ffmpeg -version   # debe responder
```

---

## Instalación

### Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Creá `backend/.env` (o en la raíz del repo). Ver [.env.example](backend/.env.example)
para la lista completa:

```ini
GEMINI_API_KEY=tu_api_key_de_google_ai_studio

# Opcional: usar Claude en vez de Gemini (requiere créditos de API aparte)
# ANTHROPIC_API_KEY=tu_api_key_de_anthropic

# Opcionales
WHISPER_MODEL=small          # tiny | base | small | medium | large-v3
WHISPER_COMPUTE=int8         # int8 | int8_float32 | float16 (GPU)
WHISPER_DEVICE=cpu           # cuda si tenés GPU NVIDIA
CPU_THREADS=4
MAX_UPLOAD_MB=300
```

### Elegir proveedor de LLM

El LLM sólo traduce, clasifica emoción y redacta el resumen. Si falla o se queda
sin cuota, **el análisis de señal se completa igual**: transcripción, hablantes
y métricas no dependen de él.

**El proveedor se elige solo** según qué API key esté cargada (prefiere Claude si
están las dos). `LLM_PROVIDER=claude|gemini` fuerza uno.

| | Gemini Flash (por defecto) | Claude (`claude-opus-5`) |
|---|---|---|
| Costo | Gratis, con cuota diaria | ~US$0.15–0.80 por sesión de 25 min según modelo |
| Emociones fuera del enum | Se corrigen en código | Imposibles: el enum va en el esquema de salida |
| Contenido sensible | Se desactivan los filtros | Fallback automático de servidor ante rechazo |

> **Claude Pro/Max NO habilita la API.** Son productos con facturación separada:
> la suscripción cubre claude.ai y Claude Code, no llamadas desde tu backend.
> Los créditos de API se compran en <https://console.anthropic.com>.

La API key de Gemini se saca gratis en <https://aistudio.google.com/apikey>.

**Sobre la cuota gratuita.** El límite es por día *y por modelo* (20 requests/día
en el flash más nuevo). Para estirarlo, el sistema reparte la carga:

| Tarea | Modelo | Por qué |
|---|---|---|
| Traducción + emoción | `gemini-flash-lite-latest` | muchas requests, tarea mecánica; cupo propio |
| Resumen clínico | `gemini-flash-latest` | una sola request, es donde importa la calidad |

Si igual se agota, el resumen reintenta con el modelo liviano antes de rendirse,
y ante un límite por minuto reintenta con backoff. En el peor caso quedan vacíos
sólo el resumen y la traducción: **el análisis de señal se completa siempre**.

**Nota Windows:** ECAPA se descarga de HuggingFace y speechbrain intenta crear
un symlink, que Windows bloquea sin modo desarrollador (`WinError 1314`). El
código ya fuerza copia en vez de enlace, así que no hace falta hacer nada.

### Frontend

```powershell
cd frontend
npm install
```

---

## Correr el proyecto

Dos terminales:

```powershell
# Terminal 1 — backend  (http://127.0.0.1:8000)
cd backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --reload --port 8000
```

```powershell
# Terminal 2 — frontend (http://localhost:5173)
cd frontend
npm run dev
```

Abrí <http://localhost:5173>. La primera ejecución descarga el modelo Whisper
(~480 MB para `small`); las siguientes arrancan al instante.

Docs interactivas de la API: <http://127.0.0.1:8000/docs>

---

## Ver qué modelos se están usando

```powershell
curl http://127.0.0.1:8000/api/health
```

```json
{
  "asr":          { "modelo": "small", "compute_type": "int8", "device": "cpu" },
  "diarizacion":  { "backend": "ecapa" },
  "llm": {
    "proveedor": "gemini",
    "modelos":   { "resumen": "gemini-flash-latest",
                   "traduccion": "gemini-flash-lite-latest" },
    "version_resuelta": { "gemini-flash-lite-latest": "gemini-3.5-flash-lite" }
  }
}
```

`modelos` son los alias que pediste; **`version_resuelta` es el modelo concreto
que efectivamente respondió**. La diferencia importa: `gemini-flash-latest` es un
alias móvil que hoy apunta a `gemini-3.7-flash` y mañana puede apuntar a otro.
Se completa después de la primera llamada real de cada modelo.

`diarizacion.backend` dice `mfcc` hasta que ECAPA termina de cargar (~40 s
después de arrancar el servidor); si sigue diciendo `mfcc` después de eso, ECAPA
no se pudo cargar.

**Cada sesión guarda su propia procedencia** en `results/{job_id}.json`, bajo la
clave `modelos`. Para un informe académico eso es lo que permite decir con qué se
generó cada resultado, y reproducirlo después.

---

## Atajos de teclado

| Tecla | Acción |
|---|---|
| `Espacio` | reproducir / pausar |
| `←` `→` | ±5 segundos |
| `Shift` + `←` `→` | ±30 segundos |

Hacer clic en cualquier línea de la transcripción salta a ese momento del audio.

---

## Rendimiento medido

Medido en un **Intel i3-10110U (2 núcleos / 4 hilos), 8 GB RAM, sin GPU**, con
los modelos ya precargados, sobre una entrevista real de **5 min 37 s**:

| Etapa | Tiempo | Escala con |
|---|---|---|
| Decodificación + peaks | **0.7 s** | duración · **acá ya se ve el waveform** |
| Transcripción (`small`, int8) | 110 s | duración (≈3× tiempo real) |
| Diarización (ECAPA) | 28 s | duración (≈12× tiempo real) |
| Prosodia | 0.8 s | duración |
| Traducción + emoción | 27 s | nº de enunciados (chunks paralelos) |
| Resumen clínico | ~20 s | casi constante |
| **Total** | **≈ 3 min** | ≈ 1.8× tiempo real |

**Referencia rápida** (misma máquina, con ECAPA):

| Audio | Waveform visible | Transcripción completa | Todo listo |
|---|---|---|---|
| 5 min | < 1 s | ~1 min 40 s | **~2 min 50 s** |
| 15 min | ~2 s | ~5 min | ~7 min 30 s |
| 45 min | ~5 s | ~15 min | ~22 min |

Nada de eso es tiempo de espera con la pantalla vacía: el waveform aparece de
inmediato y la transcripción se va llenando enunciado por enunciado.

### Cómo acelerarlo más

1. **GPU NVIDIA** — `WHISPER_DEVICE=cuda`, `WHISPER_COMPUTE=float16`.
   Es el salto más grande: de ~3× a ~20× tiempo real, y ECAPA pasa a ser gratis.
2. **`distil-whisper`** — `WHISPER_MODEL=distil-large-v3` da calidad cercana a
   `large` a velocidad de `small`.
3. **Modelo más chico** — `WHISPER_MODEL=base` casi duplica la velocidad, a
   costa de precisión. No lo recomiendo: es lo que hacía ilegible la versión
   anterior.
4. **Sacar ECAPA** — el fallback MFCC es ~3× más rápido en diarización, pero
   falla con voces grabadas por un mismo micrófono lejano.
5. **Paralelizar por bloques** — partir el audio en trozos de 10 min y
   transcribirlos en procesos separados. Sólo conviene con 4+ núcleos.

---

## Estructura

```
backend/
  main.py                      API, CORS, warmup del modelo
  app/core/config.py           configuración y rutas
  app/core/jobs.py             registro de trabajos + bus de eventos SSE
  app/routes/audio.py          endpoints (upload, SSE, resultado, audio con Range)
  app/services/
    audio_io.py                decodificación única + peaks
    asr.py                     faster-whisper, palabras, corte por turnos
    diarize.py                 embeddings + clustering + asignación de roles
    prosody.py                 métricas acústicas reales
    llm.py                     Gemini/Claude: traducción, emoción, resumen
    pipeline.py                orquestación por etapas
frontend/src/
  App.jsx                      layout y estado general
  useAnalysis.js               máquina de estados alimentada por SSE
  api.js  utils.js  styles.css
  components/                  Player, Transcript, Metrics, Summary, Uploader
```

---

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/sessions` | sube el audio y arranca el análisis → `{job_id}` |
| `GET` | `/api/sessions/{id}/events` | SSE con progreso y resultados parciales |
| `GET` | `/api/sessions/{id}` | resultado completo (JSON) |
| `GET` | `/api/sessions/{id}/audio` | audio con soporte de `Range` |
| `GET` | `/api/sessions` | historial |
| `DELETE` | `/api/sessions/{id}` | borra sesión y audio |
| `GET` | `/api/health` | estado y modelo cargado |

---

## Interpretación de las métricas

- **`articulation_rate`** — sílabas por segundo descontando pausas. En español
  rioplatense lo normal ronda 5–7 síl/s.
- **`pause_ratio`** — proporción del turno ocupada por silencios > 150 ms.
- **`f0_mean` / `f0_std`** — tono medio y su variabilidad, en Hz.
- **`fluency_z`** — z-score **contra la línea de base del propio paciente**.
  0 = su ritmo habitual; negativo = más lento y entrecortado.
- **`arousal_z`** — activación: energía + variabilidad tonal + velocidad.

La normalización por hablante es deliberada: comparar el ritmo de dos personas
distintas en una escala absoluta no significa nada clínicamente.

> Herramienta de apoyo. No reemplaza el juicio clínico profesional, y las
> etiquetas emocionales del LLM son orientativas, no diagnósticas.
