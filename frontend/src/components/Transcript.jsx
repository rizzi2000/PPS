import { useEffect, useMemo, useRef, useState } from 'react'
import { FileText, Search, Crosshair } from 'lucide-react'
import { fmtTime, roleClass, findActiveIndex, levelTone } from '../utils'

const VIEWS = [
  { id: 'es', label: 'ES' },
  { id: 'both', label: 'ES + EN' },
  { id: 'en', label: 'EN' },
]

export default function Transcript({ segments, currentTime, onSeek, loading }) {
  const [view, setView] = useState('es')
  const [query, setQuery] = useState('')
  const [follow, setFollow] = useState(true)
  const [speaker, setSpeaker] = useState('all')
  const activeRef = useRef(null)
  const listRef = useRef(null)

  const activeIndex = useMemo(
    () => findActiveIndex(segments, currentTime), [segments, currentTime])

  const speakers = useMemo(() => {
    const set = new Map()
    segments.forEach((s) => s.speaker_name && set.set(s.speaker_name, s.role))
    return [...set.entries()]
  }, [segments])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return segments
      .map((s, i) => ({ ...s, _i: i }))
      .filter((s) => speaker === 'all' || s.speaker_name === speaker)
      .filter((s) => !q ||
        s.text?.toLowerCase().includes(q) ||
        s.text_en?.toLowerCase().includes(q))
  }, [segments, query, speaker])

  // Auto-scroll: sólo cuando el usuario no está explorando manualmente.
  useEffect(() => {
    if (!follow || !activeRef.current) return
    activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [activeIndex, follow])

  useEffect(() => {
    const el = listRef.current
    if (!el) return
    let timer
    const onWheel = () => {
      setFollow(false)
      clearTimeout(timer)
      timer = setTimeout(() => setFollow(true), 6000)  // vuelve solo
    }
    el.addEventListener('wheel', onWheel, { passive: true })
    return () => { el.removeEventListener('wheel', onWheel); clearTimeout(timer) }
  }, [])

  return (
    <div className="card">
      <div className="card-head">
        <FileText size={16} />
        <h2>Transcripción</h2>
        <div className="spacer" />
        <span style={{ fontSize: 11.5, color: 'var(--ink-muted)' }}>
          {segments.length} enunciados
        </span>
      </div>

      <div className="transcript-tools">
        <label className="search">
          <Search size={14} />
          <input value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="Buscar en la transcripción..." aria-label="Buscar" />
        </label>

        <div className="seg" role="group" aria-label="Idioma">
          {VIEWS.map((v) => (
            <button key={v.id} aria-pressed={view === v.id} onClick={() => setView(v.id)}>
              {v.label}
            </button>
          ))}
        </div>

        {speakers.length > 1 && (
          <div className="seg" role="group" aria-label="Filtrar por hablante">
            <button aria-pressed={speaker === 'all'} onClick={() => setSpeaker('all')}>Todos</button>
            {speakers.map(([name, role]) => (
              <button key={name} aria-pressed={speaker === name} onClick={() => setSpeaker(name)}>
                <span className="dot" style={{ background: `var(--spk-${roleClass(role)})`,
                  display: 'inline-block', marginRight: 5, verticalAlign: -1 }} />
                {name}
              </button>
            ))}
          </div>
        )}

        <button className={`btn ghost icon`} onClick={() => setFollow((f) => !f)}
                title={follow ? 'Seguimiento activado' : 'Seguimiento desactivado'}
                aria-pressed={follow}>
          <Crosshair size={16} style={{ color: follow ? 'var(--accent)' : 'var(--ink-muted)' }} />
        </button>
      </div>

      <div className="transcript" ref={listRef}>
        {filtered.length === 0 && (
          <p className="empty">
            {loading ? 'La transcripción va apareciendo a medida que se procesa...'
                     : 'Sin resultados.'}
          </p>
        )}

        {filtered.map((seg) => {
          const active = seg._i === activeIndex
          return (
            <button
              key={seg._i}
              ref={active ? activeRef : null}
              className={`row${active ? ' active' : ''}`}
              onClick={() => onSeek(seg.start)}
              aria-current={active ? 'true' : undefined}
            >
              <span className="ts">{fmtTime(seg.start)}</span>

              <span>
                <span className="who">
                  <span className={`name ${roleClass(seg.role)}`}>
                    {seg.speaker_name || 'Procesando...'}
                  </span>
                  {seg.emocion && seg.emocion !== 'Neutral' && (
                    <span className="chip">{seg.emocion}</span>
                  )}
                  {seg.metrics?.speed_label && seg.metrics.speed_label !== 'Normal' && (
                    <span className={`chip ${levelTone(seg.metrics.speed_label) || ''}`}>
                      {seg.metrics.speed_label}
                    </span>
                  )}
                  {seg.metrics?.blocked && (
                    <span className="chip critical">
                      Silencio {seg.metrics.silence}s
                    </span>
                  )}
                </span>

                {view !== 'en' && (
                  <p className="es">
                    {active && seg.words?.length
                      ? <Words words={seg.words} t={currentTime} />
                      : <Highlight text={seg.text} query={query} />}
                  </p>
                )}
                {view !== 'es' && seg.text_en && (
                  <p className="en"><Highlight text={seg.text_en} query={query} /></p>
                )}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/**
 * Resaltado palabra por palabra usando los timestamps de faster-whisper.
 * Esta es la sincronía fina que antes no existía: los bloques duraban 30 s
 * y el tiempo estaba redondeado a segundos enteros en formato MM:SS.
 */
function Words({ words, t }) {
  return words.map((w, i) => {
    const state = t >= w.s && t <= w.e ? 'now' : t > w.e ? 'spoken' : ''
    const low = w.p < 0.5 ? ' low' : ''   // baja confianza: revisar manualmente
    return (
      <span key={i} className={`word ${state}${low}`} title={w.p < 0.5 ? `Confianza ${Math.round(w.p * 100)}%` : undefined}>
        {w.w}{i < words.length - 1 ? ' ' : ''}
      </span>
    )
  })
}

function Highlight({ text, query }) {
  const q = query.trim()
  if (!q || !text) return text || null
  const parts = text.split(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig'))
  return parts.map((p, i) =>
    p.toLowerCase() === q.toLowerCase() ? <mark key={i}>{p}</mark> : p)
}
