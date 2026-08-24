import { useMemo } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ReferenceArea,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { Waves, BarChart3, Users } from 'lucide-react'
import { fmtTime, roleClass, EMOTION_ORDER } from '../utils'

/**
 * Panel de métricas del paciente.
 *
 * Todo lo graficado acá se MIDE sobre la señal (prosody.py), no lo estima un
 * LLM. Fluidez y activación son z-scores del propio paciente: el 0 es su
 * línea de base personal, así que las desviaciones son interpretables.
 *
 * Dos series comparables en la misma unidad (z) pero en dos gráficos chicos
 * apilados (small multiples), no en ejes dobles.
 */
export default function Metrics({ segments, stats, roles, names, duration, currentTime, onSeek }) {
  const patientKey = useMemo(
    () => Object.keys(roles || {}).find((k) => roles[k] === 'Paciente'), [roles])

  const data = useMemo(() => segments
    .filter((s) => s.role === 'Paciente' && s.metrics)
    .map((s) => ({
      t: (s.start + s.end) / 2,
      start: s.start,
      fluidez: s.metrics.fluency_z,
      activacion: s.metrics.arousal_z,
      rate: s.metrics.articulation_rate,
      pausa: s.metrics.longest_pause,
      label: s.metrics.fluency_label,
      emocion: s.emocion,
    })), [segments])

  const emotions = useMemo(() => {
    const counts = new Map()
    segments.filter((s) => s.role === 'Paciente' && s.emocion)
      .forEach((s) => counts.set(s.emocion, (counts.get(s.emocion) || 0) + 1))
    return EMOTION_ORDER.filter((e) => counts.has(e))
      .map((e) => ({ emocion: e, n: counts.get(e) }))
  }, [segments])

  const patient = patientKey ? stats?.[patientKey] : null
  const hasData = data.length > 1

  return (
    <div className="card">
      <div className="card-head">
        <Waves size={16} />
        <h2>Métricas del paciente</h2>
        <div className="spacer" />
        <span style={{ fontSize: 11.5, color: 'var(--ink-muted)' }}>medidas sobre la señal</span>
      </div>

      <div className="card-body">
        {!hasData && <p className="empty">Las métricas aparecen cuando termina el análisis prosódico.</p>}

        {hasData && (
          <>
            {patient && (
              <div className="tiles" style={{ marginBottom: 20 }}>
                <Tile label="Tiempo de habla" value={fmtTime(patient.talk_time)} />
                <Tile label="Participación" value={patient.talk_share} unit="%" />
                <Tile label="Ritmo medio" value={patient.avg_rate} unit="síl/s" />
                <Tile label="Tono medio" value={patient.f0_median || '—'} unit={patient.f0_median ? 'Hz' : ''} />
                <Tile label="Turnos" value={patient.turns} />
              </div>
            )}

            <Trend
              title="Fluidez del habla"
              hint="z respecto de su propia línea de base · negativo = más lento y entrecortado"
              data={data} dataKey="fluidez" color="var(--spk-patient)"
              duration={duration} currentTime={currentTime} onSeek={onSeek}
            />

            <Trend
              title="Activación emocional"
              hint="energía + variabilidad tonal + velocidad"
              data={data} dataKey="activacion" color="var(--spk-patient)"
              duration={duration} currentTime={currentTime} onSeek={onSeek}
            />

            {emotions.length > 0 && (
              <div className="section">
                <p className="section-label"><BarChart3 size={11} style={{ verticalAlign: -1, marginRight: 5 }} />
                  Emociones del paciente</p>
                <div style={{ width: '100%', height: 30 + emotions.length * 26 }}>
                  <ResponsiveContainer>
                    <BarChart data={emotions} layout="vertical" margin={{ left: 4, right: 28, top: 2, bottom: 2 }}>
                      <XAxis type="number" hide />
                      <YAxis type="category" dataKey="emocion" width={82} axisLine={false} tickLine={false}
                             tick={{ fill: 'var(--ink-2)', fontSize: 11.5 }} />
                      <Bar dataKey="n" radius={[0, 4, 4, 0]} barSize={13}
                           label={{ position: 'right', fill: 'var(--ink-muted)', fontSize: 11 }}>
                        {emotions.map((e) => <Cell key={e.emocion} fill="var(--spk-patient)" />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </>
        )}

        {stats && Object.keys(stats).length > 0 && (
          <div className="section">
            <p className="section-label"><Users size={11} style={{ verticalAlign: -1, marginRight: 5 }} />
              Reparto del habla</p>
            <div className="share-bar">
              {Object.entries(stats).map(([spk, st]) => (
                <div key={spk}
                     style={{ width: `${st.talk_share}%`, background: `var(--spk-${roleClass(roles[spk])})` }}
                     title={`${names[spk]}: ${st.talk_share}%`}>
                  {st.talk_share >= 12 ? `${st.talk_share}%` : ''}
                </div>
              ))}
            </div>
            <div className="legend" style={{ marginTop: 9 }}>
              {Object.entries(stats).map(([spk, st]) => (
                <span className="k" key={spk}>
                  <span className="dot" style={{ background: `var(--spk-${roleClass(roles[spk])})` }} />
                  {names[spk]} · {fmtTime(st.talk_time)} · {st.turns} turnos
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Tile({ label, value, unit }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}<span className="unit">{unit}</span></div>
    </div>
  )
}

/** Serie única en el tiempo, con banda neutra y línea del cursor de audio. */
function Trend({ title, hint, data, dataKey, color, duration, currentTime, onSeek }) {
  return (
    <div className="section">
      <p className="section-label">{title}</p>
      <p style={{ margin: '-5px 0 8px', fontSize: 11.5, color: 'var(--ink-muted)' }}>{hint}</p>
      <div style={{ width: '100%', height: 132 }}>
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}
                     onClick={(e) => e?.activePayload?.[0] && onSeek(e.activePayload[0].payload.start)}
                     style={{ cursor: 'pointer' }}>
            <defs>
              <linearGradient id={`g-${dataKey}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.30} />
                <stop offset="100%" stopColor={color} stopOpacity={0.02} />
              </linearGradient>
            </defs>

            <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" vertical={false} />

            {/* Banda neutra: ±0.75 z = variación normal del propio paciente. */}
            <ReferenceArea y1={-0.75} y2={0.75} fill="var(--ink-muted)" fillOpacity={0.06} />
            <ReferenceLine y={0} stroke="var(--axis)" strokeWidth={1} />

            <XAxis dataKey="t" type="number" domain={[0, duration || 'dataMax']}
                   tickFormatter={fmtTime} tick={{ fill: 'var(--ink-muted)', fontSize: 10.5 }}
                   axisLine={{ stroke: 'var(--axis)' }} tickLine={false} minTickGap={44} />
            <YAxis domain={[-2.6, 2.6]} width={26} tick={{ fill: 'var(--ink-muted)', fontSize: 10.5 }}
                   axisLine={false} tickLine={false} ticks={[-2, 0, 2]} />

            <Tooltip content={<Tip dataKey={dataKey} />} cursor={{ stroke: 'var(--ink-muted)', strokeDasharray: '3 3' }} />

            <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2}
                  fill={`url(#g-${dataKey})`} isAnimationActive={false}
                  dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} />

            {/* Posición actual del audio */}
            <ReferenceLine x={currentTime} stroke="var(--ink)" strokeWidth={1.5} strokeOpacity={0.55} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function Tip({ active, payload, dataKey }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="chart-tip">
      <div className="t">{fmtTime(d.t)}</div>
      <div className="k">
        <span className="dot" style={{ background: 'var(--spk-patient)' }} />
        {dataKey === 'fluidez' ? 'Fluidez' : 'Activación'}: <b>{d[dataKey]?.toFixed(2)}</b>
      </div>
      <div className="k">Ritmo: {d.rate} síl/s</div>
      {d.pausa > 0.5 && <div className="k">Pausa máx: {d.pausa}s</div>}
      {d.emocion && <div className="k">Emoción: {d.emocion}</div>}
    </div>
  )
}
