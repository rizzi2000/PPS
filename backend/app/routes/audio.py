"""Endpoints de sesiones: subida, progreso en vivo (SSE), resultado y audio."""
import asyncio
import json
import mimetypes
import os
import re
import unicodedata

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ..core.config import ALLOWED_EXT, MAX_UPLOAD_MB, RESULTS_DIR, UPLOAD_DIR
from ..core.jobs import registry
from ..services.pipeline import run_pipeline

router = APIRouter()

CHUNK = 1024 * 1024


def safe_filename(name: str) -> str:
    """Evita path traversal y nombres raros. El código anterior hacía
    os.path.join(UPLOAD_DIR, file.filename) sin sanitizar: '../../x' escapaba."""
    name = os.path.basename(name or "audio")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "audio"
    return name[:120]


@router.post("/sessions")
async def create_session(request: Request, file: UploadFile = File(...)):
    """Guarda el audio y lanza el pipeline en segundo plano.

    Responde de inmediato con el job_id: el front se suscribe al stream
    y empieza a recibir resultados por etapas.
    """
    filename = safe_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Formato no soportado ({ext}). "
                                 f"Permitidos: {', '.join(sorted(ALLOWED_EXT))}")

    loop = asyncio.get_running_loop()
    job = registry.create(filename, loop)

    dest = os.path.join(UPLOAD_DIR, f"{job.id}{ext}")
    size = 0
    limit = MAX_UPLOAD_MB * 1024 * 1024
    with open(dest, "wb") as out:
        while chunk := await file.read(CHUNK):
            size += len(chunk)
            if size > limit:
                out.close()
                os.remove(dest)
                raise HTTPException(413, f"El archivo supera {MAX_UPLOAD_MB} MB.")
            out.write(chunk)

    if size == 0:
        os.remove(dest)
        raise HTTPException(400, "El archivo está vacío.")

    job.audio_path = dest
    n_speakers = request.query_params.get("speakers")
    n_speakers = int(n_speakers) if n_speakers and n_speakers.isdigit() else None

    # Hilo aparte: el pipeline es CPU-bound y congelaría el event loop.
    loop.run_in_executor(None, run_pipeline, job, dest, n_speakers)

    return {"job_id": job.id, "filename": filename, "size": size}


@router.get("/sessions/{job_id}/events")
async def stream_events(job_id: str, request: Request):
    """Server-Sent Events: progreso y resultados parciales en tiempo real."""
    job = registry.get(job_id)
    if not job:
        raise HTTPException(404, "Sesión no encontrada")

    async def gen():
        # Reenviamos lo ya ocurrido para que un refresh no pierda estado.
        sent = 0
        for item in list(job.history):
            sent += 1
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        while True:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(job.queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"      # evita que proxies corten la conexión
                continue
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            if item["event"] in ("done", "error"):
                break

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@router.get("/sessions")
async def list_sessions():
    jobs = registry.list()
    known = {j["id"] for j in jobs}
    # Sumamos las sesiones ya persistidas de ejecuciones anteriores.
    for fn in sorted(os.listdir(RESULTS_DIR), reverse=True):
        if not fn.endswith(".json"):
            continue
        jid = fn[:-5]
        if jid in known:
            continue
        try:
            with open(os.path.join(RESULTS_DIR, fn), encoding="utf-8") as f:
                data = json.load(f)
            jobs.append({"id": jid, "filename": data.get("filename", jid),
                         "status": "done", "created_at": data.get("created_at", 0)})
        except Exception:  # noqa: BLE001
            continue
    return jobs


@router.get("/sessions/{job_id}")
async def get_session(job_id: str):
    job = registry.get(job_id)
    if job and job.result:
        return job.result
    path = os.path.join(RESULTS_DIR, f"{job_id}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if job:
        return JSONResponse({"job_id": job.id, "status": job.status,
                             "error": job.error}, status_code=202)
    raise HTTPException(404, "Sesión no encontrada")


def _find_audio(job_id: str) -> str:
    for ext in ALLOWED_EXT:
        p = os.path.join(UPLOAD_DIR, f"{job_id}{ext}")
        if os.path.exists(p):
            return p
    raise HTTPException(404, "Audio no encontrado")


@router.get("/sessions/{job_id}/audio")
async def get_audio(job_id: str, request: Request):
    """Sirve el audio con soporte de Range.

    Sin Range, el navegador no puede hacer seek en archivos largos: por eso
    conviene servirlo desde el backend y no depender de un blob local.
    """
    path = _find_audio(job_id)
    total = os.path.getsize(path)
    media = mimetypes.guess_type(path)[0] or "application/octet-stream"
    range_header = request.headers.get("range")

    if not range_header:
        def full():
            with open(path, "rb") as f:
                while data := f.read(CHUNK):
                    yield data
        return StreamingResponse(full(), media_type=media, headers={
            "Accept-Ranges": "bytes", "Content-Length": str(total)})

    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    start = int(m.group(1)) if m and m.group(1) else 0
    end = int(m.group(2)) if m and m.group(2) else total - 1
    end = min(end, total - 1)
    if start > end:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{total}"})

    def partial():
        remaining = end - start + 1
        with open(path, "rb") as f:
            f.seek(start)
            while remaining > 0 and (data := f.read(min(CHUNK, remaining))):
                remaining -= len(data)
                yield data

    return StreamingResponse(partial(), status_code=206, media_type=media, headers={
        "Content-Range": f"bytes {start}-{end}/{total}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    })


@router.delete("/sessions/{job_id}")
async def delete_session(job_id: str):
    job = registry.get(job_id)
    if job:
        job.cancelled = True
    removed = []
    for path in (os.path.join(RESULTS_DIR, f"{job_id}.json"),):
        if os.path.exists(path):
            os.remove(path)
            removed.append(path)
    try:
        os.remove(_find_audio(job_id))
    except HTTPException:
        pass
    return {"deleted": job_id, "files": len(removed)}
