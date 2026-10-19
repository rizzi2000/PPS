# Comparación de modelos: local contra nube

Script para medir, sobre un mismo conjunto de audios, **cuánto tarda y cuánto se equivoca** cada configuración. Responde la pregunta del Proyecto Integrador: si conviene un modelo local más rápido y cuánta precisión se pierde a cambio.

## Qué compara y qué mide

| Etapa | Configuraciones | Métricas |
|---|---|---|
| Transcripción | Whisper local `tiny`, `base`, `small`, `medium`, `large-v3`, `distil-large-v3`; Gemini en la nube (`gemini`) | Tiempo, factor de tiempo real, **WER** y **CER**, % de voz sin transcribir |
| Hablantes | ECAPA-TDNN (`ecapa`) y MFCC (`mfcc`), ambos locales | **DER** (desglosado en habla perdida, falsa alarma y confusión), cantidad de hablantes detectados contra la real |
| Emoción | Gemini (`gemini`) y modelos locales vía Ollama (`ollama:<modelo>`) | Tiempo, exactitud y kappa de Cohen contra etiquetas humanas, respuestas inválidas |

- **Factor de tiempo real (RTF):** segundos de proceso por segundo de audio. Un valor menor que 1 es más rápido que el audio.
- **WER:** porcentaje de palabras mal transcriptas (sustituidas, omitidas o agregadas). 0,10 = 10 % de error. Se compara sin mayúsculas, tildes ni puntuación.
- **CER:** lo mismo, contado por caracteres.
- **% sin transcribir:** porción del tiempo con voz (según la referencia) donde el modelo no escribió nada.
- **DER:** porcentaje del tiempo de habla mal atribuido (nadie, alguien de más o la persona equivocada).
- **Kappa:** acuerdo con las etiquetas humanas descontando el azar. 0 es azar, 1 es acuerdo perfecto.

## 1. Armar el corpus

Una carpeta por audio dentro de `benchmark/corpus/`:

```
benchmark/corpus/
├── caso01/
│   ├── audio.mp3           (o .wav, .m4a, .ogg, .flac, .webm)
│   └── referencia.json
├── caso02/
│   ├── audio.wav
│   └── referencia.json
└── ...
```

`referencia.json` es la verdad contra la que se compara, **anotada a mano**:

```json
{
  "meta": { "edad": "25-35", "perfil": "introvertido", "tipo": "individual", "hablantes_reales": 2 },
  "turnos": [
    { "inicio": 0.0,  "fin": 4.8,  "hablante": "T", "texto": "Hola, ¿cómo estás hoy?", "emocion": "Neutral" },
    { "inicio": 5.3,  "fin": 12.1, "hablante": "P", "texto": "Y... más o menos, la verdad que esta semana fue difícil.", "emocion": "Tristeza" }
  ]
}
```

- `inicio` y `fin` en segundos. `hablante` es cualquier etiqueta, siempre la misma para la misma persona.
- `texto`: lo que se dice, literal, incluidas muletillas ("eh", "este").
- `emocion` es opcional y debe ser una de: Neutral, Alegria, Tristeza, Enojo, Frustracion, Confusion. Sólo los turnos con emoción entran en esa comparación.
- `meta` es libre: se copia al CSV con el prefijo `meta_`, así después se filtra por edad, perfil o tipo de sesión.

**Recomendaciones para el corpus**

- Entre 10 y 20 audios de 3 a 10 minutos.
- Variar edades, personalidades (habla rápida o lenta, mucho o poco silencio), calidad de grabación y **sesiones grupales con 3 o más personas**.
- Anotar con un editor que muestre la onda y deje marcar tramos, como Audacity (*Etiquetas*), ELAN o Praat. Calcular unos 15 a 20 minutos de trabajo por minuto de audio.
- Para las emociones, conviene que dos personas etiqueten por separado y quedarse con los turnos donde coinciden.
- Usar audios con consentimiento o públicos. `benchmark/corpus/` y `benchmark/resultados/` están en `.gitignore` y no se suben al repositorio.

## 2. Preparar el entorno

Desde `backend/`, con el mismo `venv` de la app:

```powershell
.\venv\Scripts\Activate.ps1
pip install rapidfuzz        # opcional: acelera mucho el cálculo de WER/CER
```

- **Gemini** (transcripción en la nube y emoción): necesita `GEMINI_API_KEY` en el `.env`, igual que la app.
- **Modelo local de lenguaje:** instalar [Ollama](https://ollama.com) y bajar un modelo, por ejemplo `ollama pull qwen2.5:7b` o `ollama pull llama3.2:3b`. Ollama tiene que estar abierto mientras corre el script.
- La primera vez que se usa un tamaño de Whisper se descarga el modelo. La descarga no cuenta en el tiempo medido.

## 3. Correr

```powershell
python -m benchmark.benchmark --corpus benchmark/corpus --asr tiny,base,small,medium --diar ecapa,mfcc
```

Con transcripción en la nube y emoción local contra Gemini:

```powershell
python -m benchmark.benchmark --asr small,gemini --llm gemini,ollama:qwen2.5:7b
```

| Opción | Qué hace | Por defecto |
|---|---|---|
| `--corpus` | Carpeta con los casos | `benchmark/corpus` |
| `--asr` | Modelos de transcripción, separados por coma | `tiny,base,small` |
| `--diar` | Métodos de hablantes (vacío para saltear) | `ecapa,mfcc` |
| `--llm` | Proveedores para emoción (vacío para saltear) | — |
| `--out` | Carpeta de resultados | `benchmark/resultados` |

La separación de hablantes se calcula sobre las zonas con voz del **primer** modelo de `--asr`.

## 4. Leer los resultados

Al terminar, el script muestra un resumen promediado y deja `benchmark/resultados/resultados_AAAAMMDD_HHMM.csv`, con una fila por caso, etapa y configuración. Se abre con Excel o Google Sheets para armar las tablas y los gráficos del informe:

- **Velocidad contra error:** en el eje X el factor de tiempo real y en el eje Y el WER, un punto por modelo. Muestra cuánto error se paga por cada ganancia de velocidad.
- **Error por perfil:** el WER y el DER agrupados por `meta_edad` o `meta_perfil`.
- **Grupal contra individual:** el DER y el acierto en la cantidad de hablantes.

## Limitaciones a declarar

- La transcripción de Gemini no devuelve tiempos por palabra, así que para ella no se calcula el % sin transcribir.
- La emoción se clasifica sobre el texto de referencia, no sobre el transcripto. Así se mide el error del modelo de lenguaje sin mezclarlo con el de la transcripción.
- El resumen clínico no tiene una métrica automática confiable: se evalúa a mano, por ejemplo contando datos inventados o minutos mal citados.
