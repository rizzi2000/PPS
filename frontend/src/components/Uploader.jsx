import { useRef, useState } from 'react'
import { UploadCloud, Loader2, Check, AlertTriangle } from 'lucide-react'

const STAGES = [
  { id: 'upload',   label: 'Subida' },
  { id: 'decode',   label: 'Audio' },
  { id: 'asr',      label: 'Transcripción' },
  { id: 'diarize',  label: 'Hablantes' },
  { id: 'prosody',  label: 'Prosodia' },
  { id: 'llm',      label: 'Traducción' },
  { id: 'summary',  label: 'Resumen' },
]

export function Dropzone({ onFile, disabled }) {
  const [over, setOver] = useState(false)
  const inputRef = useRef(null)

  const pick = (files) => {
    const f = files?.[0]
    if (f) onFile(f)
  }

  return (
    <div
      className={`dropzone${over ? ' over' : ''}`}
      onClick={() => !disabled && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled) pick(e.dataTransfer.files) }}
      role="button" tabIndex={0}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && inputRef.current?.click()}
      aria-disabled={disabled}
    >
      <input ref={inputRef} type="file" hidden accept="audio/*,video/mp4"
             onChange={(e) => pick(e.target.files)} />
      <div className="dz-icon"><UploadCloud size={26} /></div>
      <h3>Arrastrá el audio de la sesión</h3>
      <p>O hacé clic para elegirlo. MP3, WAV, M4A, OGG, FLAC o WEBM, hasta 300&nbsp;MB.</p>
      <p className="disc">
        El waveform aparece a los pocos segundos; la transcripción se va mostrando mientras se procesa.
      </p>
    </div>
  )
}

export function ProgressRail({ progress, status, error }) {
  const currentIdx = STAGES.findIndex((s) => s.id === progress.stage)

  if (status === 'error') {
    return (
      <div className="card">
        <div className="card-body">
          <div className="progress-msg" style={{ color: 'var(--critical)' }}>
            <AlertTriangle size={15} />
            <span>{error || 'Ocurrió un error durante el procesamiento.'}</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="card-body">
        <div className="progress-rail">
          <div className="bar"><i style={{ width: `${progress.pct}%` }} /></div>

          <div className="stages">
            {STAGES.map((s, i) => {
              const done = currentIdx > i || status === 'done'
              const active = currentIdx === i && status !== 'done'
              return (
                <span key={s.id} className={`stage${active ? ' active' : ''}${done ? ' done' : ''}`}>
                  {done ? <Check size={11} />
                        : active ? <Loader2 size={11} className="spin" />
                        : <span style={{ width: 11 }} />}
                  {s.label}
                </span>
              )
            })}
          </div>

          <div className="progress-msg">
            <span>{progress.message}</span>
            <span style={{ marginLeft: 'auto', fontVariantNumeric: 'tabular-nums',
                           color: 'var(--ink-muted)' }}>
              {Math.round(progress.pct)}%
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
