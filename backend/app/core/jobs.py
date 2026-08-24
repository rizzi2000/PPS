"""Registro de trabajos en memoria con un bus de eventos para SSE.

El pipeline corre en un hilo aparte (es CPU-bound y bloquearía el event loop),
y empuja eventos hacia una cola asyncio del hilo del servidor.
"""
import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional


class Job:
    def __init__(self, job_id: str, filename: str, loop: asyncio.AbstractEventLoop):
        self.id = job_id
        self.filename = filename
        self.created_at = time.time()
        self.status = "pending"          # pending | running | done | error
        self.error: Optional[str] = None
        self.loop = loop
        self.queue: asyncio.Queue = asyncio.Queue()
        # Historial: permite reconectarse al stream sin perder lo ya emitido.
        self.history: List[Dict[str, Any]] = []
        self.result: Dict[str, Any] = {}
        self.cancelled = False

    def emit(self, event: str, data: Any = None):
        """Thread-safe: se llama desde el hilo del pipeline."""
        payload = {"event": event, "data": data, "t": round(time.time() - self.created_at, 2)}
        self.history.append(payload)
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, payload)
        except RuntimeError:
            pass  # el loop se cerró; el historial igual queda persistido

    def progress(self, stage: str, pct: float, message: str = ""):
        self.emit("progress", {"stage": stage, "pct": round(pct, 1), "message": message})


class JobRegistry:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}

    def create(self, filename: str, loop: asyncio.AbstractEventLoop) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = self._jobs[job_id] = Job(job_id, filename, loop)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": j.id,
                "filename": j.filename,
                "status": j.status,
                "created_at": j.created_at,
            }
            for j in sorted(self._jobs.values(), key=lambda x: -x.created_at)
        ]


registry = JobRegistry()
