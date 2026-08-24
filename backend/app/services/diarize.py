"""Diarización: separar QUIÉN habla a partir de la señal, no del texto.

La versión anterior le pedía a Gemini que adivinara el rol leyendo la
transcripción. Un LLM no escucha: no puede distinguir voces. Acá lo hacemos
con embeddings de locutor + clustering, que es la técnica estándar.

Dos backends:
  1. ECAPA-TDNN (speechbrain) -> calidad alta, ~15x tiempo real en CPU.
  2. Fallback MFCC + estadísticas -> sin dependencias extra, suficiente
     para separar 2 voces claramente distintas (terapeuta / paciente).

Diseñado para 2 núcleos: se extraen embeddings solo sobre ventanas con voz.
"""
import os

import numpy as np

from ..core.config import CACHE_DIR, SAMPLE_RATE

_encoder = None
_encoder_failed = False

WIN_S = 1.5        # ventana de análisis
HOP_ECAPA = 1.4    # ECAPA discrimina bien: casi sin solape -> mitad de ventanas
HOP_MFCC = 0.75    # MFCC es más débil: necesita solape del 50% para compensar


def _get_encoder():
    """Intenta cargar ECAPA-TDNN. Si no está, devolvemos None y usamos MFCC."""
    global _encoder, _encoder_failed
    if _encoder is not None or _encoder_failed:
        return _encoder
    try:
        import torch
        from speechbrain.inference.speaker import EncoderClassifier
        torch.set_num_threads(2)

        # En Windows, crear symlinks requiere privilegios de administrador o
        # modo desarrollador (WinError 1314). Forzamos copia del modelo.
        kwargs = {}
        try:
            from speechbrain.utils.fetching import LocalStrategy
            kwargs["local_strategy"] = LocalStrategy.COPY
        except ImportError:
            pass  # speechbrain < 1.0 no expone LocalStrategy

        _encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=os.path.join(CACHE_DIR, "spkrec-ecapa"),
            run_opts={"device": "cpu"},
            **kwargs,
        )
        print("[DIAR] ECAPA-TDNN cargado.")
    except Exception as e:  # noqa: BLE001
        print(f"[DIAR] ECAPA no disponible ({type(e).__name__}), uso fallback MFCC.")
        _encoder_failed = True
        _encoder = None
    return _encoder


def _embed_ecapa(windows: np.ndarray) -> np.ndarray:
    import torch
    enc = _get_encoder()
    out = []
    # Lotes chicos: 8 GB de RAM no perdonan.
    for i in range(0, len(windows), 16):
        batch = torch.from_numpy(windows[i:i + 16])
        with torch.no_grad():
            emb = enc.encode_batch(batch).squeeze(1).cpu().numpy()
        out.append(emb)
    return np.vstack(out)


def _embed_mfcc(windows: np.ndarray) -> np.ndarray:
    """Fallback: MFCC + delta, resumidos en media y desvío por ventana."""
    import librosa
    feats = []
    for w in windows:
        m = librosa.feature.mfcc(y=w, sr=SAMPLE_RATE, n_mfcc=20,
                                 n_fft=512, hop_length=160)
        d = librosa.feature.delta(m)
        feats.append(np.concatenate([m.mean(1), m.std(1), d.mean(1)]))
    return np.asarray(feats, dtype=np.float32)


def _speech_windows(samples: np.ndarray, regions: list[tuple[float, float]],
                    hop_s: float = HOP_MFCC):
    """Corta ventanas de WIN_S dentro de las zonas con voz detectada."""
    win = int(WIN_S * SAMPLE_RATE)
    hop = int(hop_s * SAMPLE_RATE)
    windows, centers = [], []

    for start, end in regions:
        a, b = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
        if b - a < win // 2:
            continue
        pos = a
        while pos + win // 2 <= b:
            chunk = samples[pos:pos + win]
            if chunk.size < win:
                chunk = np.pad(chunk, (0, win - chunk.size))
            # Descartamos ventanas casi mudas: ensucian el clustering.
            if float(np.sqrt(np.mean(chunk ** 2))) > 0.005:
                windows.append(chunk)
                centers.append((pos + win / 2) / SAMPLE_RATE)
            pos += hop

    if not windows:
        return np.empty((0, win), dtype=np.float32), []
    return np.stack(windows).astype(np.float32), centers


def _best_k(emb: np.ndarray, max_k: int = 4) -> int:
    """Elige el número de hablantes por silhouette. En terapia casi siempre 2."""
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    n = len(emb)
    if n < 6:
        return 1
    best_k, best_score = 1, -1.0
    for k in range(2, min(max_k, n - 1) + 1):
        labels = AgglomerativeClustering(n_clusters=k, metric="cosine",
                                         linkage="average").fit_predict(emb)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(emb, labels, metric="cosine")
        if score > best_score:
            best_k, best_score = k, score
    # Umbral conservador: si la separación es pobre, asumimos un solo hablante.
    return best_k if best_score > 0.12 else 1


def diarize(samples: np.ndarray, regions: list[tuple[float, float]],
            n_speakers: int | None = None) -> list[dict]:
    """Devuelve turnos [{start, end, speaker}] ordenados."""
    from sklearn.cluster import AgglomerativeClustering

    enc = _get_encoder()
    hop = HOP_ECAPA if enc is not None else HOP_MFCC

    windows, centers = _speech_windows(samples, regions, hop)
    if len(windows) == 0:
        return []
    if len(windows) < 4:
        return [{"start": regions[0][0], "end": regions[-1][1], "speaker": "SPK_0"}]

    emb = _embed_ecapa(windows) if enc is not None else _embed_mfcc(windows)

    # Normalización L2 -> distancia coseno bien condicionada.
    emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)

    k = n_speakers or _best_k(emb)
    if k <= 1:
        labels = np.zeros(len(emb), dtype=int)
    else:
        labels = AgglomerativeClustering(n_clusters=k, metric="cosine",
                                         linkage="average").fit_predict(emb)

    labels = _smooth(labels)

    # Ventanas contiguas con misma etiqueta -> un turno.
    turns: list[dict] = []
    for center, lab in zip(centers, labels):
        s, e = center - hop / 2, center + hop / 2
        if turns and turns[-1]["speaker"] == f"SPK_{lab}" and s - turns[-1]["end"] < 0.8:
            turns[-1]["end"] = e
        else:
            turns.append({"start": max(0.0, s), "end": e, "speaker": f"SPK_{lab}"})

    for t in turns:
        t["start"], t["end"] = round(t["start"], 2), round(t["end"], 2)
    return turns


def _smooth(labels: np.ndarray, k: int = 3) -> np.ndarray:
    """Filtro de mediana: elimina cambios de hablante de una sola ventana,
    que casi siempre son ruido del clustering y no turnos reales."""
    if len(labels) < k:
        return labels
    out = labels.copy()
    half = k // 2
    for i in range(half, len(labels) - half):
        vals, counts = np.unique(labels[i - half:i + half + 1], return_counts=True)
        out[i] = vals[counts.argmax()]
    return out


def assign_roles(segments: list[dict]) -> dict[str, str]:
    """Heurística acústico-conversacional para etiquetar Terapeuta vs Paciente.

    En una sesión terapéutica el paciente habla considerablemente más tiempo,
    mientras el terapeuta interviene más seguido y más breve. Esa asimetría
    es mucho más confiable que pedirle el rol a un LLM.
    """
    stats: dict[str, dict] = {}
    for seg in segments:
        spk = seg.get("speaker", "SPK_0")
        st = stats.setdefault(spk, {"talk": 0.0, "turns": 0, "questions": 0})
        st["talk"] += seg["end"] - seg["start"]
        st["turns"] += 1
        if "?" in seg.get("text", ""):
            st["questions"] += 1

    if not stats:
        return {}
    if len(stats) == 1:
        return {next(iter(stats)): "Paciente"}

    def score(item):
        spk, st = item
        avg_turn = st["talk"] / max(1, st["turns"])
        q_ratio = st["questions"] / max(1, st["turns"])
        # Puntaje alto = más probable terapeuta (turnos cortos, muchas preguntas).
        return q_ratio * 2.0 - avg_turn / 10.0

    ranked = sorted(stats.items(), key=score, reverse=True)
    roles = {ranked[0][0]: "Terapeuta"}
    for spk, _ in ranked[1:]:
        roles[spk] = "Paciente"
    return roles
