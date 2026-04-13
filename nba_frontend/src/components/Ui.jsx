// components/Ui.jsx — Shared UI primitives
import React from 'react'

export function Card({ children, style }) {
  return <div className="card" style={style}>{children}</div>
}

export function SectionTitle({ children }) {
  return <div className="section-title">{children}</div>
}

export function StatBox({ label, value, sub, color }) {
  return (
    <div className="stat-box">
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={color ? { color } : {}}>
        {value ?? '—'}
      </div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export function Tag({ children, variant = 'orange' }) {
  return <span className={`tag tag-${variant}`}>{children}</span>
}

export function Pill({ children }) {
  return <span className="formula-pill">{children}</span>
}

export function EmptyState({ icon, title, sub }) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">{icon}</div>
      <div className="empty-state-title">{title}</div>
      {sub && <div className="empty-state-sub">{sub}</div>}
    </div>
  )
}

export function Spinner() {
  return <span style={{ opacity: 0.5 }}>⟳</span>
}

export function LiveDot({ active }) {
  return (
    <span style={{
      display:    'inline-block',
      width:       8, height: 8,
      borderRadius:'50%',
      background:  active ? 'var(--green)' : 'var(--ink-4)',
      marginRight: 6,
      animation:   active ? 'pulse 1.4s ease-in-out infinite' : 'none',
    }} />
  )
}

export function AccBadge({ value }) {
  if (value == null) return <span style={{ color: 'var(--ink-4)' }}>—</span>
  const pct   = (value * 100).toFixed(2) + '%'
  const color = value >= 0.70 ? 'var(--green)'
              : value >= 0.60 ? 'var(--orange)'
              : value >= 0.55 ? 'var(--gold)'
              : 'var(--ink-3)'
  return <span style={{ color, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{pct}</span>
}

export function IntBadge({ value }) {
  if (value == null) return <span style={{ color: 'var(--ink-4)' }}>—</span>
  const pct   = (value * 100).toFixed(1) + '%'
  const color = value >= 0.60 ? 'var(--green)'
              : value >= 0.40 ? 'var(--orange)'
              : value >= 0.20 ? 'var(--gold)'
              : 'var(--ink-3)'
  return <span style={{ color, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{pct}</span>
}

// ── Draggable Slider ─────────────────────────────────────────────────────────
// Replaces native input[type=range] which doesn't drag properly in WSL/Chrome

export function Slider({ label, value, min, max, step, onChange, format }) {
  const display  = format ? format(value) : value
  const trackRef = React.useRef()

  function valueFromEvent(e) {
    const rect  = trackRef.current.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const raw   = min + ratio * (max - min)
    const steps = Math.round((raw - min) / step)
    const snapped = min + steps * step
    return +Math.max(min, Math.min(max, snapped)).toFixed(10)
  }

  function handleMouseDown(e) {
    e.preventDefault()
    onChange(valueFromEvent(e))

    const onMove = ev => { ev.preventDefault(); onChange(valueFromEvent(ev)) }
    const onUp   = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup',   onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup',   onUp)
  }

  const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))

  return (
    <div className="slider-group">
      <label>{label}</label>
      <div className="slider-value">{display}</div>
      <div
        ref={trackRef}
        onMouseDown={handleMouseDown}
        style={{
          position:   'relative',
          height:     20,
          cursor:     'pointer',
          display:    'flex',
          alignItems: 'center',
          userSelect: 'none',
          touchAction:'none',
        }}>
        {/* Track background */}
        <div style={{
          width: '100%', height: 4, borderRadius: 2,
          background: 'rgba(255,255,255,0.15)', position: 'relative',
        }}>
          {/* Filled portion */}
          <div style={{
            position: 'absolute', left: 0, top: 0, bottom: 0,
            width:    `${pct}%`, borderRadius: 2,
            background: 'var(--orange-2)',
          }} />
        </div>
        {/* Thumb */}
        <div style={{
          position:     'absolute',
          left:         `calc(${pct}% - 7px)`,
          width:        14, height: 14,
          borderRadius: '50%',
          background:   'var(--orange-2)',
          boxShadow:    '0 0 0 3px rgba(255,107,43,0.20)',
          pointerEvents:'none',  // track handles events, not thumb
        }} />
      </div>
    </div>
  )
}

export function LogBox({ lines, maxLines = 200, style }) {
  const ref = React.useRef()
  React.useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [lines])
  return (
    <div ref={ref} style={{
      background:   '#0d0d0d',
      borderRadius: 'var(--radius)',
      padding:      '12px 16px',
      fontFamily:   'var(--font-mono)',
      fontSize:      11,
      color:        '#9ca3af',
      height:        220,
      overflowY:    'auto',
      lineHeight:    1.7,
      ...style,
    }}>
      {lines.slice(-maxLines).map((l, i) => (
        <div key={i} style={{
          color: l.startsWith('[SAVE]')   ? '#7DD3A8'
               : l.startsWith('[STOP]')   ? '#f87171'
               : l.startsWith('[ACCEPT]') ? '#FB923C'
               : l.startsWith('[START]')  ? '#60a5fa'
               : l.startsWith('[ERROR]')  ? '#f87171'
               : undefined
        }}>{l}</div>
      ))}
      {lines.length === 0 && <div style={{ opacity: 0.4 }}>waiting...</div>}
    </div>
  )
}