import { useMemo } from 'react'
import { EMOTION_ORDER, levelFromZ } from './utils'

/**
 * Deriva del análisis todo lo que consumen los gráficos.
 *
 * Vive fuera de los componentes para que el panel compacto y el expandido
 * miren exactamente los mismos números: si divergieran, el usuario vería una
 * cosa en la barra lateral y otra al agrandar.
 */
export function useMetricsData(segments, stats, roles, speaker) {
  return useMemo(() => {
    const keys = Object.keys(roles || {})
    // Por defecto analizamos al paciente, que es el foco clínico.
    const target = speaker || keys.find((k) => roles[k] === 'Paciente') || keys[0]
    const targetRole = roles?.[target]

    const mine = segments.filter((s) => s.speaker === target && s.metrics)
    const legacy = mine.length > 0 && mine[0].metrics.speed_z === undefined

    const data = mine.map((s) => ({
      t: (s.start + s.end) / 2,
      start: s.start,
      end: s.end,
      // Compatibilidad: las sesiones analizadas antes del cambio de nombres
      // traen fluency_z / arousal_z. Se leen igual para que los graficos no
      // queden vacios, pero la sesion se marca como `legacy` porque la
      // formula vieja mezclaba velocidad con pausas y no es equivalente.
      velocidad: s.metrics.speed_z ?? s.metrics.fluency_z,
      intensidad: s.metrics.intensity_z ?? s.metrics.arousal_z,
      velLabel: s.metrics.speed_label
        ?? levelFromZ(s.metrics.fluency_z, ['Lento', 'Normal', 'Rapido']),
      intLabel: s.metrics.intensity_label
        ?? levelFromZ(s.metrics.arousal_z, ['Baja', 'Normal', 'Alta']),
      rate: s.metrics.articulation_rate,
      // `silence` cubre tanto el hueco entre palabras como el silencio
      // previo al turno; `longest_pause` solo, se quedaba corto.
      pausa: s.metrics.silence ?? s.metrics.longest_pause,
      pauseRatio: s.metrics.pause_ratio,
      blocked: s.metrics.blocked ?? (s.metrics.silence ?? 0) >= 2.0,
      f0: s.metrics.f0_mean,
      label: s.metrics.speed_label,
      emocion: s.emocion,
      tema: s.tema,
      texto: s.text,
    }))

    // Bloqueos: las pausas largas son el evento que más interesa localizar.
    const blocks = data.filter((d) => d.blocked || d.pausa >= 2.0)

    // Huecos donde hay audio pero no hay transcripcion: el ASR perdio habla.
    // Es indicador de calidad, no clinico, y aplica a toda la sesion.
    const gaps = segments
      .filter((s) => (s.metrics?.gap_unvoiced || 0) >= 1.5)
      .map((s) => ({ start: s.start, dur: s.metrics.gap_unvoiced, texto: s.text }))
      .sort((a, b) => b.dur - a.dur)

    const counts = new Map()
    mine.forEach((s) => s.emocion && counts.set(s.emocion, (counts.get(s.emocion) || 0) + 1))
    const emotions = EMOTION_ORDER
      .filter((e) => counts.has(e))
      .map((e) => ({ emocion: e, n: counts.get(e) }))

    // Como habla mayormente esta persona, en una palabra.
    const tally = { Lento: 0, Normal: 0, Rapido: 0 }
    data.forEach((d) => { if (d.velLabel in tally) tally[d.velLabel] += 1 })
    const speedSummary = Object.entries(tally)
      .sort((a, b) => b[1] - a[1])[0]?.[0] || '—'

    // Extremos: los momentos que vale la pena escuchar primero.
    const sorted = [...data].sort((a, b) => a.velocidad - b.velocidad)
    const extremes = {
      lento: sorted[0],
      rapido: sorted[sorted.length - 1],
      pausaMax: data.reduce((m, d) => (!m || d.pausa > m.pausa ? d : m), null),
    }

    return {
      target,
      targetRole,
      targetStats: stats?.[target] || null,
      speakers: keys,
      data,
      blocks,
      gaps,
      emotions,
      extremes,
      speedSummary,
      hasData: data.length > 1,
      legacy,
    }
  }, [segments, stats, roles, speaker])
}
