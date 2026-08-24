import { Stethoscope, ShieldAlert, Lightbulb, Dot, ListChecks } from 'lucide-react'

const RISK_ICON = { alto: ShieldAlert, medio: ShieldAlert, bajo: ShieldAlert }

export default function Summary({ summary, loading }) {
  if (!summary) {
    return (
      <div className="card">
        <div className="card-head"><Stethoscope size={16} /><h2>Resumen clínico</h2></div>
        <p className="empty">
          {loading ? 'El resumen se genera al final del análisis...' : 'Todavía no hay resumen.'}
        </p>
      </div>
    )
  }

  const riesgo = (summary.riesgo || 'na').toLowerCase()
  const key = ['bajo', 'medio', 'alto'].includes(riesgo) ? riesgo : 'na'
  const Icon = RISK_ICON[key] || ShieldAlert

  return (
    <div className="card">
      <div className="card-head">
        <Stethoscope size={16} />
        <h2>Resumen clínico</h2>
        <div className="spacer" />
        {/* El color de estado nunca va solo: siempre con ícono y etiqueta. */}
        <span className={`risk ${key}`}>
          <Icon size={13} />
          Riesgo {summary.riesgo}
        </span>
      </div>

      <div className="card-body">
        {summary.justificacion_riesgo && (
          <p className="prose" style={{ marginBottom: 14, color: 'var(--ink)' }}>
            {summary.justificacion_riesgo}
          </p>
        )}

        <p className="prose">{summary.resumen}</p>

        {summary.temas?.length > 0 && (
          <div className="section">
            <p className="section-label">Temas centrales</p>
            <div className="chips">
              {summary.temas.map((t, i) => <span className="chip" key={i}>{t}</span>)}
            </div>
          </div>
        )}

        {summary.indicadores?.length > 0 && (
          <div className="section">
            <p className="section-label"><ListChecks size={11} style={{ verticalAlign: -1, marginRight: 5 }} />
              Indicadores observados</p>
            <ul className="list">
              {summary.indicadores.map((t, i) => (
                <li key={i}><Dot size={16} /><span>{t}</span></li>
              ))}
            </ul>
          </div>
        )}

        {summary.sugerencias?.length > 0 && (
          <div className="section">
            <p className="section-label"><Lightbulb size={11} style={{ verticalAlign: -1, marginRight: 5 }} />
              Posibles líneas de trabajo</p>
            <ul className="list">
              {summary.sugerencias.map((t, i) => (
                <li key={i}><Dot size={16} /><span>{t}</span></li>
              ))}
            </ul>
          </div>
        )}

        <p style={{ fontSize: 11, color: 'var(--ink-muted)', marginTop: 20, marginBottom: 0 }}>
          Generado automáticamente. Material de apoyo: no reemplaza el juicio clínico profesional.
        </p>
      </div>
    </div>
  )
}
