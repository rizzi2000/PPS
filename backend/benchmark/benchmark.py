"""Comparación de modelos: velocidad contra errores.

Corre el mismo corpus de audios con distintas configuraciones y deja un CSV
con una fila por (audio, etapa, configuración). Las métricas se calculan
contra una referencia anotada a mano; sin referencia no hay forma honesta de
decir cuánto "pifia" un modelo.

Uso (desde backend/, con el venv activado):

    python -m benchmark.benchmark --corpus benchmark/corpus \
        --asr tiny,base,small,gemini --diar ecapa,mfcc --llm gemini,ollama:qwen2.5:7b

Ver benchmark/README.md para el formato del corpus.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime

import numpy as np

# Permite correrlo como script suelto además de como módulo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import CPU_THREADS, EMOTIONS, SAMPLE_RATE, WHISPER_COMPUTE, WHISPER_DEVICE  # noqa: E402
from app.services import audio_io, diarize  # noqa: E402

AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm")


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def load_corpus(root: str) -> list[dict]:
    """Cada subcarpeta es un caso: un audio + referencia.json."""
    items = []
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue
        audio = next((os.path.join(folder, f) for f in sorted(os.listdir(folder))
                      if f.lower().endswith(AUDIO_EXT)), None)
        ref_path = os.path.join(folder, "referencia.json")
        if not audio or not os.path.exists(ref_path):
            print(f"[corpus] salteo {name}: falta el audio o referencia.json")
            continue
        with open(ref_path, encoding="utf-8") as f:
            ref = json.load(f)
        items.append({"id": name, "audio": audio, "ref": ref, "meta": ref.get("meta", {})})
    return items


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> list[str]:
    """Minúsculas, sin puntuación ni tildes: se compara lo que se dijo, no
    cómo se escribió. Las muletillas se conservan (son parte del habla)."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9ñ\s]", " ", text)
    return text.split()


def edit_ops(ref: list, hyp: list) -> tuple[int, int, int]:
    """Sustituciones, borrados e inserciones (Levenshtein con backtrace).

    Usa rapidfuzz si está instalado (mucho más rápido); si no, la versión en
    Python, que alcanza para comparar palabras pero es lenta para caracteres.
    """
    try:
        from rapidfuzz.distance import Levenshtein
        ops = Levenshtein.editops(ref, hyp)
        return (sum(o.tag == "replace" for o in ops), sum(o.tag == "delete" for o in ops),
                sum(o.tag == "insert" for o in ops))
    except ImportError:
        pass
    n, m = len(ref), len(hyp)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + cost)
    s = dl = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            s += ref[i - 1] != hyp[j - 1]
            i, j = i - 1, j - 1
        elif i > 0 and d[i, j] == d[i - 1, j] + 1:
            dl, i = dl + 1, i - 1
        else:
            ins, j = ins + 1, j - 1
    return int(s), int(dl), int(ins)


def _fast_or_small(a, b) -> bool:
    try:
        import rapidfuzz  # noqa: F401
        return True
    except ImportError:
        return len(a) * len(b) < 4e6


def wer(ref_text: str, hyp_text: str) -> dict:
    ref, hyp = normalize_text(ref_text), normalize_text(hyp_text)
    s, d, i = edit_ops(ref, hyp)
    n = max(1, len(ref))
    ref_c = list("".join(ref))
    hyp_c = list("".join(hyp))
    cs, cd, ci = edit_ops(ref_c, hyp_c) if _fast_or_small(ref_c, hyp_c) else (0, 0, 0)
    return {
        "wer": round((s + d + i) / n, 4),
        "sustituciones": s, "borrados": d, "inserciones": i,
        "cer": round((cs + cd + ci) / max(1, len(ref_c)), 4),
        "palabras_ref": len(ref),
    }


def coverage_missed(ref_turns: list[dict], words: list[dict]) -> float:
    """% del tiempo con voz (según la referencia) donde el modelo no
    transcribió ninguna palabra. Es la versión medida del panel
    'Transcripción incompleta' de la app."""
    step = 0.05
    total = missed = 0
    spans = sorted((w["s"], w["e"]) for w in words)
    for t in ref_turns:
        x = t["inicio"]
        while x < t["fin"]:
            total += 1
            # Una palabra "cubre" el instante con 250 ms de tolerancia.
            if not any(a - 0.25 <= x <= b + 0.25 for a, b in spans):
                missed += 1
            x += step
    return round(100 * missed / max(1, total), 2)


def der(ref_turns: list[dict], hyp_turns: list[dict], step: float = 0.01) -> dict:
    """Diarization Error Rate por cuadros de 10 ms.

    DER = (habla perdida + falsa alarma + confusión de hablante) / habla de
    referencia. Los nombres de hablante del modelo (SPK_0...) se emparejan con
    los de la referencia de la forma que menos error da (algoritmo húngaro).
    """
    from scipy.optimize import linear_sum_assignment

    end = max([t["fin"] for t in ref_turns] + [t["end"] for t in hyp_turns] + [0])
    n = int(end / step) + 1
    ref_spk = sorted({t["hablante"] for t in ref_turns})
    hyp_spk = sorted({t["speaker"] for t in hyp_turns})
    R = np.zeros((len(ref_spk), n), dtype=bool)
    H = np.zeros((len(hyp_spk), n), dtype=bool)
    for t in ref_turns:
        R[ref_spk.index(t["hablante"]), int(t["inicio"] / step):int(t["fin"] / step)] = True
    for t in hyp_turns:
        H[hyp_spk.index(t["speaker"]), int(t["start"] / step):int(t["end"] / step)] = True

    ref_any, hyp_any = R.any(0), H.any(0)
    speech = ref_any.sum() or 1
    missed = (ref_any & ~hyp_any).sum()
    false_alarm = (hyp_any & ~ref_any).sum()

    # Emparejamiento: maximiza el solapamiento entre etiquetas.
    overlap = np.array([[(R[i] & H[j]).sum() for j in range(len(hyp_spk))]
                        for i in range(len(ref_spk))]) if hyp_spk else np.zeros((len(ref_spk), 0))
    rows, cols = linear_sum_assignment(-overlap) if overlap.size else ([], [])
    mapping = {hyp_spk[c]: ref_spk[r] for r, c in zip(rows, cols)}
    both = ref_any & hyp_any
    correct = 0
    for j, h in enumerate(hyp_spk):
        if h in mapping:
            correct += (H[j] & R[ref_spk.index(mapping[h])] & both).sum()
    confusion = both.sum() - correct

    return {
        "der": round(float((missed + false_alarm + confusion) / speech), 4),
        "habla_perdida_pct": round(100 * float(missed / speech), 2),
        "falsa_alarma_pct": round(100 * float(false_alarm / speech), 2),
        "confusion_pct": round(100 * float(confusion / speech), 2),
        "hablantes_ref": len(ref_spk),
        "hablantes_detectados": len(hyp_spk),
    }


def cohen_kappa(a: list[str], b: list[str]) -> float:
    labels = sorted(set(a) | set(b))
    if not a:
        return 0.0
    po = sum(x == y for x, y in zip(a, b)) / len(a)
    pe = sum((a.count(l) / len(a)) * (b.count(l) / len(b)) for l in labels)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else 1.0


# ---------------------------------------------------------------------------
# Transcripción
# ---------------------------------------------------------------------------

_whisper_cache: dict = {}


def load_whisper(name: str):
    """Carga (y la primera vez descarga) el modelo fuera del cronómetro: lo que
    se compara es la velocidad de transcribir, no la de bajar el modelo."""
    from faster_whisper import WhisperModel

    if name not in _whisper_cache:
        _whisper_cache[name] = WhisperModel(name, device=WHISPER_DEVICE,
                                            compute_type=WHISPER_COMPUTE, cpu_threads=CPU_THREADS)
    return _whisper_cache[name]


def run_whisper(name: str, samples: np.ndarray) -> tuple[str, list[dict], list[dict]]:
    """Misma configuración que la app (asr.py), cambiando sólo el modelo."""
    segments, _ = load_whisper(name).transcribe(
        samples, language="es", beam_size=1, best_of=1, temperature=0.0,
        word_timestamps=True, condition_on_previous_text=False, vad_filter=True,
        vad_parameters={"threshold": 0.5, "min_speech_duration_ms": 250,
                        "min_silence_duration_ms": 400, "speech_pad_ms": 200},
    )
    segs, words = [], []
    for s in segments:
        segs.append({"start": float(s.start), "end": float(s.end), "text": s.text.strip()})
        words += [{"s": float(w.start), "e": float(w.end)} for w in (s.words or []) if w.word.strip()]
    return " ".join(s["text"] for s in segs), segs, words


def run_gemini_asr(audio_path: str) -> tuple[str, list, list]:
    """Transcripción en la nube: el audio completo a Gemini (como el
    prototipo 1). No devuelve tiempos confiables, así que sólo se mide WER."""
    from google import genai

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    up = client.files.upload(file=audio_path)
    resp = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
        contents=[up, "Transcribí literalmente este audio en español. Devolvé sólo "
                      "el texto, sin nombres de hablantes, sin marcas de tiempo y sin comentarios."],
    )
    return (resp.text or "").strip(), [], []


_ecapa = None


def use_ecapa(on: bool):
    """diarize.py elige ECAPA o MFCC según su encoder global: lo alternamos
    acá, cargando ECAPA una sola vez para toda la corrida."""
    global _ecapa
    if on:
        if _ecapa is None:
            diarize._encoder_failed = False
            _ecapa = diarize._get_encoder()
        diarize._encoder, diarize._encoder_failed = _ecapa, _ecapa is None
    else:
        diarize._encoder, diarize._encoder_failed = None, True


# ---------------------------------------------------------------------------
# Emoción (modelo de lenguaje)
# ---------------------------------------------------------------------------

def _emotion_prompt(texts: list[str]) -> str:
    lines = "\n".join(f"{i}. {t}" for i, t in enumerate(texts))
    return (f"Clasificá la emoción predominante de cada uno de estos {len(texts)} enunciados "
            f"de una sesión de psicoterapia. Usá EXACTAMENTE una de: {', '.join(EMOTIONS)}.\n\n"
            f"{lines}\n\nRespondé sólo con JSON: "
            '{"items": [{"i": 0, "emocion": "..."}]}')


def classify_emotions(provider: str, texts: list[str]) -> tuple[list[str], int]:
    """Devuelve (etiquetas, respuestas inválidas)."""
    prompt = _emotion_prompt(texts)
    if provider == "gemini":
        from app.services import llm
        data = llm._gemini_json("Sos un clasificador de emociones.", prompt, None, "low",
                                model_name=os.getenv("GEMINI_MODEL_BULK", "gemini-flash-lite-latest"))
    elif provider.startswith("ollama:"):
        import urllib.request
        body = json.dumps({
            "model": provider.split(":", 1)[1],
            "messages": [{"role": "user", "content": prompt}],
            "format": "json", "stream": False, "options": {"temperature": 0.1},
        }).encode()
        req = urllib.request.Request(os.getenv("OLLAMA_URL", "http://localhost:11434") + "/api/chat",
                                     data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            data = json.loads(json.loads(r.read())["message"]["content"])
    else:
        raise ValueError(f"Proveedor desconocido: {provider}")

    got = {int(it.get("i", -1)): it.get("emocion") for it in (data or {}).get("items", [])}
    labels, invalid = [], 0
    for i in range(len(texts)):
        e = got.get(i)
        if e not in EMOTIONS:
            invalid += 1
            e = "Neutral"
        labels.append(e)
    return labels, invalid


# ---------------------------------------------------------------------------
# Corrida
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="benchmark/corpus")
    ap.add_argument("--asr", default="tiny,base,small", help="modelos Whisper y/o 'gemini'")
    ap.add_argument("--diar", default="ecapa,mfcc", help="ecapa, mfcc o vacío para saltear")
    ap.add_argument("--llm", default="", help="gemini y/o ollama:<modelo>, separados por coma")
    ap.add_argument("--out", default="benchmark/resultados")
    args = ap.parse_args()

    corpus = load_corpus(args.corpus)
    if not corpus:
        sys.exit(f"No encontré casos en {args.corpus}. Ver benchmark/README.md.")
    os.makedirs(args.out, exist_ok=True)
    out_csv = os.path.join(args.out, f"resultados_{datetime.now():%Y%m%d_%H%M}.csv")

    rows = []
    for case in corpus:
        ref = case["ref"]
        turns = ref.get("turnos", [])
        ref_text = " ".join(t.get("texto", "") for t in turns)
        print(f"\n=== {case['id']} ===")
        samples = audio_io.decode_to_pcm(case["audio"])
        dur = samples.size / SAMPLE_RATE
        base = {"caso": case["id"], "duracion_s": round(dur, 1), **{f"meta_{k}": v for k, v in case["meta"].items()}}

        regions = None
        for name in [x for x in args.asr.split(",") if x]:
            if name != "gemini":
                load_whisper(name)
            t0 = time.time()
            if name == "gemini":
                hyp, segs, words = run_gemini_asr(case["audio"])
                where = "nube"
            else:
                hyp, segs, words = run_whisper(name, samples)
                where = "local"
            el = time.time() - t0
            row = {**base, "etapa": "transcripcion", "config": name, "donde": where,
                   "tiempo_s": round(el, 1), "factor_tiempo_real": round(el / dur, 3),
                   **wer(ref_text, hyp)}
            if words:
                row["sin_transcribir_pct"] = coverage_missed(turns, words)
            rows.append(row)
            print(f"  ASR {name:>8}: {el:6.1f}s  WER {row['wer']:.3f}"
                  + (f"  sin transcribir {row['sin_transcribir_pct']}%" if words else ""))
            if regions is None and segs:
                regions = [(s["start"], s["end"]) for s in segs]

        # Diarización sobre las zonas con voz del primer Whisper corrido.
        if regions:
            for method in [x for x in args.diar.split(",") if x]:
                use_ecapa(method == "ecapa")
                t0 = time.time()
                hyp_turns = diarize.diarize(samples, regions, None)
                el = time.time() - t0
                row = {**base, "etapa": "hablantes", "config": method, "donde": "local",
                       "tiempo_s": round(el, 1), "factor_tiempo_real": round(el / dur, 3),
                       **der(turns, hyp_turns)}
                rows.append(row)
                print(f"  DIAR {method:>7}: {el:6.1f}s  DER {row['der']:.3f}  "
                      f"hablantes {row['hablantes_detectados']}/{row['hablantes_ref']}")

        # Emoción: sobre el texto de referencia, para aislar el error del LLM
        # del error de transcripción.
        emo_ref = [t for t in turns if t.get("emocion") in EMOTIONS]
        for provider in [x for x in args.llm.split(",") if x]:
            if not emo_ref:
                break
            t0 = time.time()
            try:
                labels, invalid = classify_emotions(provider, [t["texto"] for t in emo_ref])
            except Exception as e:  # noqa: BLE001
                print(f"  LLM {provider}: error {e}")
                continue
            el = time.time() - t0
            gold = [t["emocion"] for t in emo_ref]
            acc = sum(a == b for a, b in zip(labels, gold)) / len(gold)
            rows.append({**base, "etapa": "emocion", "config": provider,
                         "donde": "nube" if provider == "gemini" else "local",
                         "tiempo_s": round(el, 1), "enunciados": len(gold),
                         "exactitud": round(acc, 4), "kappa": cohen_kappa(gold, labels),
                         "respuestas_invalidas": invalid})
            print(f"  LLM {provider}: {el:6.1f}s  exactitud {acc:.2f}")

    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"\nResultados: {out_csv}")
    summarize(rows)


def summarize(rows: list[dict]):
    """Promedios por configuración: la tabla que va al informe."""
    print("\nResumen (promedio sobre el corpus)")
    groups: dict = {}
    for r in rows:
        groups.setdefault((r["etapa"], r["config"]), []).append(r)
    for (etapa, cfg), rs in groups.items():
        def avg(k):
            v = [r[k] for r in rs if isinstance(r.get(k), (int, float))]
            return f"{np.mean(v):.3f}" if v else "—"
        if etapa == "transcripcion":
            print(f"  {etapa:<13} {cfg:<16} RTF {avg('factor_tiempo_real')}  WER {avg('wer')}  "
                  f"CER {avg('cer')}  sin transcribir {avg('sin_transcribir_pct')}%")
        elif etapa == "hablantes":
            acc = np.mean([r["hablantes_detectados"] == r["hablantes_ref"] for r in rs])
            print(f"  {etapa:<13} {cfg:<16} RTF {avg('factor_tiempo_real')}  DER {avg('der')}  "
                  f"acierto en cantidad {acc:.0%}")
        else:
            print(f"  {etapa:<13} {cfg:<16} {avg('tiempo_s')} s  exactitud {avg('exactitud')}  "
                  f"kappa {avg('kappa')}")


if __name__ == "__main__":
    main()
