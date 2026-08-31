import { Waves, Maximize2, AlertTriangle } from 'lucide-react'
import { EmotionBars, ShareBar, Tile, Trend } from './charts'
import { useMetricsData } from '../useMetricsData'
import { fmtTime, roleClass, SERIES } from '../utils'

/**
 * Panel compacto de la barra lateral.
 *
 * Es un vistazo, no un espacio de análisis: muestra los titulares y ofrece
 * abrir la vista ampliada, donde los gráficos tienen ancho real. Ambos leen
 * los mismos datos derivados, así que nunca se contradicen.
 */
export default function Metrics({
  segments, stats, roles, names, duration, currentTime, onSeek, onExpand,
}) {
  const m = useMetricsData(segments, stats, roles, null)
  const st = m.targetStats

  return (
    <div className="card">
      <div className="card-head">
        <Waves size={16} />
        <h2>Métricas{m.targetRole ? ` · ${m.targetRole}` : ''}</h2>
        <div className="spacer" />
        {m.hasData && (
          <button className="btn expand-btn" onClick={onExpand}>
            <Maximize2 size={14} /> Analizar
          </button>
        )}
      </div>

      <div className="card-body">
        {!m.hasData && (
          <p className="empty">Las métricas aparecen cuando termina el análisis prosódico.</p>
        )}

        {m.hasData && (
          <>
            {st && (
              <div className="tiles" style={{ marginBottom: 16 }}>
                <Tile label="Habla" value={st.talk_share} unit="%" />
                <Tile label="Ritmo" value={st.avg_rate} unit="síl/s" />
                <Tile label="Tono" value={st.f0_median || '—'} unit={st.f0_median ? 'Hz' : ''} />
                <Tile label="Bloqueos" value={m.blocks.length}
                      tone={m.blocks.length ? 'alert' : null} />
              </div>
            )}

            {m.blocks.length > 0 && (
              <button className="alert-strip" onClick={onExpand}>
                <AlertTriangle size={14} />
                {m.blocks.length === 1
                  ? '1 bloqueo detectado'
                  : `${m.blocks.length} bloqueos detectados`}
                <span className="muted">· ver dónde</span>
              </button>
            )}

            <div className="section">
              <p className="section-label">Fluidez</p>
              <Trend data={m.data} series={SERIES.fluidez} duration={duration}
                     currentTime={currentTime} onSeek={onSeek} height={104}
                     band={[-0.75, 0.75]} zero blocks={m.blocks} />
            </div>

            <div className="section">
              <p className="section-label">Activación</p>
              <Trend data={m.data} series={SERIES.activacion} duration={duration}
                     currentTime={currentTime} onSeek={onSeek} height={104}
                     band={[-0.75, 0.75]} zero />
            </div>

            {m.emotions.length > 0 && (
              <div className="section">
                <p className="section-label">Emociones</p>
                <EmotionBars emotions={m.emotions} />
              </div>
            )}
          </>
        )}

        {stats && Object.keys(stats).length > 0 && (
          <div className="section">
            <p className="section-label">Reparto del habla</p>
            <ShareBar stats={stats} roles={roles} names={names}
                      roleClass={roleClass} fmt={fmtTime} />
          </div>
        )}
      </div>
    </div>
  )
}
