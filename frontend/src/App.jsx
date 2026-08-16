import { useState, useRef, useEffect, useMemo } from 'react'
import axios from 'axios'
import WaveSurfer from 'wavesurfer.js'
import RegionsPlugin from 'wavesurfer.js/dist/plugins/regions.js'
import { Play, Pause, Upload, Activity, Brain, FileAudio, LineChart as ChartIcon } from 'lucide-react'
import { clsx } from 'clsx'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceArea, ReferenceLine } from 'recharts'
import './App.css'

const API_URL = 'http://127.0.0.1:8000/api/audio'

const timeToSeconds = (timeStr) => {
  if (!timeStr) return 0
  const parts = timeStr.split(':')
  if (parts.length < 2) return 0
  return parseInt(parts[0]) * 60 + parseInt(parts[1])
}

const formatTime = (secs) => {
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s < 10 ? '0' : ''}${s}`
}

// SOLUCIÓN: El Tooltip se define AFUERA del componente App
const CustomTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    const data = payload[0].payload;
    return (
      <div className="chart-tooltip" style={{ background: '#fff', padding: '10px', border: '1px solid #e2e8f0', borderRadius: '8px', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' }}>
        <p style={{ margin: 0, fontWeight: 'bold', color: '#334155' }}>{formatTime(data.time)}</p>
        <p style={{ margin: '4px 0 0 0', color: '#4f46e5' }}>Fluidez: {data.etiqueta} ({data.fluidez})</p>
        <p style={{ margin: '4px 0 0 0', color: '#0ea5e9' }}>Emoción: {data.emocion}</p>
      </div>
    );
  }
  return null;
};

function App() {
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState("idle") 
  const [aiData, setAiData] = useState(null)
  const [rhythmData, setRhythmData] = useState(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  // SOLUCIÓN: Estado para guardar la duración y no leer la referencia en el render
  const [audioDuration, setAudioDuration] = useState(0) 

  const waveformRef = useRef(null)
  const wavesurfer = useRef(null)
  const activeMessageRef = useRef(null)

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
      height: 100, 
      barWidth: 2,
      barGap: 1,
      normalize: true,
      plugins: [RegionsPlugin.create()]
    })

    const regions = ws.registerPlugin(RegionsPlugin.create())

    ws.on('ready', () => {
      // Guardamos la duración aquí
      setAudioDuration(ws.getDuration())

      rhythmJson.forEach((point, index) => {
        const duration = ws.getDuration()
        const end = rhythmJson[index + 1] ? rhythmJson[index + 1].timestamp : duration
        
        let color = 'rgba(148, 163, 184, 0.1)'
        if (point.tipo === 'pausa') color = 'rgba(239, 68, 68, 0.25)'
        if (point.tipo === 'acelerado') color = 'rgba(34, 197, 94, 0.25)'
        if (point.tipo === 'fluidez_alterada') color = 'rgba(245, 158, 11, 0.25)'
        if (point.tipo === 'ajeno') color = 'rgba(0, 0, 0, 0.05)'

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

  const chartData = useMemo(() => {
    if (!aiData || !aiData.dialogo) return [];
    
    return aiData.dialogo
      .filter(seg => seg.rol === 'Paciente')
      .reduce((acc, seg) => {
        const start = timeToSeconds(seg.inicio);
        const end = timeToSeconds(seg.fin);
        const val = isNaN(Number(seg.nivel_fluidez)) ? 0.5 : Number(seg.nivel_fluidez);
        
        acc.push({ time: start, fluidez: val, etiqueta: seg.fluidez, emocion: seg.emocion });
        acc.push({ time: end,   fluidez: val, etiqueta: seg.fluidez, emocion: seg.emocion });
        return acc;
      }, []);
  }, [aiData]);

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
            <h2>Señal Acústica (Micropauses)</h2>
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

        {aiData && chartData.length > 0 && (
          <div className="card chart-card" style={{ marginTop: '20px' }}>
            <div className="card-header" style={{ marginBottom: '15px' }}>
              <ChartIcon size={20} />
              <h2>Flujo de Fluidez (Paciente)</h2>
            </div>
            
            <div style={{ width: '100%', height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chartData} margin={{ top: 10, right: 20, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  
                  {/* Se utiliza audioDuration en lugar de wavesurfer.current */}
                  <XAxis 
                    dataKey="time" 
                    type="number" 
                    domain={[0, audioDuration || 'dataMax']} 
                    tickFormatter={formatTime} 
                    stroke="#94a3b8" 
                    minTickGap={30}
                  />
                  <YAxis domain={[-1.5, 2]} hide={true} />
                  
                  <Tooltip content={<CustomTooltip />} />

                  <ReferenceArea y1={-1.5} y2={0.0} fill="#fee2e2" fillOpacity={0.6} /> 
                  <ReferenceArea y1={0.0}  y2={1.0} fill="#f1f5f9" fillOpacity={0.6} /> 
                  <ReferenceArea y1={1.0}  y2={2.0} fill="#fef3c7" fillOpacity={0.6} /> 

                  <ReferenceLine x={currentTime} stroke="#ef4444" strokeWidth={2} />

                  <Area 
                    type="monotone" 
                    dataKey="fluidez" 
                    stroke="#4f46e5" 
                    strokeWidth={3}
                    fill="#818cf8" 
                    fillOpacity={0.4} 
                    isAnimationActive={false} 
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="legend" style={{ justifyContent: 'center', marginTop: '10px' }}>
                <span className="dot" style={{ background: '#fee2e2' }}></span> Zona Baja (Bloqueo)
                <span className="dot" style={{ background: '#f1f5f9' }}></span> Zona Normal
                <span className="dot" style={{ background: '#fef3c7' }}></span> Zona Alta (Acelerado)
            </div>
          </div>
        )}

        <div className="card transcript-card" style={{ marginTop: '20px' }}>
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
                     {seg.fluidez && seg.fluidez !== 'Normal' && (
                        <span className={clsx("fluidez-badge", seg.fluidez.toLowerCase())}>
                            {seg.fluidez} ({seg.nivel_fluidez})
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