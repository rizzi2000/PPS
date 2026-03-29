import { useState, useRef, useEffect } from 'react'
import axios from 'axios'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.js'
import { Play, Pause, Upload, Activity, Brain, FileAudio } from 'lucide-react'
import { clsx } from 'clsx'
import './App.css'

const API_URL = 'http://127.0.0.1:8000/api/audio'

const timeToSeconds = (timeStr) => {
  if (!timeStr) return 0
  const parts = timeStr.split(':')
  if (parts.length < 2) return 0
  return parseInt(parts[0]) * 60 + parseInt(parts[1])
}

function App() {
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState("idle") 
  const [aiData, setAiData] = useState(null)
  const [rhythmData, setRhythmData] = useState(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)

  const waveformRef = useRef(null)
  const wavesurfer = useRef(null)
  const activeMessageRef = useRef(null) // Para auto-scroll

  // Efecto para auto-scroll de la transcripción
  useEffect(() => {
    if (activeMessageRef.current) {
      activeMessageRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center'
      })
    }
  }, [currentTime])

  const handleFullProcess = async () => {
    if (!file) return
    setStatus("uploading")
    
    try {
      const formData = new FormData()
      formData.append('file', file)
      const uploadRes = await axios.post(`${API_URL}/upload`, formData)
      const serverFilename = uploadRes.data.filename

      setStatus("processing_ai")
      const res = await axios.post(`${API_URL}/process-ai`, { filename: serverFilename });
      
      if (res.data && res.data.ai_data) {
        setAiData(res.data.ai_data);
        setRhythmData(res.data.rhythm_data || []);
        initWaveform(file, res.data.rhythm_data || []);
        setStatus("ready");
      }
    } catch (error) {
      console.error("Error en el proceso:", error);
      setStatus("error");
    }
  }

  const initWaveform = (audioFile, rhythmJson) => {
    if (wavesurfer.current) wavesurfer.current.destroy()

    const url = URL.createObjectURL(audioFile)
    
    const ws = WaveSurfer.create({
      container: waveformRef.current,
      waveColor: '#cbd5e1',
      progressColor: '#6366f1',
      cursorColor: '#4338ca',
      height: 120,
      barWidth: 2,
      barGap: 1,
      normalize: true,
      plugins: [RegionsPlugin.create()]
    })

    const regions = ws.registerPlugin(RegionsPlugin.create())

    ws.on('ready', () => {
      // PINTAR REGIONES SEGÚN EL RITMO FÍSICO
      rhythmJson.forEach((point, index) => {
        const duration = ws.getDuration()
        const end = rhythmJson[index + 1] ? rhythmJson[index + 1].timestamp : duration
        
        let color = 'rgba(148, 163, 184, 0.1)'; // Normal (Gris)
        if (point.tipo === 'pausa') color = 'rgba(239, 68, 68, 0.25)'; // Rojo
        if (point.tipo === 'acelerado') color = 'rgba(34, 197, 94, 0.25)'; // Verde
        if (point.tipo === 'fluidez_alterada') color = 'rgba(245, 158, 11, 0.25)'; // Naranja
        if (point.tipo === 'ajeno') color = 'rgba(0, 0, 0, 0.05)'; // Parte del terapeuta o ruido

        regions.addRegion({
          start: point.timestamp,
          end: end,
          color: color,
          drag: false,
          resize: false
        });
      });
    });

    ws.load(url)
    ws.on('finish', () => setIsPlaying(false))
    ws.on('audioprocess', (time) => setCurrentTime(time))
    ws.on('seek', (progress) => setCurrentTime(progress * ws.getDuration()))
    
    wavesurfer.current = ws
  }

  const togglePlay = () => {
    if (wavesurfer.current) {
      wavesurfer.current.playPause()
      setIsPlaying(!isPlaying)
    }
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <Brain size={32} color="#6366f1" />
          <h1>NeuroVoice</h1>
        </div>

        <div className="upload-container">
          <input type="file" id="file" onChange={(e) => setFile(e.target.files[0])} hidden accept="audio/*" />
          <label htmlFor="file" className="upload-btn">
            <Upload size={18} />
            {file ? file.name.substring(0, 20) + "..." : "Seleccionar Audio"}
          </label>
          <button 
            onClick={handleFullProcess} 
            disabled={!file || (status !== 'idle' && status !== 'ready' && status !== 'error')} 
            className="process-btn"
          >
            {status === 'idle' && "Analizar Sesión"}
            {status === 'uploading' && "Subiendo..."}
            {status === 'processing_ai' && "Procesando IA y Ritmo..."}
            {status === 'ready' && "Análisis Completo"}
            {status === 'error' && "Error (Reintentar)"}
          </button>
        </div>

        {aiData && (
          <div className="clinical-summary">
            <h3>Resumen Clínico</h3>
            <p>{aiData.resumen}</p>
            <div className="risk-indicator">
                <h4>Riesgo: <span className={`riesgo-${aiData.riesgo?.toLowerCase()}`}>{aiData.riesgo}</span></h4>
            </div>
          </div>
        )}
      </aside>

      <main className="main-content">
        <div className="card waveform-card">
          <div className="card-header">
            <Activity size={20} />
            <h2>Análisis de Fluidez (Paciente)</h2>
          </div>
          <div ref={waveformRef} className="waveform-container"></div>
          
          <div className="controls">
            <button onClick={togglePlay} className="play-btn" disabled={status !== 'ready'}>
              {isPlaying ? <Pause /> : <Play />}
            </button>
            <span className="time-display">
              {new Date(currentTime * 1000).toISOString().substr(14, 5)}
            </span>
            {rhythmData && (
              <div className="legend">
              <span className="dot pausa"></span> Pausa 
              <span className="dot alterada"></span> Bloqueo 
              <span className="dot normal"></span> Normal
            </div>
            )}
          </div>
        </div>

        <div className="card transcript-card">
          <div className="card-header">
            <FileAudio size={20} />
            <h2>Transcripción por Hablante</h2>
          </div>
          <div className="transcript-list">
            {aiData?.dialogo?.map((seg, index) => {
              const start = timeToSeconds(seg.inicio)
              const end = timeToSeconds(seg.fin)
              const isActive = currentTime >= start && currentTime <= end

              return (
                <div 
                  key={index} 
                  ref={isActive ? activeMessageRef : null}
                  className={clsx("message-row", seg.rol?.toLowerCase(), { active: isActive })}
                >
                  <div className="meta">
                    <span className="timestamp">{seg.inicio}</span>
                    <span className="speaker-name">{seg.hablante}</span>
                    <span className="role-tag">{seg.rol}</span>
                    <span className="emotion-tag">{seg.emocion}</span>
                  </div>
                  <div className="content">
                    <p className="text-es">{seg.texto_es}</p>
                    <p className="text-en">{seg.texto_en}</p>
                  </div>
                  <div className="metrics">
                     {seg.fluidez !== 'Normal' && (
                        <span className={clsx("fluidez-badge", seg.fluidez?.toLowerCase())}>
                            {seg.fluidez}
                        </span>
                     )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </main>
    </div>
  )
}

export default App