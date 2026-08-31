/** Formatea segundos como H:MM:SS o M:SS. Soporta sesiones de más de 1 hora
 *  (el `toISOString().substr(14,5)` de la versión anterior se rompía a los 60 min). */
export function fmtTime(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`
}

export const roleClass = (role) => {
  const r = (role || '').toLowerCase()
  if (r.startsWith('terapeuta')) return 'therapist'
  if (r.startsWith('paciente')) return 'patient'
  return 'other'
}

/** Índice del segmento activo por búsqueda binaria: O(log n) en cada tick del
 *  audio, en vez de recorrer toda la lista 60 veces por segundo. */
export function findActiveIndex(segments, t) {
  let lo = 0, hi = segments.length - 1, best = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (segments[mid].start <= t) { best = mid; lo = mid + 1 }
    else hi = mid - 1
  }
  if (best >= 0 && t <= segments[best].end + 0.25) return best
  return -1
}

export const EMOTION_ORDER = [
  'Alegria', 'Neutral', 'Confusion', 'Frustracion', 'Tristeza', 'Enojo',
]

/** Etiqueta de estado -> color. Solo se usan colores de estado aca. */
export function levelTone(label) {
  if (label === 'Bloqueo') return 'critical'
  if (['Lento', 'Rapido', 'Alta', 'Baja'].includes(label)) return 'warn'
  return null
}

/** Configuracion de cada serie graficada.
 *  Vive aca y no en charts.jsx porque un archivo de componentes que
 *  exporta constantes rompe el fast refresh de React.
 *
 *  Los ejes se rotulan con palabras, no con el z-score: el numero es el que
 *  se mide, pero "Lento / Normal / Rapido" es lo que se lee de un vistazo. */
export const SERIES = {
  velocidad: {
    key: 'velocidad', label: 'Velocidad',
    domain: [-2.6, 2.6], ticks: [-1.6, 0, 1.6],
    tickNames: { '-1.6': 'Lento', 0: 'Normal', '1.6': 'Rapido' },
    fmt: (v, d) => (d?.velLabel ?? (v == null ? '—' : v.toFixed(2))),
  },
  intensidad: {
    key: 'intensidad', label: 'Intensidad de la voz',
    domain: [-2.6, 2.6], ticks: [-1.6, 0, 1.6],
    tickNames: { '-1.6': 'Baja', 0: 'Normal', '1.6': 'Alta' },
    fmt: (v, d) => (d?.intLabel ?? (v == null ? '—' : v.toFixed(2))),
  },
  rate: {
    key: 'rate', label: 'Silabas por segundo',
    domain: [0, 'dataMax'], ticks: undefined,
    fmt: (v) => (v == null ? '—' : `${v} sil/s`),
  },
}
