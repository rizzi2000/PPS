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
  'Alegria', 'Certeza', 'Reflexion', 'Neutral',
  'Confusion', 'Ansiedad', 'Tristeza', 'Enojo',
]

/** Fluidez -> nivel de alerta visual. Sólo usamos colores de estado acá. */
export function fluencyTone(label) {
  if (label === 'Bloqueo') return 'critical'
  if (label === 'Lenta' || label === 'Rapida') return 'warn'
  return null
}
