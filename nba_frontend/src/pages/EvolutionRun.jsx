// pages/EvolutionRun.jsx — Live evolution dashboard
import { useState, useEffect } from 'react'
import { apiGet, apiPost } from '../hooks/useApi'
import { useSSE } from '../hooks/useSSE'
import {
  Card, SectionTitle, StatBox, Tag, EmptyState, AccBadge, LiveDot, LogBox
} from '../components/Ui'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine
} from 'recharts'

export default function EvolutionRun({ formulaId, runId, onBack }) {
  const [runs,    setRuns]    = useState([])
  const [curRun,  setCurRun]  = useState(runId)
  const [history, setHistory] = useState(null)
  const [best,    setBest]    = useState(null)
  const [liveStats,setLiveStats]=useState(null)
  const [running, setRunning] = useState(false)
  const [logs,    setLogs]    = useState([])

  // SSE
  const { data: sseData } = useSSE('/api/evolve/stream', true)

  useEffect(() => {
    if (!sseData) return
    // Only apply if this run is active
    if (sseData.formula_id === formulaId && sseData.run_id === curRun) {
      setLiveStats(sseData)
      setRunning(sseData.is_running)
      if (sseData.gen_accepted > (liveStats?.gen_accepted ?? 0)) {
        setLogs(l => [...l, `[ACCEPT] gen ${sseData.best_gen} — acc ${(sseData.current_accuracy*100).toFixed(4)}%`])
      }
      if (!sseData.is_running && sseData.stop_reason) {
        setLogs(l => [...l, `[STOP] Reason: ${sseData.stop_reason}`])
        loadHistory()
      }
    }
  }, [sseData])

  useEffect(() => {
    if (!formulaId) return
    loadRuns()
  }, [formulaId])

  useEffect(() => {
    if (!curRun) return
    loadHistory()
    loadBest()
  }, [curRun])

  // Poll history while running
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => { loadHistory(); loadBest() }, 2000)
    return () => clearInterval(t)
  }, [running])

  async function loadRuns() {
    try {
      const data = await apiGet(`/api/evolve/${formulaId}/runs`)
      setRuns(data)
    } catch {}
  }

  async function loadHistory() {
    try {
      const data = await apiGet(`/api/evolve/${formulaId}/${curRun}/history`)
      setHistory(data)
    } catch {}
  }

  async function loadBest() {
    try {
      const data = await apiGet(`/api/evolve/${formulaId}/${curRun}/best`)
      setBest(data)
    } catch {}
  }

  async function handleStop() {
    try {
      await apiPost('/api/evolve/stop')
      setRunning(false)
      setLogs(l => [...l, '[STOP] Stop signal sent'])
      await loadHistory()
    } catch (e) {
      setLogs(l => [...l, `[ERROR] ${e.message}`])
    }
  }

  // Chart data from history
  const chartData = (history?.history ?? []).map(g => ({
    gen:     g.gen_number,
    acc:     +(g.accuracy * 100).toFixed(4),
    delta:   +(g.improvement * 100).toFixed(4),
  }))

  const startAcc  = history?.history?.[0]?.accuracy
  const currentAcc = liveStats?.current_accuracy ?? best?.accuracy

  // Custom tooltip
  function ChartTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null
    return (
      <div style={{ background: 'var(--ink)', border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: 'var(--radius)', padding: '8px 12px', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
        <div style={{ color: 'rgba(255,255,255,0.5)', marginBottom: 4 }}>gen {label}</div>
        <div style={{ color: 'var(--orange-2)' }}>acc: {payload[0]?.value}%</div>
        {payload[1] && <div style={{ color: 'var(--green)' }}>Δ: +{payload[1]?.value}%</div>}
      </div>
    )
  }

  if (!formulaId) {
    return (
      <div style={{ padding: 32 }}>
        <EmptyState icon="⟳" title="No run selected"
          sub="Open a run from the Formulas page." />
      </div>
    )
  }

  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <button className="btn" onClick={onBack} style={{ fontSize: 12 }}>← Back</button>
        <div>
          <h2 style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 24 }}>
            {formulaId}
            <span style={{ color: 'var(--ink-4)', fontSize: 16, marginLeft: 10, fontFamily: 'var(--font-mono)' }}>
              / {curRun}
            </span>
          </h2>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <LiveDot active={running} />
          <span style={{ fontSize: 13, color: running ? 'var(--green)' : 'var(--ink-3)' }}>
            {running ? 'Running' : 'Idle'}
          </span>
          {running && (
            <button className="btn btn-danger" onClick={handleStop}>■ Stop</button>
          )}
        </div>
      </div>

      {/* Run selector */}
      {runs.length > 1 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {runs.map(r => (
            <button key={r.run_id}
              className={`tab ${curRun === r.run_id ? 'active' : ''}`}
              onClick={() => setCurRun(r.run_id)}>
              {r.run_id}
              {r.best_accuracy != null && (
                <span style={{ marginLeft: 6, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  {(r.best_accuracy * 100).toFixed(2)}%
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Stats bar */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12 }}>
        <StatBox label="Start acc"  value={<AccBadge value={startAcc} />} />
        <StatBox label="Current"    value={<AccBadge value={currentAcc} />} />
        <StatBox label="Best"       value={<AccBadge value={liveStats?.best_accuracy ?? best?.accuracy} />} />
        <StatBox label="Accepted"   value={liveStats?.gen_accepted ?? history?.n_accepted ?? 0} />
        <StatBox label="Tried"      value={liveStats?.gen_tried?.toLocaleString() ?? '—'} />
        <StatBox label="Accept rate" value={
          liveStats ? `${(liveStats.accept_rate * 100).toFixed(1)}%` : '—'
        } />
      </div>

      {/* Accuracy chart */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <SectionTitle>Accuracy progression</SectionTitle>
          <div style={{ display: 'flex', gap: 16, fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--ink-3)' }}>
            <span style={{ color: 'var(--orange)' }}>— accuracy</span>
            <span style={{ color: 'var(--green)' }}>— Δ improvement</span>
          </div>
        </div>

        {chartData.length < 2 ? (
          <div style={{ height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--ink-4)', fontSize: 13 }}>
            {running ? 'Waiting for accepted mutations...' : 'No accepted mutations yet.'}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="gen" tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                label={{ value: 'Generation', position: 'insideBottom', offset: -2, fontSize: 10 }} />
              <YAxis yAxisId="acc" domain={['auto', 'auto']}
                tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                tickFormatter={v => v.toFixed(1) + '%'} width={52} />
              <YAxis yAxisId="delta" orientation="right"
                tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                tickFormatter={v => '+' + v.toFixed(2) + '%'} width={60} />
              <Tooltip content={<ChartTooltip />} />
              {startAcc && (
                <ReferenceLine yAxisId="acc" y={startAcc * 100}
                  stroke="rgba(255,255,255,0.2)" strokeDasharray="6 3"
                  label={{ value: 'start', position: 'right', fontSize: 9,
                            fill: 'rgba(255,255,255,0.4)', fontFamily: 'var(--font-mono)' }} />
              )}
              <Line yAxisId="acc"   type="monotone" dataKey="acc"
                stroke="var(--orange)" strokeWidth={2} dot={false} />
              <Line yAxisId="delta" type="monotone" dataKey="delta"
                stroke="var(--green)" strokeWidth={1.5} dot={false} opacity={0.7} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Card>

      {/* Two columns: best formula + log */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16 }}>

        {/* Best formula */}
        <Card>
          <SectionTitle>Best formula</SectionTitle>
          {best ? (
            <>
              <div style={{ display: 'flex', gap: 8, marginTop: 10, marginBottom: 12, flexWrap: 'wrap' }}>
                <Tag variant="orange">gen {best.gen_number}</Tag>
                <Tag variant="green">size {best.tree_size}</Tag>
                <Tag variant="blue">depth {best.tree_depth}</Tag>
                <AccBadge value={best.accuracy} />
              </div>
              <div style={{
                fontFamily:    'var(--font-mono)', fontSize: 12,
                background:    'var(--bg-subtle)', borderRadius: 'var(--radius)',
                padding:       '12px 14px', overflowX: 'auto',
                whiteSpace:    'pre-wrap', wordBreak: 'break-all', lineHeight: 1.8,
              }}>
                {best.repr ?? '—'}
              </div>
              {(best.vars ?? []).length > 0 && (
                <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  {best.vars.slice(0, 8).map(v => (
                    <Tag key={v} variant="gold">{v.split('.').pop()}</Tag>
                  ))}
                  {best.vars.length > 8 && <Tag variant="gold">+{best.vars.length - 8}</Tag>}
                </div>
              )}
            </>
          ) : (
            <div style={{ color: 'var(--ink-4)', fontSize: 13, marginTop: 10 }}>
              No mutations accepted yet.
            </div>
          )}
        </Card>

        {/* Log */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Card>
            <SectionTitle>
              <LiveDot active={running} />
              Live log
            </SectionTitle>
            <div style={{ marginTop: 8 }}>
              <LogBox lines={logs} />
            </div>
          </Card>

          {/* Stats detail */}
          {liveStats && (
            <Card>
              <SectionTitle>Engine stats</SectionTitle>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 10 }}>
                <StatBox label="Rejected"  value={liveStats.gen_rejected?.toLocaleString()} />
                <StatBox label="Invalid"   value={liveStats.gen_invalid?.toLocaleString()} />
                <StatBox label="Speed"     value={`${Math.round(liveStats.mutations_per_s ?? 0)}/s`} />
                <StatBox label="Stagnation" value={`${liveStats.stagnation_count}`} />
                <StatBox label="Elapsed"   value={`${liveStats.elapsed_s?.toFixed(0)}s`} />
                <StatBox label="Best gen"  value={liveStats.best_gen} />
              </div>
            </Card>
          )}
        </div>
      </div>

      {/* History table */}
      {(history?.history?.length ?? 0) > 0 && (
        <Card>
          <SectionTitle>Accepted mutations history ({history.n_accepted} total)</SectionTitle>
          <div style={{ marginTop: 12, overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border)' }}>
                  {['Gen', 'Accuracy', 'Improvement', 'Games eval.', 'Tree size', 'Time'].map(h => (
                    <th key={h} style={{ padding: '6px 12px', textAlign: 'left', fontFamily: 'var(--font-mono)',
                      fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--ink-3)' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...(history.history ?? [])].reverse().slice(0, 50).map(g => (
                  <tr key={g.gen_number} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '7px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                      {g.gen_number}
                    </td>
                    <td style={{ padding: '7px 12px' }}><AccBadge value={g.accuracy} /></td>
                    <td style={{ padding: '7px 12px', fontFamily: 'var(--font-mono)', fontSize: 11,
                      color: g.improvement > 0 ? 'var(--green)' : 'var(--ink-3)' }}>
                      {g.improvement > 0 ? '+' : ''}{(g.improvement * 100).toFixed(4)}%
                    </td>
                    <td style={{ padding: '7px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                      {g.n_games_eval?.toLocaleString()}
                    </td>
                    <td style={{ padding: '7px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)' }}>
                      {g.tree_size}
                    </td>
                    <td style={{ padding: '7px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-4)' }}>
                      {g.timestamp?.slice(11, 19) ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
