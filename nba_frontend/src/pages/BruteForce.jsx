// pages/BruteForce.jsx — Exhaustive formula enumeration
import { useState, useEffect, useRef } from 'react'
import { apiGet, apiPost } from '../hooks/useApi'
import { useSSE } from '../hooks/useSSE'
import { Card, SectionTitle, StatBox, EmptyState, AccBadge, IntBadge, LiveDot, Tag } from '../components/Ui'

const SIZE_TOTALS = {
  1:           1618,
  2:           9708,
  3:       18383716,
  4:      330207912,
  5:  419068899152,
}

const SIZE_LABELS = {
  1: '1 node (leaves)',
  2: '2 nodes (unary)',
  3: '3 nodes (binary pairs)',
  4: '4 nodes (leaf × size-2)',
  5: '5 nodes (size-2 × size-2)',
}

const DEFAULT_CFG = {
  min_interest:    0.20,
  start_fraction:  0.5,
  block_size:      100,
  min_size:        1,
  max_size:        3,
}

function fmt(n) {
  if (n === undefined || n === null) return '—'
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return n.toLocaleString()
}

function ProgressBar({ value, total, color = 'var(--orange)' }) {
  const pct = total > 0 ? Math.min(100, (value / total) * 100) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ flex: 1, background: 'var(--bg-subtle)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color,
          borderRadius: 4, transition: 'width 0.3s' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)', minWidth: 42 }}>
        {pct.toFixed(1)}%
      </span>
    </div>
  )
}

export default function BruteForce() {
  const [cfg,     setCfg]     = useState(DEFAULT_CFG)
  const [running, setRunning] = useState(false)
  const [stats,   setStats]   = useState(null)
  const [results, setResults] = useState([])
  const [error,   setError]   = useState(null)

  const { data: sseData } = useSSE('/api/brute/stream', true)

  useEffect(() => {
    if (!sseData || sseData.type !== 'brute_force') return
    setStats(sseData)
    setRunning(sseData.is_running)
  }, [sseData])

  useEffect(() => {
    // Load existing results on mount
    apiGet('/api/brute/summary').then(d => {
      if (d?.stats) { setStats(d.stats); setRunning(d.stats.is_running) }
    }).catch(() => {})
    loadResults()
  }, [])

  async function loadResults() {
    try {
      // Load top formulas from summary (sorted by accuracy, maintained by engine)
      const summary = await apiGet('/api/brute/summary')
      if (summary?.top_formulas?.length > 0) {
        setResults(summary.top_formulas)
      }
    } catch {}
  }

  async function handleStart() {
    setError(null)
    const interest = cfg.min_interest
    try {
      await apiPost('/api/brute/start', {
        min_interest:    interest,
        start_fraction:  cfg.start_fraction,
        block_size:      cfg.block_size,
        min_size:        cfg.min_size,
        max_size:        cfg.max_size,
      })
      setRunning(true)
      setResults([])
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleStop() {
    try {
      await apiPost('/api/brute/stop')
      setRunning(false)
      setTimeout(loadResults, 1000)
    } catch {}
  }

  function set(k) { return v => setCfg(c => ({ ...c, [k]: v })) }

  // Estimate time remaining
  const totalForSizes = Array.from(
    {length: cfg.max_size - cfg.min_size + 1},
    (_, i) => SIZE_TOTALS[cfg.min_size + i] || 0
  ).reduce((a, b) => a + b, 0)

  const testedPct = stats && totalForSizes > 0
    ? Math.min(100, (stats.n_tested / totalForSizes) * 100)
    : 0

  const etaSeconds = stats?.formulas_per_s > 0 && testedPct < 100
    ? (totalForSizes - stats.n_tested) / stats.formulas_per_s
    : null

  function fmtEta(s) {
    if (!s) return '—'
    if (s < 60) return `${Math.round(s)}s`
    if (s < 3600) return `${Math.floor(s/60)}m ${Math.round(s%60)}s`
    return `${Math.floor(s/3600)}h ${Math.floor((s%3600)/60)}m`
  }

  return (
    <div style={{ padding: 32, display: 'grid', gridTemplateColumns: '320px 1fr', gap: 20, alignItems: 'start' }}>

      {/* ── LEFT: Config ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="train-panel">
          <SectionTitle style={{ color: 'rgba(255,255,255,0.4)' }}>Brute Force Config</SectionTitle>

          {/* Size range */}
          <div style={{ marginTop: 20 }}>
            <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: 10, fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
              Formula size range
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              {[['From', 'min_size'], ['To', 'max_size']].map(([label, key]) => (
                <div key={key}>
                  <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 10,
                    fontFamily: 'var(--font-mono)', textTransform: 'uppercase',
                    letterSpacing: '0.06em', marginBottom: 6 }}>{label}</div>
                  <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700,
                    fontSize: 28, color: 'var(--orange-2)', marginBottom: 4 }}>
                    {cfg[key]}
                  </div>
                  <input type="range" min={1} max={5} step={1}
                    value={cfg[key]}
                    onChange={e => set(key)(Math.min(5, Math.max(1, +e.target.value)))} />
                </div>
              ))}
            </div>
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 3 }}>
              {Array.from({length: cfg.max_size - cfg.min_size + 1}, (_, i) => {
                const s = cfg.min_size + i
                const n = SIZE_TOTALS[s]
                return (
                  <div key={s} style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 11, fontFamily: 'var(--font-mono)' }}>
                    <span style={{ color: 'rgba(255,255,255,0.4)' }}>Size {s}</span>
                    <span style={{ color: 'var(--orange-2)' }}>{fmt(n)} formulas</span>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Interest threshold */}
          <div style={{ marginTop: 20 }}>
            <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: 10, fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
              Min interest threshold
            </div>
            <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700,
              fontSize: 24, color: 'var(--orange-2)', marginBottom: 4 }}>
              {(50 + cfg.min_interest * 50).toFixed(1)}% accuracy
            </div>
            <input type="range" min={0.10} max={0.50} step={0.01}
              value={cfg.min_interest}
              onChange={e => set('min_interest')(+e.target.value)} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9,
              fontFamily: 'var(--font-mono)', color: 'rgba(255,255,255,0.25)', marginTop: 4 }}>
              <span>55%</span><span>60%</span><span>65%</span><span>70%</span><span>75%</span>
            </div>
          </div>

          {/* Ramp + block */}
          <div style={{ marginTop: 20 }}>
            <div style={{ color: 'rgba(255,255,255,0.35)', fontSize: 10, fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
              Filter settings
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 10, fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Ramp start</div>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 22,
                  color: 'var(--orange-2)', marginBottom: 4 }}>
                  {Math.round(cfg.start_fraction * 100)}%
                </div>
                <input type="range" min={0.1} max={1.0} step={0.1}
                  value={cfg.start_fraction}
                  onChange={e => set('start_fraction')(+e.target.value)} />
              </div>
              <div>
                <div style={{ color: 'rgba(255,255,255,0.4)', fontSize: 10, fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Block size</div>
                <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 22,
                  color: 'var(--orange-2)', marginBottom: 4 }}>{cfg.block_size}</div>
                <input type="range" min={50} max={500} step={50}
                  value={cfg.block_size}
                  onChange={e => set('block_size')(+e.target.value)} />
              </div>
            </div>
          </div>

          {error && (
            <div style={{ marginTop: 12, background: 'rgba(192,57,43,0.2)', color: '#f87171',
              padding: '8px 12px', borderRadius: 'var(--radius)', fontSize: 12 }}>
              {error}
            </div>
          )}

          <div style={{ marginTop: 20 }}>
            {!running
              ? <button className="btn btn-primary" style={{ width: '100%', padding: 12 }}
                  onClick={handleStart}>▶ Start Brute Force</button>
              : <button className="btn btn-danger" style={{ width: '100%', padding: 12 }}
                  onClick={handleStop}>■ Stop</button>
            }
          </div>
        </div>

        {/* Constant info */}
        <Card>
          <SectionTitle>Constant scheme</SectionTitle>
          <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
            {[
              ['0.010 → 0.099', 'step 0.001', 90],
              ['0.100 → 0.990', 'step 0.010', 90],
              ['1.000 → 9.900', 'step 0.100', 90],
              ['10.00 → 99.00', 'step 1.000', 90],
              ['100.0 → 1000.',  'step 10.00', 91],
            ].map(([range, step, n]) => (
              <div key={range} style={{ display: 'flex', justifyContent: 'space-between',
                fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--ink-3)' }}>
                <span>{range}</span>
                <span style={{ color: 'var(--ink-4)' }}>{step} × {n}</span>
              </div>
            ))}
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--ink-4)',
              fontFamily: 'var(--font-mono)', borderTop: '1px solid var(--border)', paddingTop: 6 }}>
              451 pos + 451 neg = 902 constants<br/>
              + 716 variables = <strong style={{ color: 'var(--ink-2)' }}>1 618 leaves</strong>
            </div>
          </div>
        </Card>
      </div>

      {/* ── RIGHT: Stats + Results ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h2 style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 24 }}>
            Brute Force
          </h2>
          <LiveDot active={running} />
          {running && <Tag variant="green">RUNNING</Tag>}
          {stats && !running && stats.n_saved > 0 && <Tag variant="blue">DONE — {stats.n_saved} saved</Tag>}
        </div>

        {/* Live stats */}
        {stats && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
              <StatBox label="Current size"
                value={<span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 28, color: 'var(--orange)' }}>
                  {stats.current_size || '—'}
                </span>} />
              <StatBox label="Tested" value={fmt(stats.n_tested)} />
              <StatBox label="Saved" value={stats.n_saved}
                sub={stats.n_tested > 0 ? `${((stats.n_saved/stats.n_tested)*100).toFixed(2)}% rate` : ''} />
              <StatBox label="Speed" value={`${fmt(Math.round(stats.formulas_per_s))}/s`} />
              <StatBox label="ETA" value={fmtEta(etaSeconds)} />
            </div>

            {/* Current size progress */}
            {stats.current_size > 0 && (
              <Card>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <SectionTitle>
                    Progress — Size {stats.current_size} ({SIZE_LABELS[stats.current_size]})
                  </SectionTitle>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                    {fmt(stats.current_idx)} / {fmt(stats.current_size_total)}
                  </span>
                </div>
                <ProgressBar
                  value={stats.current_idx}
                  total={stats.current_size_total}
                  color={running ? 'var(--orange)' : 'var(--green)'}
                />

                {/* Breakdown */}
                <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                  <StatBox label="Invalid / const" value={fmt(stats.n_invalid)} />
                  <StatBox label="Filtered" value={fmt(stats.n_filtered)} />
                  <StatBox label="Best acc" value={<AccBadge value={stats.best_accuracy > 0.5 ? stats.best_accuracy : null} />} />
                </div>

                {/* Best formula so far */}
                {stats.best_formula_repr && stats.best_accuracy > 0.5 && (
                  <div style={{ marginTop: 10, background: 'var(--orange-dim)', borderRadius: 'var(--radius)',
                    padding: '8px 12px' }}>
                    <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--orange)',
                      textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4 }}>
                      Current best
                    </div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, wordBreak: 'break-all' }}>
                      {stats.best_formula_repr}
                    </div>
                  </div>
                )}
              </Card>
            )}
          </>
        )}

        {/* Results */}
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <SectionTitle>Survivors found</SectionTitle>
            <button className="btn" style={{ fontSize: 11 }} onClick={loadResults}>↻ Refresh</button>
          </div>

          {results.length === 0 ? (
            <EmptyState icon="◈"
              title={running ? "Running — survivors will appear here" : "No results yet"}
              sub={running ? "" : "Start brute force to enumerate formulas."} />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {results
                .sort((a, b) => (b.score?.accuracy ?? 0) - (a.score?.accuracy ?? 0))
                .map(rec => (
                  <div key={rec.id} style={{
                    background: 'var(--bg-subtle)', borderRadius: 'var(--radius)',
                    padding: '8px 14px',
                    display: 'grid', gridTemplateColumns: '1fr auto auto auto auto',
                    gap: 10, alignItems: 'center',
                  }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {rec.repr}
                    </div>
                    <Tag variant="blue">size {rec.score?.size ?? rec.tree_size}</Tag>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 9, color: 'var(--ink-4)', marginBottom: 2 }}>INT</div>
                      <IntBadge value={rec.score?.interest} />
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 9, color: 'var(--ink-4)', marginBottom: 2 }}>ACC</div>
                      <AccBadge value={rec.score?.accuracy} />
                    </div>
                    <Tag variant={rec.score?.direction === 1 ? 'green' : 'orange'}>
                      {rec.score?.direction === 1 ? 'GOOD' : 'BAD'}
                    </Tag>
                  </div>
                ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}