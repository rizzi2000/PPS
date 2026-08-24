"""Decodificación y picos de waveform.

Regla de oro del rendimiento: el audio se decodifica UNA sola vez a
16 kHz mono float32 y ese array se reutiliza en ASR, diarización y prosodia.
El código anterior hacía `librosa.load(sr=None)` (44.1 kHz estéreo, float64)
por cada análisis: 5-8x más RAM y CPU para nada.
"""
import os
import subprocess

import numpy as np

from ..core.config import CACHE_DIR, PEAKS_BUCKETS, SAMPLE_RATE


def _ffmpeg_bin() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def decode_to_pcm(audio_path: str) -> np.ndarray:
    """Decodifica cualquier formato a mono 16 kHz float32 en [-1, 1].

    Usa ffmpeg por stdout (sin archivo intermedio). Para un MP3 de 30 min
    esto tarda ~3-6 s en un i3, contra ~40 s de librosa.load a 44.1 kHz.
    """
    cmd = [
        _ffmpeg_bin(), "-nostdin", "-threads", "0", "-i", audio_path,
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-loglevel", "error", "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falló: {proc.stderr.decode('utf-8', 'ignore')[:400]}")

    pcm = np.frombuffer(proc.stdout, dtype=np.int16)
    if pcm.size == 0:
        raise RuntimeError("El archivo no contiene audio decodificable.")
    return (pcm.astype(np.float32) / 32768.0)


def cached_wav_path(job_id: str) -> str:
    return os.path.join(CACHE_DIR, f"{job_id}.wav")


def write_wav(samples: np.ndarray, path: str):
    """Escribe WAV PCM16 sin depender de soundfile."""
    import wave

    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes())


def compute_peaks(samples: np.ndarray, buckets: int = PEAKS_BUCKETS) -> dict:
    """Envolvente para WaveSurfer: un valor con signo por bucket.

    Mismo formato que `wavesurfer.exportPeaks()` (el de mayor valor absoluto
    en cada bucket, conservando el signo). Al mandárselo precalculado junto
    con la duración, WaveSurfer dibuja al instante sin descargar ni decodificar
    el archivo completo en el navegador.

    Vectorizado: un audio de 1 hora se resuelve en ~50 ms.
    """
    n = samples.size
    duration = n / SAMPLE_RATE
    buckets = max(1, min(buckets, n))
    per = int(np.ceil(n / buckets))

    padded = np.pad(samples, (0, per * buckets - n), mode="constant")
    frames = padded.reshape(buckets, per)

    mins = frames.min(axis=1)
    maxs = frames.max(axis=1)
    # El extremo dominante de cada bucket, con su signo.
    envelope = np.where(np.abs(mins) > np.abs(maxs), mins, maxs)

    # Normalizamos por el pico real para que audios grabados bajo se vean bien.
    peak = float(max(np.abs(envelope).max(), 1e-6))

    return {
        "duration": round(duration, 3),
        "peak": peak,
        "data": np.round(envelope / peak, 4).tolist(),
    }


def rms_envelope(samples: np.ndarray, hop_s: float = 0.02) -> tuple[np.ndarray, np.ndarray]:
    """Energía RMS por frame. Devuelve (tiempos, rms). Puro numpy, sin librosa."""
    hop = max(1, int(hop_s * SAMPLE_RATE))
    win = hop * 2
    n_frames = max(1, (samples.size - win) // hop + 1)

    idx = np.arange(win)[None, :] + hop * np.arange(n_frames)[:, None]
    idx = np.clip(idx, 0, samples.size - 1)
    frames = samples[idx]

    rms = np.sqrt(np.mean(frames.astype(np.float32) ** 2, axis=1))
    times = np.arange(n_frames) * hop / SAMPLE_RATE
    return times, rms
