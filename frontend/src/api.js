export const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api'

export const audioUrl = (jobId) => `${API}/sessions/${jobId}/audio`

export async function uploadSession(file, { speakers, onProgress } = {}) {
  const form = new FormData()
  form.append('file', file)

  // XHR en vez de fetch: necesitamos el progreso real de subida.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const qs = speakers ? `?speakers=${speakers}` : ''
    xhr.open('POST', `${API}/sessions${qs}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      let body
      try { body = JSON.parse(xhr.responseText) } catch { body = {} }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body)
      else reject(new Error(body.detail || `Error ${xhr.status}`))
    }
    xhr.onerror = () => reject(new Error('No se pudo conectar con el servidor.'))
    xhr.send(form)
  })
}

export async function listSessions() {
  const r = await fetch(`${API}/sessions`)
  if (!r.ok) throw new Error('No se pudieron listar las sesiones')
  return r.json()
}

export async function getSession(jobId) {
  const r = await fetch(`${API}/sessions/${jobId}`)
  if (!r.ok) throw new Error('Sesión no encontrada')
  return r.json()
}

export function exportJSON(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}
