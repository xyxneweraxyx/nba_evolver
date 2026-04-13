// hooks/useSSE.js — Server-Sent Events hook
import { useEffect, useRef, useState } from 'react'
import { API_BASE } from './useApi'

/**
 * useSSE(path, enabled)
 * Opens an SSE connection to API_BASE + path when enabled=true.
 * Returns { data, connected, error }
 * data = latest non-ping JSON event from server
 */
export function useSSE(path, enabled = true) {
  const [data,      setData]      = useState(null)
  const [connected, setConnected] = useState(false)
  const [error,     setError]     = useState(null)
  const esRef = useRef(null)

  useEffect(() => {
    if (!enabled) {
      if (esRef.current) { esRef.current.close(); esRef.current = null }
      setConnected(false)
      return
    }

    const es = new EventSource(`${API_BASE}${path}`)
    esRef.current = es

    es.onopen = () => { setConnected(true); setError(null) }

    es.onmessage = e => {
      try {
        const d = JSON.parse(e.data)
        if (d.type === 'ping') return      // ignore keepalives
        if (d.type === 'connected') { setConnected(true); return }
        setData(d)
      } catch { /* ignore parse errors */ }
    }

    es.onerror = () => {
      setConnected(false)
      setError('Connection lost — retrying...')
    }

    return () => { es.close(); esRef.current = null; setConnected(false) }
  }, [path, enabled])

  return { data, connected, error }
}
