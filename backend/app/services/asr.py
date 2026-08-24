"""Transcripción con faster-whisper: streaming + timestamps por palabra.

Cambios frente a la versión anterior:
  * faster-whisper (CTranslate2) en vez de openai-whisper -> ~4x más rápido
    en CPU con cuantización int8, y permite modelo "small" donde antes
    "base" ya era lento.
  * `word_timestamps=True`: cada palabra trae su segundo exacto. La
    sincronía deja de depender de bloques de 30 s redondeados a MM:SS.
  * VAD Silero integrado: se saltan los silencios, lo que en sesiones
    terapéuticas (con pausas largas) recorta 20-40% del tiempo de cómputo.
  * Generador: emitimos cada segmento apenas está listo, no al final.
"""
from typing import Iterator

import numpy as np

from ..core.config import (CPU_THREADS, SAMPLE_RATE, WHISPER_COMPUTE,
                           WHISPER_DEVICE, WHISPER_MODEL)

_model = None


def get_model():
    """Carga perezosa y única del modelo (evita 1-2 min de arranque del server)."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        print(f"[ASR] Cargando faster-whisper '{WHISPER_MODEL}' ({WHISPER_COMPUTE})...")
        _model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE,
            cpu_threads=CPU_THREADS,
        )
        print("[ASR] Modelo listo.")
    return _model


def transcribe_stream(samples: np.ndarray, language: str = "es") -> Iterator[dict]:
    """Transcribe y va emitiendo segmentos con sus palabras alineadas.

    Recibe el array ya decodificado a 16 kHz: faster-whisper lo acepta
    directamente, evitando que vuelva a invocar ffmpeg sobre el archivo.
    """
    model = get_model()

    segments, info = model.transcribe(
        samples,
        language=language,
        task="transcribe",
        beam_size=1,               # greedy: ~2x más rápido, calidad casi igual con "small"
        best_of=1,
        temperature=0.0,
        word_timestamps=True,
        condition_on_previous_text=False,  # evita bucles de repetición en sesiones largas
        vad_filter=True,
        vad_parameters={
            "threshold": 0.5,
            "min_speech_duration_ms": 250,
            "min_silence_duration_ms": 400,   # umbral de corte entre turnos
            "speech_pad_ms": 200,
        },
    )

    yield {"type": "info", "language": info.language,
           "duration": float(info.duration)}

    for seg in segments:
        words = []
        for w in (seg.words or []):
            token = w.word.strip()
            if not token:
                continue
            words.append({
                "w": token,
                "s": round(float(w.start), 3),
                "e": round(float(w.end), 3),
                "p": round(float(w.probability), 3),
            })

        text = seg.text.strip()
        if not text:
            continue

        yield {
            "type": "segment",
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": text,
            "words": words,
            # confianza media: sirve para atenuar visualmente lo dudoso
            "confidence": round(float(np.exp(seg.avg_logprob)), 3),
            "no_speech": round(float(seg.no_speech_prob), 3),
        }


def split_segments_by_turns(segments: list[dict], turns: list[dict]) -> list[dict]:
    """Corta segmentos ASR en los límites de hablante, usando las palabras.

    Esto es lo que faltaba: antes un bloque de 30 s contenía la pregunta del
    terapeuta Y la respuesta del paciente, y el rol se volvía inasignable.
    Ahora cada enunciado pertenece a un solo hablante.
    """
    if not turns:
        return segments

    def speaker_at(t: float) -> str:
        for turn in turns:
            if turn["start"] <= t <= turn["end"]:
                return turn["speaker"]
        # Si cae en tierra de nadie, tomamos el turno más cercano.
        best, best_d = None, float("inf")
        for turn in turns:
            d = min(abs(turn["start"] - t), abs(turn["end"] - t))
            if d < best_d:
                best, best_d = turn["speaker"], d
        return best or "SPK_0"

    out: list[dict] = []
    for seg in segments:
        words = seg.get("words") or []
        if not words:
            seg = {**seg, "speaker": speaker_at((seg["start"] + seg["end"]) / 2)}
            out.append(seg)
            continue

        current: list[dict] = []
        current_spk = None
        for w in words:
            spk = speaker_at((w["s"] + w["e"]) / 2)
            if current_spk is None:
                current_spk = spk
            if spk != current_spk and current:
                out.append(_pack(current, current_spk, seg))
                current, current_spk = [], spk
            current.append(w)
        if current:
            out.append(_pack(current, current_spk, seg))

    return _merge_tiny(out)


def _pack(words: list[dict], speaker: str, parent: dict) -> dict:
    return {
        "start": words[0]["s"],
        "end": words[-1]["e"],
        "text": " ".join(w["w"] for w in words),
        "words": words,
        "speaker": speaker,
        "confidence": parent.get("confidence", 0.0),
    }


def _merge_tiny(segs: list[dict], min_dur: float = 0.6) -> list[dict]:
    """Absorbe fragmentos de 1-2 palabras (típicos 'sí', 'ajá') en el vecino
    del mismo hablante, para que la transcripción no quede picada."""
    if not segs:
        return segs
    out = [segs[0]]
    for seg in segs[1:]:
        prev = out[-1]
        too_short = (seg["end"] - seg["start"]) < min_dur and len(seg["words"]) <= 2
        if prev["speaker"] == seg["speaker"] and (too_short or seg["start"] - prev["end"] < 0.35):
            prev["end"] = seg["end"]
            prev["text"] = (prev["text"] + " " + seg["text"]).strip()
            prev["words"] = prev["words"] + seg["words"]
        else:
            out.append(seg)
    return out
