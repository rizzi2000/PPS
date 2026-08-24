import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from 'react'
import WaveSurfer from 'wavesurfer.js'
import { Play, Pause, Rewind, FastForward, Activity } from 'lucide-react'
import { audioUrl } from '../api'
import { fmtTime, roleClass } from '../utils'

const SPEEDS = [0.75, 1, 1.25, 1.5, 2]

/**
 * Reproductor con waveform.
 *
 * Clave de rendimiento: se le pasan `peaks` y `duration` precalculados por el
 * backend, así WaveSurfer dibuja de inmediato y NO descarga ni decodifica el
 * archivo entero en el navegador. El audio se sirve con soporte de Range, por
 * lo que el seek funciona aunque la sesión dure una hora.
 */
const Player = forwardRef(function Player({ jobId, peaks, duration, turns, roles, currentTime, onTime }, ref) {
  const containerRef = useRef(null)
  const wsRef = useRef(null)
  const [ready, setReady] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)

  // Evita realimentación cuando el seek viene de la transcripción.
  const seekingRef = useRef(false)

  useEffect(() => {
    if (!peaks || !containerRef.current || !jobId) return

    const css = getComputedStyle(document.documentElement)
    const ws = WaveSurfer.create({
      container: containerRef.current,
      height: 96,
      waveColor: css.getPropertyValue('--axis').trim() || '#c3c2b7',
      progressColor: css.getPropertyValue('--accent').trim() || '#2a78d6',
      cursorColor: css.getPropertyValue('--ink').trim() || '#0b0b0b',
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: false,          // ya vienen normalizados desde el backend
      // Con peaks + duration, WaveSurfer 7 dibuja sin descargar ni decodificar:
      // el audio se reproduce por streaming (Range) desde el <audio> interno.
      peaks: [peaks],
      duration,
      url: audioUrl(jobId),
    })

    ws.on('ready', () => setReady(true))
    ws.on('play', () => setPlaying(true))
    ws.on('pause', () => setPlaying(false))
    ws.on('finish', () => setPlaying(false))
    ws.on('timeupdate', (t) => { if (!seekingRef.current) onTime(t) })

    wsRef.current = ws
    setReady(false)
    return () => { ws.destroy(); wsRef.current = null }
  }, [peaks, duration, jobId, onTime])

  useEffect(() => {
    wsRef.current?.setPlaybackRate(speed)
  }, [speed])

  useImperativeHandle(ref, () => ({
    seek(seconds) {
      const ws = wsRef.current
      if (!ws || !duration) return
      seekingRef.current = true
      ws.setTime(Math.max(0, Math.min(seconds, duration - 0.05)))
      onTime(seconds)
      requestAnimationFrame(() => { seekingRef.current = false })
    },
    toggle() { wsRef.current?.playPause() },
    isReady: () => ready,
  }), [duration, onTime, ready])

  const nudge = (delta) => {
    const ws = wsRef.current
    if (!ws) return
    ws.setTime(Math.max(0, Math.min(ws.getCurrentTime() + delta, duration - 0.05)))
  }

  // Atajos de teclado globales (se ignoran mientras se escribe en un input).
  useEffect(() => {
    const onKey = (e) => {
      const tag = e.target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.code === 'Space') { e.preventDefault(); wsRef.current?.playPause() }
      else if (e.code === 'ArrowLeft') { e.preventDefault(); nudge(e.shiftKey ? -30 : -5) }
      else if (e.code === 'ArrowRight') { e.preventDefault(); nudge(e.shiftKey ? 30 : 5) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [duration])

  return (
    <div className="card">
      <div className="card-head">
        <Activity size={16} />
        <h2>Señal acústica</h2>
        <div className="spacer" />
        <div className="seg" role="group" aria-label="Velocidad de reproducción">
          {SPEEDS.map((s) => (
            <button key={s} aria-pressed={speed === s} onClick={() => setSpeed(s)}>
              {s}×
            </button>
          ))}
        </div>
      </div>

      <div className="card-body" style={{ paddingBottom: 8 }}>
        <div className="wave-wrap">
          {!peaks && <div className="wave-skeleton" />}
          <div ref={containerRef} className="wave" style={{ display: peaks ? 'block' : 'none' }} />
          {turns?.length > 0 && (
            <SpeakerLane turns={turns} roles={roles} duration={duration} />
          )}
        </div>

        <div className="controls">
          <button className="play-btn" onClick={() => wsRef.current?.playPause()}
                  disabled={!ready} aria-label={playing ? 'Pausar' : 'Reproducir'}>
            {playing ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" style={{ marginLeft: 2 }} />}
          </button>

          <button className="btn icon ghost" onClick={() => nudge(-10)} disabled={!ready} aria-label="Retroceder 10 segundos">
            <Rewind size={17} />
          </button>
          <button className="btn icon ghost" onClick={() => nudge(10)} disabled={!ready} aria-label="Adelantar 10 segundos">
            <FastForward size={17} />
          </button>

          <span className="time"><b>{fmtTime(currentTime)}</b> / {fmtTime(duration)}</span>

          <div className="spacer" />

          <span style={{ fontSize: 11.5, color: 'var(--ink-muted)' }}>
            <span className="kbd">espacio</span> reproducir · <span className="kbd">← →</span> ±5s
          </span>
        </div>
      </div>
    </div>
  )
})

/** Franja de turnos: muestra de un vistazo quién habla a lo largo de la sesión. */
function SpeakerLane({ turns, roles, duration }) {
  if (!duration) return null
  const blocks = []
  let cursor = 0
  for (const t of turns) {
    if (t.start > cursor) blocks.push({ w: t.start - cursor, role: null })
    blocks.push({ w: Math.max(0, t.end - t.start), role: roles[t.speaker] })
    cursor = t.end
  }
  if (cursor < duration) blocks.push({ w: duration - cursor, role: null })

  return (
    <div className="speaker-lane" role="img" aria-label="Distribución de turnos de habla">
      {blocks.map((b, i) => (
        <span key={i} style={{
          width: `${(b.w / duration) * 100}%`,
          background: b.role ? `var(--spk-${roleClass(b.role)})` : 'transparent',
        }} />
      ))}
    </div>
  )
}

export default Player
