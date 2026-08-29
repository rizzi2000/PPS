"""Orquestación del análisis, por etapas y con resultados incrementales.

Ordenamos las etapas por "valor percibido / tiempo de cómputo": el usuario
ve el waveform a los ~2 s, la transcripción va apareciendo mientras se
procesa, y el resumen (lo más lento) llega al final. Nada bloquea a nada.

Antes: un único POST bloqueante que devolvía todo junto al cabo de varios
minutos, y encima corriendo en el event loop de asyncio.
"""
import json
import os
import time

from ..core.config import RESULTS_DIR, WHISPER_MODEL
from ..core.jobs import Job
from . import asr, audio_io, diarize, llm, prosody


def _speech_regions(segments: list[dict]) -> list[tuple[float, float]]:
    """Zonas con voz según el VAD del ASR, fusionando huecos chicos."""
    regions: list[list[float]] = []
    for s in segments:
        if regions and s["start"] - regions[-1][1] < 0.5:
            regions[-1][1] = s["end"]
        else:
            regions.append([s["start"], s["end"]])
    return [(a, b) for a, b in regions]


def run_pipeline(job: Job, audio_path: str, n_speakers: int | None = None):
    t0 = time.time()
    try:
        job.status = "running"

        # --- Etapa 1: decodificar y dibujar (rápida) ----------------------
        job.progress("decode", 2, "Decodificando audio...")
        samples = audio_io.decode_to_pcm(audio_path)
        duration = samples.size / audio_io.SAMPLE_RATE

        peaks = audio_io.compute_peaks(samples)
        # El front ya puede renderizar el waveform completo acá.
        job.emit("peaks", peaks)
        job.progress("decode", 8, f"Audio listo ({duration/60:.1f} min)")

        if job.cancelled:
            return

        # --- Etapa 2: transcripción en streaming --------------------------
        job.progress("asr", 10, "Transcribiendo...")
        raw_segments: list[dict] = []

        for item in asr.transcribe_stream(samples):
            if job.cancelled:
                return
            if item["type"] == "info":
                job.emit("asr_info", item)
                continue
            raw_segments.append(item)
            # Emisión incremental: el texto aparece mientras se procesa.
            job.emit("segment", item)
            pct = 10 + 45 * min(1.0, item["end"] / max(duration, 1e-6))
            job.progress("asr", pct, f"Transcribiendo {item['end']/60:.1f}/{duration/60:.1f} min")

        if not raw_segments:
            raise RuntimeError("No se detectó voz en el audio.")

        job.progress("asr", 55, f"{len(raw_segments)} enunciados transcriptos")

        # --- Etapa 3: diarización -----------------------------------------
        job.progress("diarize", 58, "Identificando hablantes...")
        turns = diarize.diarize(samples, _speech_regions(raw_segments), n_speakers)

        # Cortamos los segmentos en los límites de hablante.
        segments = asr.split_segments_by_turns(raw_segments, turns)

        roles = diarize.assign_roles(segments)
        speaker_names = {}
        counts = {"Paciente": 0, "Terapeuta": 0}
        for spk, role in roles.items():
            counts[role] = counts.get(role, 0) + 1
            speaker_names[spk] = (
                role if counts[role] == 1 else f"{role} {counts[role]}"
            )

        for s in segments:
            spk = s.get("speaker", "SPK_0")
            s["role"] = roles.get(spk, "Desconocido")
            s["speaker_name"] = speaker_names.get(spk, spk)

        job.emit("speakers", {
            "turns": turns,
            "roles": roles,
            "names": speaker_names,
            "n_speakers": len(set(roles.values() and roles.keys())),
        })
        job.progress("diarize", 68, f"{len(set(roles))} hablantes detectados")

        # --- Etapa 4: prosodia (métricas reales) ---------------------------
        job.progress("prosody", 70, "Midiendo ritmo y prosodia...")
        prosody.enrich(samples, segments)
        stats = prosody.speaker_summary(segments)

        # Los segmentos ya reordenados y con métricas reemplazan a los crudos.
        job.emit("segments_final", {"segments": segments, "stats": stats})
        job.progress("prosody", 78, "Métricas calculadas")

        del samples  # liberamos memoria antes de la etapa de red (8 GB)

        # --- Etapa 5: traducción + emoción (paralelo) ----------------------
        job.progress("llm", 80, "Traduciendo y clasificando emociones...")

        def on_chunk(done, total):
            job.progress("llm", 80 + 12 * done / max(1, total),
                         f"Traduciendo {done}/{total}")

        llm.translate_and_tag(segments, on_chunk=on_chunk)
        job.emit("translations", [
            {"i": i, "text_en": s.get("text_en", ""),
             "emocion": s.get("emocion", "Neutral"), "tema": s.get("tema", "")}
            for i, s in enumerate(segments)
        ])

        # --- Etapa 6: resumen clínico --------------------------------------
        job.progress("summary", 93, "Redactando resumen clínico...")
        summary = llm.clinical_summary(segments, stats)
        job.emit("summary", summary)

        # --- Persistencia --------------------------------------------------
        result = {
            "job_id": job.id,
            "filename": job.filename,
            "duration": round(duration, 2),
            "created_at": job.created_at,
            "elapsed": round(time.time() - t0, 1),
            # Procedencia: con qué se generó este análisis. Necesario para poder
            # citar la fuente en un informe y para reproducir resultados.
            "modelos": {
                "asr": WHISPER_MODEL,
                "diarizacion": "ecapa" if diarize._encoder is not None else "mfcc",
                "llm": llm.describe(),
            },
            "speakers": {"roles": roles, "names": speaker_names, "stats": stats},
            "summary": summary,
            "segments": segments,
        }
        with open(os.path.join(RESULTS_DIR, f"{job.id}.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)

        job.result = result
        job.status = "done"
        job.progress("done", 100, f"Listo en {result['elapsed']}s "
                                  f"({duration/max(result['elapsed'],1):.1f}x tiempo real)")
        job.emit("done", {"elapsed": result["elapsed"]})

    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        job.status = "error"
        job.error = str(e)
        job.emit("error", {"message": str(e)})
