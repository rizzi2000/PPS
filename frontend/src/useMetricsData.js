import { useMemo } from 'react'
import { EMOTION_ORDER } from './utils'

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

    const data = mine.map((s) => ({
      t: (s.start + s.end) / 2,
      start: s.start,
      end: s.end,
      fluidez: s.metrics.fluency_z,
      activacion: s.metrics.arousal_z,
      rate: s.metrics.articulation_rate,
      // `silence` cubre tanto el hueco entre palabras como el silencio
      // previo al turno; `longest_pause` solo, se quedaba corto.
      pausa: s.metrics.silence ?? s.metrics.longest_pause,
      pauseRatio: s.metrics.pause_ratio,
      f0: s.metrics.f0_mean,
      label: s.metrics.fluency_label,
      emocion: s.emocion,
      tema: s.tema,
      texto: s.text,
    }))

    // Bloqueos: las pausas largas son el evento que más interesa localizar.
    const blocks = data.filter((d) => d.label === 'Bloqueo' || d.pausa >= 2.0)

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

    // Extremos: los momentos que vale la pena escuchar primero.
    const sorted = [...data].sort((a, b) => a.fluidez - b.fluidez)
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
      hasData: data.length > 1,
    }
  }, [segments, stats, roles, speaker])
}
