// hooks/useApi.js — API helpers + SSE hook

const API = 'http://localhost:8080'

// ── fetch helpers ──────────────────────────────────────────────────────────

export async function apiFetch(path, opts = {}) {
  const r = await fetch(`${API}${path}`, opts)
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json()
}

export async function apiGet(path) {
  return apiFetch(path)
}

export async function apiPost(path, body = {}) {
  return apiFetch(path, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
}

export const API_BASE = API
