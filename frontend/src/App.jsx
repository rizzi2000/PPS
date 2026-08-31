import { useCallback, useEffect, useRef, useState } from 'react'
import { AudioWaveform, Moon, Sun, Download, RotateCcw, History, X } from 'lucide-react'
import { useAnalysis } from './useAnalysis'
import { exportJSON, getSession, listSessions } from './api'
import { Dropzone, ProgressRail } from './components/Uploader'
import Player from './components/Player'
import Transcript from './components/Transcript'
import Metrics from './components/Metrics'
import MetricsLab from './components/MetricsLab'
import Summary from './components/Summary'
import './styles.css'

export default function App() {
  const { state, start, load, reset } = useAnalysis()
  const [currentTime, setCurrentTime] = useState(0)
  const [theme, setTheme] = useState(() => localStorage.getItem('nv-theme') || 'system')
  const [sessions, setSessions] = useState([])
  const [showHistory, setShowHistory] = useState(false)
  const [labOpen, setLabOpen] = useState(false)
  const playerRef = useRef(null)

  useEffect(() => {
    if (theme === 'system') document.documentElement.removeAttribute('data-theme')
    else document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('nv-theme', theme)
  }, [theme])

  const refreshSessions = useCallback(() => {
    listSessions().then(setSessions).catch(() => {})
  }, [])

  useEffect(() => { refreshSessions() }, [refreshSessions])
  useEffect(() => { if (state.status === 'done') refreshSessions() }, [state.status, refreshSessions])

  const handleSeek = useCallback((t) => {
    playerRef.current?.seek(t)
    setCurrentTime(t)
  }, [])

  const handleFile = useCallback((file) => {
    setCurrentTime(0)
    setLabOpen(false)
    start(file)
  }, [start])

  const openSession = async (id) => {
    try {
      const data = await getSession(id)
      setCurrentTime(0)
      setLabOpen(false)
      load(data)
      setShowHistory(false)
    } catch { /* sesión aún en proceso */ }
  }

  const busy = state.status === 'uploading' || state.status === 'running'
  const started = state.status !== 'idle'

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <AudioWaveform size={21} />
          NeuroVoice
          <small>análisis de sesiones</small>
        </div>

        {state.filename && (
          <span style={{ fontSize: 12.5, color: 'var(--ink-2)', overflow: 'hidden',
                         textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 320 }}>
            {state.filename}
            {state.elapsed && (
              <span style={{ color: 'var(--ink-muted)' }}>
                {' · '}procesado en {state.elapsed}s
              </span>
            )}
          </span>
        )}

        <div className="spacer" />

        <button className="btn ghost" onClick={() => setShowHistory((v) => !v)}>
          <History size={16} /> Sesiones
        </button>

        {state.status === 'done' && (
          <button className="btn ghost" onClick={() => getSession(state.jobId)
            .then((d) => exportJSON(d, `${state.filename || 'sesion'}.json`))}>
            <Download size={16} /> Exportar
          </button>
        )}

        {started && (
          <button className="btn ghost" onClick={() => { reset(); setCurrentTime(0) }} disabled={busy}>
            <RotateCcw size={16} /> Nueva
          </button>
        )}

        <button className="btn icon ghost" onClick={() => setTheme((t) => t === 'dark' ? 'light' : 'dark')}
                aria-label="Cambiar tema">
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>

      {showHistory && (
        <HistoryPanel sessions={sessions} onOpen={openSession} onClose={() => setShowHistory(false)} />
      )}

      {!started ? (
        <div style={{ display: 'grid', placeItems: 'center', flex: 1, padding: 24 }}>
          <div style={{ width: 'min(620px, 100%)' }}>
            <Dropzone onFile={handleFile} />
          </div>
        </div>
      ) : (
        <div className="workspace">
          <div className="col">
            {state.status !== 'done' && (
              <ProgressRail progress={state.progress} status={state.status} error={state.error} />
            )}

            <Player
              ref={playerRef}
              jobId={state.jobId}
              peaks={state.peaks}
              duration={state.duration}
              turns={state.turns}
              roles={state.roles}
              currentTime={currentTime}
              onTime={setCurrentTime}
            />

            <Transcript
              segments={state.segments}
              currentTime={currentTime}
              onSeek={handleSeek}
              loading={busy}
            />
          </div>

          <div className="col">
            <Summary summary={state.summary} loading={busy} />
            <Metrics
              segments={state.segments}
              stats={state.stats}
              roles={state.roles}
              names={state.names}
              duration={state.duration}
              currentTime={currentTime}
              onSeek={handleSeek}
              onExpand={() => setLabOpen(true)}
            />
          </div>
        </div>
      )}

      {labOpen && (
        <MetricsLab
          segments={state.segments}
          stats={state.stats}
          roles={state.roles}
          names={state.names}
          duration={state.duration}
          currentTime={currentTime}
          onSeek={handleSeek}
          onClose={() => setLabOpen(false)}
        />
      )}

      {state.status === 'error' && !busy && (
        <div className="toast"><X size={15} />{state.error}</div>
      )}
    </div>
  )
}

function HistoryPanel({ sessions, onOpen, onClose }) {
  return (
    <div className="card" style={{ margin: '12px 16px 0' }}>
      <div className="card-head">
        <History size={16} /><h2>Sesiones analizadas</h2>
        <div className="spacer" />
        <button className="btn ghost icon" onClick={onClose} aria-label="Cerrar"><X size={15} /></button>
      </div>
      <div className="card-body" style={{ maxHeight: 220, overflowY: 'auto' }}>
        {sessions.length === 0
          ? <p className="empty">Todavía no hay sesiones guardadas.</p>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {sessions.map((s) => (
                <button key={s.id} className="row" style={{ gridTemplateColumns: '1fr auto' }}
                        onClick={() => s.status === 'done' && onOpen(s.id)}
                        disabled={s.status !== 'done'}>
                  <span style={{ fontSize: 13 }}>{s.filename}</span>
                  <span className="chip">{s.status === 'done' ? 'Listo' : s.status}</span>
                </button>
              ))}
            </div>
          )}
      </div>
    </div>
  )
}
