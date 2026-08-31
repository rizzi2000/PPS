import { useEffect, useState } from 'react'
import { Minimize2, Table2, LineChart, Play, AlertTriangle, X } from 'lucide-react'
import { EmotionBars, ShareBar, Tile, Trend } from './charts'
import { useMetricsData } from '../useMetricsData'
import { fmtTime, roleClass, SERIES } from '../utils'

/**
 * Vista ampliada de métricas.
 *
 * El panel de la barra lateral sirve para mirar de reojo; acá es donde se
 * analiza: los gráficos ocupan el ancho real, comparten cursor temporal, se
 * pueden acotar a un tramo con el selector inferior, y cada punto es
 * navegable hacia ese momento del audio.
 */
export default function MetricsLab({
  segments, stats, roles, names, duration, currentTime, onSeek, onClose,
}) {
  const [speaker, setSpeaker] = useState(null)
  const [view, setView] = useState('graficos')
  const m = useMetricsData(segments, stats, roles, speaker)

  // Escape cierra; mientras está abierto el fondo no debe scrollear.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [onClose])

  const st = m.targetStats

  return (
    <div className="lab-overlay" role="dialog" aria-modal="true" aria-label="Análisis de métricas">
      <div className="lab">
        <header className="lab-head">
          <div>
            <h2>Análisis de métricas</h2>
            <p>Medidas sobre la señal de audio · normalizadas contra la línea de base de cada hablante</p>
          </div>

          <div className="spacer" />

          {m.speakers.length > 1 && (
            <div className="seg" role="group" aria-label="Hablante analizado">
              {m.speakers.map((k) => (
                <button key={k} aria-pressed={m.target === k} onClick={() => setSpeaker(k)}>
                  <span className="dot" style={{ background: `var(--spk-${roleClass(roles[k])})`,
                    display: 'inline-block', marginRight: 6, verticalAlign: -1 }} />
                  {names[k]}
                </button>
              ))}
            </div>
          )}

          <div className="seg" role="group" aria-label="Vista">
            <button aria-pressed={view === 'graficos'} onClick={() => setView('graficos')}>
              <LineChart size={13} style={{ verticalAlign: -2, marginRight: 5 }} />Gráficos
            </button>
            <button aria-pressed={view === 'tabla'} onClick={() => setView('tabla')}>
              <Table2 size={13} style={{ verticalAlign: -2, marginRight: 5 }} />Datos
            </button>
          </div>

          <button className="btn ghost icon" onClick={onClose} aria-label="Cerrar (Esc)">
            <Minimize2 size={17} />
          </button>
        </header>

        <div className="lab-body">
          {!m.hasData && (
            <p className="empty">No hay suficientes datos de este hablante para analizar.</p>
          )}

          {m.legacy && (
            <p className="legacy-note" style={{ gridColumn: '1 / -1' }}>
              Esta sesión se analizó antes de separar velocidad e intensidad.
              Los valores se leen del formato anterior, donde la velocidad venía
              mezclada con las pausas, así que son aproximados. Reprocesá el
              audio para obtener las métricas actuales.
            </p>
          )}

          {m.hasData && st && (
            <div className="tiles lab-tiles">
              <Tile label="Tiempo de habla" value={fmtTime(st.talk_time)} hint={`${st.talk_share}% de la sesión`} />
              <Tile label="Ritmo medio" value={st.avg_rate} unit="síl/s"
                    hint={st.avg_rate < 5 ? 'por debajo de lo típico'
                        : st.avg_rate > 7 ? 'por encima de lo típico' : 'dentro de lo típico (5–7)'} />
              <Tile label="Tono medio" value={st.f0_median || '—'} unit={st.f0_median ? 'Hz' : ''} />
              <Tile label="Pausa en el turno" value={Math.round(st.avg_pause_ratio * 100)} unit="%"
                    hint="proporción de silencio" />
              <Tile label="Turnos" value={st.turns} hint={`${st.words} palabras`} />
              <Tile label="Bloqueos" value={m.blocks.length} tone={m.blocks.length ? 'alert' : null}
                    hint="silencios ≥ 2 s" />
            </div>
          )}

          {m.hasData && view === 'graficos' && (
            <>
              <div className="lab-charts">
                <section className="lab-chart">
                  <header>
                    <h3>Velocidad del habla</h3>
                    <p>Comparada con la forma habitual de hablar de esta persona en la sesión</p>
                  </header>
                  <Trend data={m.data} series={SERIES.velocidad} duration={duration}
                         currentTime={currentTime} onSeek={onSeek} height={190}
                         band={[-0.8, 0.8, 'lo habitual en esta persona']} zero blocks={m.blocks} />
                </section>

                <section className="lab-chart">
                  <header>
                    <h3>Intensidad de la voz</h3>
                    <p>Cuánto sube el volumen y el tono. Indica activación, no una emoción concreta</p>
                  </header>
                  <Trend data={m.data} series={SERIES.intensidad} duration={duration}
                         currentTime={currentTime} onSeek={onSeek} height={190}
                         band={[-0.8, 0.8, 'lo habitual en esta persona']} zero />
                </section>

                <section className="lab-chart">
                  <header>
                    <h3>Sílabas por segundo</h3>
                    <p>El valor absoluto, sin comparar. Arrastrá la barra de abajo para acotar el tramo</p>
                  </header>
                  <Trend data={m.data} series={SERIES.rate} duration={duration}
                         currentTime={currentTime} onSeek={onSeek} height={210}
                         band={[5, 7, 'típico en español rioplatense']} brush />
                </section>
              </div>

              <div className="lab-side">
                {m.blocks.length > 0 && (
                  <section className="lab-block">
                    <h3><AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 6,
                         color: 'var(--critical)' }} />Bloqueos detectados</h3>
                    <p className="muted">Silencios de 2 s o más sin que cambie el hablante.</p>
                    <ul className="jump-list">
                      {m.blocks.slice(0, 8).map((b) => (
                        <li key={b.start}>
                          <button onClick={() => onSeek(b.start)}>
                            <Play size={11} fill="currentColor" />
                            <span className="ts">{fmtTime(b.start)}</span>
                            <span className="dur">{b.pausa}s</span>
                            <span className="txt">{b.texto?.slice(0, 44)}…</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                {m.gaps.length > 0 && (
                  <section className="lab-block">
                    <h3><AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 6,
                         color: 'var(--warning)' }} />Transcripción incompleta</h3>
                    <p className="muted">
                      Tramos con audio audible que el reconocedor no transcribió.
                      Las métricas de esos momentos no existen.
                    </p>
                    <ul className="jump-list">
                      {m.gaps.slice(0, 6).map((g) => (
                        <li key={g.start}>
                          <button onClick={() => onSeek(Math.max(0, g.start - g.dur))}>
                            <Play size={11} fill="currentColor" />
                            <span className="ts">{fmtTime(Math.max(0, g.start - g.dur))}</span>
                            <span className="dur">{g.dur}s sin texto</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <section className="lab-block">
                  <h3>Momentos destacados</h3>
                  <p className="muted">Lo más lento y lo más rápido de la sesión.</p>
                  <ul className="jump-list">
                    {[
                      ['Más lento', m.extremes.lento],
                      ['Más rápido', m.extremes.rapido],
                      ['Pausa más larga', m.extremes.pausaMax],
                    ].filter(([, d]) => d).map(([label, d]) => (
                      <li key={label}>
                        <button onClick={() => onSeek(d.start)}>
                          <Play size={11} fill="currentColor" />
                          <span className="ts">{fmtTime(d.start)}</span>
                          <span className="dur">{label}</span>
                          <span className="txt">{d.texto?.slice(0, 40)}…</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>

                {m.emotions.length > 0 && (
                  <section className="lab-block">
                    <h3>Emociones</h3>
                    <p className="muted">Clasificadas sobre el texto, no sobre la voz.</p>
                    <EmotionBars emotions={m.emotions} />
                  </section>
                )}

                <section className="lab-block">
                  <h3>Reparto del habla</h3>
                  <ShareBar stats={stats} roles={roles} names={names}
                            roleClass={roleClass} fmt={fmtTime} />
                </section>
              </div>
            </>
          )}

          {m.hasData && view === 'tabla' && (
            <div className="lab-table">
              <div className="tablewrap">
                <table>
                  <thead>
                    <tr>
                      <th>Inicio</th><th>Velocidad</th><th>Intensidad</th>
                      <th className="num">Ritmo</th><th className="num">Silencio</th>
                      <th className="num">Tono</th><th>Estado</th><th>Emoción</th><th>Texto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.data.map((d) => (
                      <tr key={d.start} onClick={() => onSeek(d.start)} className="clickable">
                        <td className="num">{fmtTime(d.start)}</td>
                        <td>{d.velLabel}</td>
                        <td>{d.intLabel}</td>
                        <td className="num">{d.rate}</td>
                        <td className="num">{d.pausa || '—'}</td>
                        <td className="num">{d.f0 || '—'}</td>
                        <td>{d.label !== 'Normal'
                          ? <span className={`chip ${d.label === 'Bloqueo' ? 'critical' : 'warn'}`}>{d.label}</span>
                          : <span className="muted">Normal</span>}</td>
                        <td>{d.emocion}</td>
                        <td className="txt-cell">{d.texto}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                Clic en cualquier fila para ir a ese momento del audio.
              </p>
            </div>
          )}
        </div>
      </div>

      <button className="lab-backdrop" onClick={onClose} aria-label="Cerrar análisis">
        <X size={18} />
      </button>
    </div>
  )
}
