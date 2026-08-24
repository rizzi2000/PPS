import { useCallback, useEffect, useRef, useState } from 'react'
import { API, uploadSession } from './api'

const EMPTY = {
  jobId: null, filename: null,
  peaks: null, duration: 0,
  segments: [], turns: [], roles: {}, names: {}, stats: {},
  summary: null,
  progress: { stage: 'idle', pct: 0, message: '' },
  status: 'idle',        // idle | uploading | running | done | error
  error: null,
  elapsed: null,
}

/**
 * Estado del análisis alimentado por SSE.
 *
 * Cada etapa del backend actualiza una porción distinta, así que la UI puede
 * dibujar el waveform apenas llega `peaks`, ir mostrando la transcripción con
 * cada `segment`, y recién al final pintar métricas y resumen. Nunca se espera
 * a que termine todo.
 */
export function useAnalysis() {
  const [state, setState] = useState(EMPTY)
  const esRef = useRef(null)

  const close = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
  }, [])

  useEffect(() => close, [close])

  const subscribe = useCallback((jobId) => {
    close()
    const es = new EventSource(`${API}/sessions/${jobId}/events`)
    esRef.current = es

    es.onmessage = (msg) => {
      let payload
      try { payload = JSON.parse(msg.data) } catch { return }
      const { event, data } = payload

      setState((prev) => {
        switch (event) {
          case 'progress':
            return { ...prev, status: 'running', progress: data }

          case 'peaks':
            // El waveform ya puede dibujarse: no esperamos a la transcripción.
            return { ...prev, peaks: data.data, duration: data.duration }

          case 'segment':
            // Streaming de transcripción: se agrega apenas está listo.
            return { ...prev, segments: [...prev.segments, { ...data, provisional: true }] }

          case 'speakers':
            return { ...prev, turns: data.turns, roles: data.roles, names: data.names }

          case 'segments_final':
            // Reemplaza los provisionales por los ya cortados por hablante.
            return { ...prev, segments: data.segments, stats: data.stats }

          case 'translations': {
            const segments = prev.segments.map((s, i) => {
              const t = data[i]
              return t ? { ...s, text_en: t.text_en, emocion: t.emocion, tema: t.tema } : s
            })
            return { ...prev, segments }
          }

          case 'summary':
            return { ...prev, summary: data }

          case 'done':
            close()
            return { ...prev, status: 'done', elapsed: data.elapsed,
                     progress: { stage: 'done', pct: 100, message: 'Análisis completo' } }

          case 'error':
            close()
            return { ...prev, status: 'error', error: data.message }

          default:
            return prev
        }
      })
    }

    es.onerror = () => {
      // El navegador reintenta solo; solo marcamos error si nunca arrancó.
      setState((prev) => prev.status === 'done' ? prev : prev)
    }
  }, [close])

  const start = useCallback(async (file, speakers) => {
    setState({ ...EMPTY, status: 'uploading', filename: file.name,
               progress: { stage: 'upload', pct: 0, message: 'Subiendo audio...' } })
    try {
      const res = await uploadSession(file, {
        speakers,
        onProgress: (p) => setState((prev) => ({
          ...prev,
          progress: { stage: 'upload', pct: p * 100, message: `Subiendo ${Math.round(p * 100)}%` },
        })),
      })
      setState((prev) => ({ ...prev, jobId: res.job_id, status: 'running' }))
      subscribe(res.job_id)
    } catch (e) {
      setState((prev) => ({ ...prev, status: 'error', error: e.message }))
    }
  }, [subscribe])

  const load = useCallback((result) => {
    close()
    setState({
      ...EMPTY,
      jobId: result.job_id,
      filename: result.filename,
      duration: result.duration,
      segments: result.segments || [],
      roles: result.speakers?.roles || {},
      names: result.speakers?.names || {},
      stats: result.speakers?.stats || {},
      summary: result.summary,
      status: 'done',
      elapsed: result.elapsed,
      progress: { stage: 'done', pct: 100, message: 'Sesión cargada' },
    })
  }, [close])

  const reset = useCallback(() => { close(); setState(EMPTY) }, [close])

  return { state, start, load, reset }
}
