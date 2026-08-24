"""Métricas acústicas reales por enunciado.

Esto reemplaza el campo `nivel_fluidez` que antes inventaba el LLM.
Un modelo de lenguaje no oye el audio: cualquier número de "ritmo de habla"
que produzca es una alucinación y no puede sostenerse en un informe.

Acá todo sale de la señal y de los timestamps por palabra:
  * tasa de habla      -> sílabas/segundo (silabeo estimado para español)
  * tasa de articulación-> ídem, descontando pausas internas
  * ratio de pausa     -> proporción de silencio dentro del turno
  * energía            -> RMS normalizado
  * F0 (tono)          -> media y variabilidad, por autocorrelación FFT
  * activación (arousal)-> combinación z-normalizada POR HABLANTE

La normalización por hablante es clave: compara al paciente consigo mismo,
no contra una escala absoluta que no significa nada entre personas distintas.
"""
import re

import numpy as np

from ..core.config import SAMPLE_RATE

VOWELS = re.compile(r"[aeiouáéíóúüAEIOUÁÉÍÓÚÜ]+")


def count_syllables_es(text: str) -> int:
    """Núcleos vocálicos ~ sílabas. Aproximación muy buena para español."""
    return max(1, len(VOWELS.findall(text)))


def _f0_track(seg_audio: np.ndarray, fmin: float = 60.0, fmax: float = 400.0):
    """F0 por autocorrelación normalizada, vectorizada con FFT.

    Preferido sobre librosa.yin/pyin: en un i3 de 2 núcleos, yin sobre una
    sesión de 45 min tarda minutos; esto resuelve en segundos.
    """
    frame = 1024
    hop = 320  # 20 ms
    if seg_audio.size < frame:
        return np.array([])

    n_frames = (seg_audio.size - frame) // hop + 1
    if n_frames < 1:
        return np.array([])

    idx = np.arange(frame)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = seg_audio[idx] * np.hanning(frame)[None, :]

    # Autocorrelación vía FFT
    nfft = 2048
    spec = np.fft.rfft(frames, n=nfft, axis=1)
    acf = np.fft.irfft(spec * np.conj(spec), n=nfft, axis=1)[:, :frame]

    energy = acf[:, 0:1]
    with np.errstate(divide="ignore", invalid="ignore"):
        acf_n = np.where(energy > 1e-8, acf / energy, 0.0)

    lag_min = int(SAMPLE_RATE / fmax)
    lag_max = min(int(SAMPLE_RATE / fmin), frame - 1)
    if lag_max <= lag_min:
        return np.array([])

    window = acf_n[:, lag_min:lag_max]
    best = window.argmax(axis=1) + lag_min
    conf = window.max(axis=1)

    f0 = SAMPLE_RATE / np.maximum(best, 1)
    # Solo nos quedamos con frames sonoros y con periodicidad clara.
    voiced = (conf > 0.35) & (energy[:, 0] > 1e-6)
    return f0[voiced]


def segment_metrics(samples: np.ndarray, seg: dict) -> dict:
    """Métricas crudas (aún sin normalizar) de un enunciado."""
    a, b = int(seg["start"] * SAMPLE_RATE), int(seg["end"] * SAMPLE_RATE)
    audio = samples[a:min(b, samples.size)]
    dur = max(1e-3, seg["end"] - seg["start"])

    words = seg.get("words") or []
    syls = count_syllables_es(seg.get("text", ""))

    # Tiempo efectivo hablando = suma de duraciones de palabra.
    voiced_time = sum(w["e"] - w["s"] for w in words) if words else dur
    voiced_time = max(1e-3, voiced_time)

    # Pausas internas: huecos entre palabras consecutivas > 150 ms
    gaps = []
    for i in range(1, len(words)):
        g = words[i]["s"] - words[i - 1]["e"]
        if g > 0.15:
            gaps.append(g)

    f0 = _f0_track(audio) if audio.size else np.array([])
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0

    return {
        "dur": round(dur, 2),
        "speech_rate": round(syls / dur, 3),              # sílabas/s con pausas
        "articulation_rate": round(syls / voiced_time, 3),  # sin pausas
        "pause_ratio": round(min(1.0, sum(gaps) / dur), 3),
        "longest_pause": round(max(gaps) if gaps else 0.0, 2),
        "n_pauses": len(gaps),
        "energy": round(rms, 5),
        "f0_mean": round(float(np.median(f0)), 1) if f0.size else 0.0,
        "f0_std": round(float(np.std(f0)), 1) if f0.size else 0.0,
        "words": len(words),
    }


def _z(values: np.ndarray) -> np.ndarray:
    mu, sd = np.mean(values), np.std(values)
    if sd < 1e-9:
        return np.zeros_like(values)
    return (values - mu) / sd


def enrich(samples: np.ndarray, segments: list[dict]) -> list[dict]:
    """Calcula métricas y las normaliza dentro de cada hablante."""
    for seg in segments:
        seg["metrics"] = segment_metrics(samples, seg)

    by_speaker: dict[str, list[dict]] = {}
    for seg in segments:
        by_speaker.setdefault(seg.get("speaker", "SPK_0"), []).append(seg)

    for _, segs in by_speaker.items():
        rate = np.array([s["metrics"]["articulation_rate"] for s in segs])
        energy = np.array([s["metrics"]["energy"] for s in segs])
        f0v = np.array([s["metrics"]["f0_std"] for s in segs])
        pause = np.array([s["metrics"]["pause_ratio"] for s in segs])

        z_rate, z_energy, z_f0, z_pause = _z(rate), _z(energy), _z(f0v), _z(pause)

        for i, s in enumerate(segs):
            # Fluidez: rápido y sin pausas = alto; lento y entrecortado = bajo.
            fluency = float(np.clip(z_rate[i] * 0.7 - z_pause[i] * 0.6, -3, 3))
            # Activación: energía + variabilidad tonal + velocidad.
            arousal = float(np.clip(
                0.4 * z_energy[i] + 0.35 * z_f0[i] + 0.25 * z_rate[i], -3, 3))

            s["metrics"]["fluency_z"] = round(fluency, 3)
            s["metrics"]["arousal_z"] = round(arousal, 3)
            s["metrics"]["fluency_label"] = _label(fluency, s["metrics"])

    return segments


def _label(fluency: float, m: dict) -> str:
    if m["longest_pause"] >= 2.5:
        return "Bloqueo"
    if fluency <= -0.9:
        return "Lenta"
    if fluency >= 0.9:
        return "Rapida"
    return "Normal"


def speaker_summary(segments: list[dict]) -> dict:
    """Agregados por hablante para el panel de métricas."""
    out: dict[str, dict] = {}
    for seg in segments:
        spk = seg.get("speaker", "SPK_0")
        m = seg["metrics"]
        st = out.setdefault(spk, {
            "talk_time": 0.0, "turns": 0, "words": 0,
            "rates": [], "pauses": [], "f0": [],
        })
        st["talk_time"] += m["dur"]
        st["turns"] += 1
        st["words"] += m["words"]
        st["rates"].append(m["articulation_rate"])
        st["pauses"].append(m["pause_ratio"])
        if m["f0_mean"] > 0:
            st["f0"].append(m["f0_mean"])

    total = sum(v["talk_time"] for v in out.values()) or 1.0
    for spk, st in out.items():
        out[spk] = {
            "talk_time": round(st["talk_time"], 1),
            "talk_share": round(100 * st["talk_time"] / total, 1),
            "turns": st["turns"],
            "words": st["words"],
            "avg_rate": round(float(np.mean(st["rates"])), 2) if st["rates"] else 0,
            "avg_pause_ratio": round(float(np.mean(st["pauses"])), 3) if st["pauses"] else 0,
            "f0_median": round(float(np.median(st["f0"])), 1) if st["f0"] else 0,
        }
    return out
