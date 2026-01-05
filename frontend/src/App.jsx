import { useState, useRef} from 'react'
import axios from 'axios'
import WaveSurfer from 'wavesurfer.js'
import { Play, Pause, Upload, Activity, Brain, Clock, FileAudio } from 'lucide-react'
import { clsx } from 'clsx'
import './App.css'

// Configura aquí la URL de tu backend
const API_URL = 'http://127.0.0.1:8000/api/audio'

// Utilidad para convertir "MM:SS" a segundos para la sincronización
const timeToSeconds = (timeStr) => {
  if (!timeStr) return 0
  const parts = timeStr.split(':')
  return parseInt(parts[0]) * 60 + parseInt(parts[1])
}

function App() {
  // Estados de la aplicación
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState("idle") // idle, uploading, processing_ai, processing_rhythm, ready, error
  const [aiData, setAiData] = useState(null)
  const [rhythmData, setRhythmData] = useState(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)

  // Referencias DOM
  const waveformRef = useRef(null)
  const wavesurfer = useRef(null)

  // --- 1. PROCESO COMPLETO (Sucesión de Endpoints) ---
  const handleFullProcess = async () => {
    if (!file) return
    setStatus("uploading")
    
    try {
      // A. Subir Audio
      const formData = new FormData()
      formData.append('file', file)
      const uploadRes = await axios.post(`${API_URL}/upload`, formData)
      const serverFilename = uploadRes.data.filename

      // B. Procesar IA (Transcripción)
      setStatus("processing_ai")
      const aiRes = await axios.post(`${API_URL}/process-ai`, { filename: serverFilename })
      setAiData(aiRes.data.data)

      // C. Procesar Ritmo (Visualización)
      setStatus("processing_rhythm")
      const rhythmRes = await axios.post(`${API_URL}/process-rhythm`, { filename: serverFilename })
      setRhythmData(rhythmRes.data.data)

      // D. Iniciar Reproductor
      initWaveform(file, rhythmRes.data.data)
      setStatus("ready")

    } catch (error) {
      console.error(error)
      setStatus("error")
      alert("Hubo un error en el proceso. Revisa la consola.")
    }
  }

  // --- 2. CONFIGURACIÓN DEL REPRODUCTOR (WaveSurfer) ---
  const initWaveform = (audioFile, rhythmJson) => {
    console.log("Iniciando Waveform con datos de ritmo:", rhythmJson)
    if (wavesurfer.current) wavesurfer.current.destroy()

    const url = URL.createObjectURL(audioFile)
    
    wavesurfer.current = WaveSurfer.create({
      container: waveformRef.current,
      waveColor: '#e2e8f0', // Color base (gris suave)
      progressColor: '#6366f1', // Color progreso (violeta)
      cursorColor: '#4338ca',
      height: 120,
      barWidth: 3,
      barGap: 2,
      barRadius: 3,
      normalize: true,
    })

    wavesurfer.current.load(url)

    // Eventos
    wavesurfer.current.on('finish', () => setIsPlaying(false))
    wavesurfer.current.on('audioprocess', (time) => setCurrentTime(time))
    wavesurfer.current.on('seek', (time) => setCurrentTime(time * wavesurfer.current.getDuration()))
    
    // Aquí podrías pintar regiones de colores usando rhythmJson si instalas el plugin de regiones,
    // pero por ahora lo dejamos simple.
  }

  const togglePlay = () => {
    if (wavesurfer.current) {
      wavesurfer.current.playPause()
      setIsPlaying(!isPlaying)
    }
  }

  if (rhythmData) console.log("Datos de ritmo cargados:", rhythmData)

  return (
    <div className="layout">
      {/* BARRA LATERAL (Resumen) */}
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
            disabled={!file || status !== 'idle'} 
            className="process-btn"
          >
            {status === 'idle' && "Analizar Sesión"}
            {status === 'uploading' && "Subiendo..."}
            {status === 'processing_ai' && "Consultando IA..."}
            {status === 'processing_rhythm' && "Calculando Ritmo..."}
            {status === 'ready' && "Análisis Completo"}
          </button>
        </div>

        {aiData && (
          <div className="clinical-summary">
            <h3>Resumen Clínico</h3>
            <p>{aiData.resumen_clinico}</p>
            
            <div className="stats">
              <h4>Participantes Detectados</h4>
              <div className="roles-list">
                {aiData.roles_identificados.map((r, i) => (
                  <span key={i} className={`role-badge ${r.rol}`}>
                    {r.hablante}: {r.rol}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}
      </aside>

      {/* ÁREA PRINCIPAL */}
      <main className="main-content">
        
        {/* SECCIÓN VISUALIZACIÓN DE ONDA */}
        <div className="card waveform-card">
          <div className="card-header">
            <Activity size={20} />
            <h2>Análisis de Ritmo y Fluidez</h2>
          </div>
          <div ref={waveformRef} className="waveform-container"></div>
          
          <div className="controls">
            <button onClick={togglePlay} className="play-btn" disabled={status !== 'ready'}>
              {isPlaying ? <Pause /> : <Play />}
            </button>
            <span className="time-display">
              {new Date(currentTime * 1000).toISOString().substr(14, 5)}
            </span>
          </div>
        </div>

        {/* SECCIÓN TRANSCRIPCIÓN SINCRONIZADA */}
        <div className="card transcript-card">
          <div className="card-header">
            <FileAudio size={20} />
            <h2>Transcripción Clínica</h2>
          </div>
          
          <div className="transcript-list">
            {aiData ? aiData.dialogo.map((seg, index) => {
              // Lógica de Sincronización: ¿Está sonando este segmento ahora?
              const start = timeToSeconds(seg.inicio)
              const end = timeToSeconds(seg.fin)
              const isActive = currentTime >= start && currentTime <= end

              return (
                <div key={index} className={clsx("message-row", seg.rol, { active: isActive })}>
                  <div className="meta">
                    <span className="timestamp">{seg.inicio}</span>
                    <span className="speaker">{seg.hablante}</span>
                    {seg.emocion && <span className="emotion">({seg.emocion})</span>}
                  </div>
                  <div className="content">
                    <p className="text-es">{seg.texto_es}</p>
                    <p className="text-en">{seg.texto_en}</p>
                  </div>
                  <div className="metrics">
                     {seg.fluidez === 'bloqueo' && <span className="warning-badge">Bloqueo</span>}
                     {seg.fluidez === 'lento' && <span className="info-badge">Lento</span>}
                  </div>
                </div>
              )
            }) : (
              <div className="placeholder-text">
                Sube un audio para ver la transcripción detallada aquí.
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}

export default App