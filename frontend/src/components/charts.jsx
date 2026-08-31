import {
  Area, AreaChart, Bar, BarChart, Brush, CartesianGrid, Cell, ReferenceArea,
  ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { fmtTime } from '../utils'

/**
 * Primitivos de gráfico compartidos entre el panel compacto y el expandido.
 *
 * Reglas que se respetan en todos:
 *  - Una sola escala por gráfico. Nunca dos ejes Y: dos magnitudes distintas
 *    van en dos gráficos apilados (small multiples), no superpuestas.
 *  - Serie única = sin leyenda; el título ya la nombra.
 *  - Grilla y ejes recesivos; el dato es lo único con peso visual.
 *  - Tooltip siempre, porque un gráfico en HTML es interactivo por defecto.
 */

export function Tile({ label, value, unit, hint, tone }) {
  return (
    <div className={`tile${tone ? ` tone-${tone}` : ''}`}>
      <div className="label">{label}</div>
      <div className="value">{value}<span className="unit">{unit}</span></div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

function Tip({ active, payload, series }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="chart-tip">
      <div className="t">{fmtTime(d.t)}</div>
      <div className="k">
        <span className="dot" style={{ background: 'var(--spk-patient)' }} />
        {series.label}: <b>{series.fmt(d[series.key], d)}</b>
      </div>
      <div className="k">{d.rate} sílabas por segundo</div>
      {d.pausa > 0.5 && <div className="k">Silencio: {d.pausa}s</div>}
      {d.emocion && <div className="k">Emoción: {d.emocion}</div>}
      <div className="k hintline">clic para ir a este momento</div>
    </div>
  )
}

/**
 * Serie única en el tiempo.
 *
 * `band` marca el rango considerado normal, para que una desviación se lea sin
 * tener que interpretar el número. `blocks` resalta los bloqueos (pausas
 * largas), que es el evento que más interesa localizar en una sesión.
 */
export function Trend({
  data, series, duration, currentTime, onSeek,
  height = 130, band, zero = false, brush = false, blocks = [],
}) {
  const gid = `grad-${series.key}`
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer>
        <AreaChart
          data={data} syncId="metricas"
          margin={{ top: 6, right: 10, left: 6, bottom: brush ? 0 : 2 }}
          onClick={(e) => e?.activePayload?.[0] && onSeek?.(e.activePayload[0].payload.start)}
          style={{ cursor: onSeek ? 'pointer' : 'default' }}
        >
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--spk-patient)" stopOpacity={0.32} />
              <stop offset="100%" stopColor="var(--spk-patient)" stopOpacity={0.02} />
            </linearGradient>
          </defs>

          <CartesianGrid stroke="var(--grid)" strokeDasharray="2 4" vertical={false} />

          {band && (
            <ReferenceArea y1={band[0]} y2={band[1]} fill="var(--ink-muted)" fillOpacity={0.07}
                           label={{ value: band[2], position: 'insideTopRight',
                                    fill: 'var(--ink-muted)', fontSize: 10 }} />
          )}
          {zero && <ReferenceLine y={0} stroke="var(--axis)" strokeWidth={1} />}

          <XAxis dataKey="t" type="number" domain={[0, duration || 'dataMax']}
                 tickFormatter={fmtTime} tick={{ fill: 'var(--ink-muted)', fontSize: 10.5 }}
                 axisLine={{ stroke: 'var(--axis)' }} tickLine={false} minTickGap={46} />
          <YAxis domain={series.domain} width={series.tickNames ? 62 : 40}
                 tick={{ fill: 'var(--ink-muted)', fontSize: 10.5 }}
                 axisLine={false} tickLine={false} ticks={series.ticks}
                 tickFormatter={(v) => series.tickNames?.[String(v)] ?? v} />

          <Tooltip content={<Tip series={series} />}
                   cursor={{ stroke: 'var(--ink-muted)', strokeDasharray: '3 3' }} />

          <Area type="monotone" dataKey={series.key} stroke="var(--spk-patient)" strokeWidth={2}
                fill={`url(#${gid})`} isAnimationActive={false} dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }} />

          {/* Bloqueos: pausas largas, marcadas donde ocurren. */}
          {blocks.map((b) => (
            <ReferenceLine key={b.t} x={b.t} stroke="var(--critical)" strokeWidth={1.5}
                           strokeDasharray="2 2" />
          ))}

          <ReferenceLine x={currentTime} stroke="var(--ink)" strokeWidth={1.5} strokeOpacity={0.55} />

          {brush && (
            <Brush dataKey="t" height={20} travellerWidth={8} tickFormatter={fmtTime}
                   stroke="var(--axis)" fill="var(--surface-2)" />
          )}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Recuento por emoción: magnitud sobre categorías -> un solo tono. */
export function EmotionBars({ emotions, height }) {
  return (
    <div style={{ width: '100%', height: height ?? 30 + emotions.length * 26 }}>
      <ResponsiveContainer>
        <BarChart data={emotions} layout="vertical"
                  margin={{ left: 4, right: 34, top: 2, bottom: 2 }}>
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="emocion" width={88} axisLine={false} tickLine={false}
                 tick={{ fill: 'var(--ink-2)', fontSize: 11.5 }} />
          <Tooltip cursor={{ fill: 'var(--surface-2)' }}
                   contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border-2)',
                                   borderRadius: 9, fontSize: 12 }}
                   formatter={(v) => [`${v} enunciados`, '']} />
          <Bar dataKey="n" radius={[0, 4, 4, 0]} barSize={14}
               label={{ position: 'right', fill: 'var(--ink-muted)', fontSize: 11 }}>
            {emotions.map((e) => <Cell key={e.emocion} fill="var(--spk-patient)" />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Reparto del habla. El color sigue al hablante, nunca al orden. */
export function ShareBar({ stats, roles, names, roleClass, fmt }) {
  const entries = Object.entries(stats || {})
  if (!entries.length) return null
  return (
    <>
      <div className="share-bar">
        {entries.map(([spk, st]) => (
          <div key={spk}
               style={{ width: `${st.talk_share}%`, background: `var(--spk-${roleClass(roles[spk])})` }}
               title={`${names[spk]}: ${st.talk_share}%`}>
            {st.talk_share >= 12 ? `${st.talk_share}%` : ''}
          </div>
        ))}
      </div>
      <div className="legend" style={{ marginTop: 9 }}>
        {entries.map(([spk, st]) => (
          <span className="k" key={spk}>
            <span className="dot" style={{ background: `var(--spk-${roleClass(roles[spk])})` }} />
            {names[spk]} · {fmt(st.talk_time)} · {st.turns} turnos
          </span>
        ))}
      </div>
    </>
  )
}
