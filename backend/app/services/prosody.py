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

    _measure_holds(segments, samples)

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
            # VELOCIDAD: sílabas por segundo y nada más. Antes esta métrica
            # mezclaba ritmo con pausas y el resultado no era interpretable como
            # "habla rápido o lento", que es la pregunta que interesa responder.
            speed = float(np.clip(z_rate[i], -3, 3))

            # INTENSIDAD: cuánto sube la voz. Volumen + variación del tono.
            # No dice qué emoción es, pero sí cuán activada está la persona.
            intensity = float(np.clip(0.55 * z_energy[i] + 0.45 * z_f0[i], -3, 3))

            m = s["metrics"]
            m["speed_z"] = round(speed, 3)
            m["intensity_z"] = round(intensity, 3)
            m["speed_label"] = _speed_label(speed)
            m["intensity_label"] = _level_label(intensity, ("Baja", "Normal", "Alta"))
            # Entrecortado = muchas pausas internas, independiente de la velocidad.
            m["choppy"] = bool(z_pause[i] >= 1.0)
            m["blocked"] = bool(m.get("silence", 0) >= BLOCK_S)

    return segments


BLOCK_S = 2.0     # silencio a partir del cual hablamos de bloqueo
LEVEL_Z = 0.8     # cuánto hay que desviarse para dejar de ser "normal"


def _measure_holds(segments: list[dict], samples: np.ndarray) -> None:
    """Mide el silencio que precede a cada turno cuando el hablante no cambió.

    Es necesario porque el VAD del ASR corta los segmentos en silencios de más
    de 400 ms: una pausa larga deja de ser un hueco DENTRO del enunciado y pasa
    a ser el corte ENTRE dos enunciados. Mirando sólo `longest_pause` (huecos
    entre palabras) el silencio clínicamente interesante —el paciente se calla
    varios segundos y después retoma— no aparecía en ningún lado.

    Dos condiciones para contarlo:

    1. Que nadie más haya hablado en el medio. Si contestó el terapeuta, el
       silencio es un turno de conversación, no un bloqueo.
    2. Que el audio esté efectivamente callado. Un hueco en la transcripción
       no es un silencio: puede ser habla que el ASR no reconoció (ruido,
       voz lejana, solapamiento). Sin esta verificación un fallo de
       transcripción se reportaría como un bloqueo de 20 segundos que nunca
       ocurrió, que es exactamente el tipo de dato falso que no puede entrar
       en una nota clínica.
    """
    ref = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
    quiet = ref * 0.15   # relativo: los niveles de grabación varían mucho

    ordered = sorted(segments, key=lambda s: s["start"])
    for i, seg in enumerate(ordered):
        gap = 0.0
        if i > 0:
            prev = ordered[i - 1]
            if prev.get("speaker") == seg.get("speaker"):
                gap = max(0.0, seg["start"] - prev["end"])

        verified = 0.0
        if gap > 0.3:
            a = int(ordered[i - 1]["end"] * SAMPLE_RATE)
            b = min(int(seg["start"] * SAMPLE_RATE), samples.size)
            chunk = samples[a:b]
            if chunk.size:
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                if rms <= quiet:
                    verified = gap
                else:
                    # Hueco con audio: no es silencio, es transcripción perdida.
                    seg["metrics"]["gap_unvoiced"] = round(gap, 2)

        seg["metrics"]["hold_before"] = round(verified, 2)
        # Silencio máximo atribuible al turno, venga de donde venga.
        seg["metrics"]["silence"] = round(
            max(verified, seg["metrics"]["longest_pause"]), 2)


def _level_label(z: float, names: tuple[str, str, str]) -> str:
    """Tres niveles a partir de un z-score: bajo, normal, alto."""
    low, mid, high = names
    if z <= -LEVEL_Z:
        return low
    if z >= LEVEL_Z:
        return high
    return mid


def _speed_label(z: float) -> str:
    """Velocidad del habla comparada con la base del propio hablante.

    Sólo tres valores. Un "Bloqueo" no es una velocidad sino un silencio, así
    que se reporta aparte (`blocked`) en lugar de mezclarlo acá.
    """
    return _level_label(z, ("Lento", "Normal", "Rapido"))


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
