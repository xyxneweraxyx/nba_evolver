// pages/Dashboard.jsx — Formula situational analysis
import { useState, useEffect } from 'react'
import { apiGet, apiPost } from '../hooks/useApi'
import { Card, SectionTitle, StatBox, Tag, EmptyState, AccBadge } from '../components/Ui'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts'

// ── helpers ──────────────────────────────────────────────────────────────────

function delta(acc, baseline) {
  if (acc == null || baseline == null) return null
  return +(acc - baseline).toFixed(4)
}

function DeltaBadge({ value }) {
  if (value == null) return <span style={{ color: 'var(--ink-4)' }}>—</span>
  const pct   = (Math.abs(value) * 100).toFixed(2)
  const plus  = value >= 0 ? '+' : '-'
  const color = value >= 0.02  ? 'var(--green)'
              : value <= -0.02 ? 'var(--red)'
              : 'var(--ink-3)'
  return <span style={{ color, fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: 11 }}>
    {plus}{pct}%
  </span>
}

function AccBar({ accuracy, baseline, maxVal = 1 }) {
  const pct  = (accuracy * 100).toFixed(1)
  const bpct = (baseline  * 100).toFixed(1)
  const color = accuracy >= baseline + 0.02 ? 'var(--green)'
              : accuracy <= baseline - 0.02 ? 'var(--red)'
              : 'var(--orange)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, background: 'var(--bg-subtle)', borderRadius: 3, height: 6, position: 'relative' }}>
        <div style={{ position: 'absolute', left: `${bpct}%`, top: -2, bottom: -2,
          width: 2, background: 'var(--ink-4)', borderRadius: 1 }} />
        <div style={{ width: `${pct}%`, height: '100%', background: color,
          borderRadius: 3, transition: 'width 0.3s' }} />
      </div>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color, fontWeight: 700, minWidth: 44 }}>
        {pct}%
      </span>
    </div>
  )
}

// ── Recharts custom tooltip ───────────────────────────────────────────────────

function ChartTooltip({ active, payload, label, baseline }) {
  if (!active || !payload?.length) return null
  const acc = payload[0]?.value
  const d   = delta(acc / 100, baseline)
  return (
    <div style={{ background: 'var(--ink)', border: '1px solid rgba(255,255,255,0.1)',
      borderRadius: 'var(--radius)', padding: '8px 12px', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
      <div style={{ color: 'rgba(255,255,255,0.5)', marginBottom: 4 }}>{label}</div>
      <div style={{ color: 'var(--orange-2)' }}>{acc?.toFixed(2)}%</div>
      {d != null && <div style={{ color: d >= 0 ? 'var(--green)' : 'var(--red)' }}>
        {d >= 0 ? '+' : ''}{(d*100).toFixed(2)}% vs baseline
      </div>}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Dashboard() {
  // Formula source
  const [sourceTab,    setSourceTab]    = useState('generated')  // 'generated' | 'evolved'
  const [batches,      setBatches]      = useState([])
  const [curBatch,     setCurBatch]     = useState('')
  const [genForms,     setGenForms]     = useState([])
  const [genPage,      setGenPage]      = useState(0)
  const [evolvedList,  setEvolvedList]  = useState([])  // [{formula_id, runs}]
  const [curFid,       setCurFid]       = useState('')
  const [curRid,       setCurRid]       = useState('')
  const [fRuns,        setFRuns]        = useState([])
  // Selected formula
  const [selected,     setSelected]     = useState(null)  // {tree, repr, label}
  // Results
  const [loading,      setLoading]      = useState(false)
  const [results,      setResults]      = useState(null)
  const [evalError,    setEvalError]    = useState(null)

  const GEN_PAGE = 20

  useEffect(() => {
    apiGet('/api/explore/batches').then(data => {
      setBatches(data)
      if (data.length > 0) {
        const latest = data[data.length - 1].name
        setCurBatch(latest)
        loadGen(latest, 0)
      }
    }).catch(() => {})
    apiGet('/api/formulas').then(setEvolvedList).catch(() => {})
  }, [])

  async function loadGen(batch, pg) {
    try {
      const data = await apiGet(`/api/explore/batch/${batch}?offset=${pg * GEN_PAGE}&limit=${GEN_PAGE}`)
      setGenForms(data)
    } catch {}
  }

  async function loadRuns(fid) {
    try {
      const runs = await apiGet(`/api/evolve/${fid}/runs`)
      setFRuns(runs)
      if (runs.length > 0) setCurRid(runs[runs.length - 1].run_id)
    } catch {}
  }

  async function handleEvaluate() {
    if (!selected) return
    setLoading(true); setResults(null); setEvalError(null)
    try {
      const res = await apiPost('/api/dashboard/evaluate', { tree: selected.tree })
      setResults(res)
    } catch (e) {
      setEvalError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const train     = results?.train
  const test      = results?.test
  const baseline  = train?.baseline ?? 0.6037

  // Chart data for season slices
  const sliceData = (train?.by_season_slice ?? []).map(s => ({
    label: s.label.split(' ')[0],   // "Early", "Mid", "Late"
    acc:   +(s.accuracy * 100).toFixed(2),
    n:     s.n_games,
  }))

  // Chart data for rest breakdown
  const restData = (train?.by_rest ?? []).map(r => ({
    label: r.label,
    acc:   +(r.accuracy * 100).toFixed(2),
    n:     r.n_games,
  }))

  const barColor = (acc) => {
    const a = acc / 100
    return a >= baseline + 0.02 ? '#1A7A45'
         : a <= baseline - 0.02 ? '#C0392B'
         : '#E8520A'
  }

  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* ── Header ── */}
      <div>
        <h2 style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 26 }}>
          Formula Dashboard
        </h2>
        <p style={{ color: 'var(--ink-3)', marginTop: 4, fontSize: 13 }}>
          Situational analysis — where does this formula work, and where does it fail?
        </p>
      </div>

      {/* ── Formula picker ── */}
      <Card>
        <SectionTitle>Select formula to analyse</SectionTitle>

        {/* Source tabs */}
        <div style={{ display: 'flex', gap: 0, borderBottom: '2px solid var(--border)', margin: '12px 0 16px' }}>
          {[['generated', 'Generated'], ['evolved', 'Evolved']].map(([id, label]) => (
            <button key={id} onClick={() => setSourceTab(id)}
              style={{ padding: '7px 16px', fontWeight: 600, fontSize: 13, cursor: 'pointer',
                background: 'none', border: 'none', borderBottom: `2px solid ${sourceTab===id ? 'var(--orange)' : 'transparent'}`,
                color: sourceTab===id ? 'var(--orange)' : 'var(--ink-3)', marginBottom: -2 }}>
              {label}
            </button>
          ))}
        </div>

        {/* Generated picker */}
        {sourceTab === 'generated' && (
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
              <select value={curBatch} onChange={e => { setCurBatch(e.target.value); setGenPage(0); loadGen(e.target.value, 0) }}
                style={{ padding: '6px 10px', borderRadius: 'var(--radius)', border: '1px solid var(--border)',
                  fontSize: 12, fontFamily: 'var(--font-mono)', background: 'var(--bg-card)', cursor: 'pointer' }}>
                {batches.map(b => <option key={b.name} value={b.name}>{b.name} ({b.n_formulas})</option>)}
              </select>
              <button className="btn" style={{fontSize:11}} disabled={genPage===0}
                onClick={() => { setGenPage(p=>p-1); loadGen(curBatch, genPage-1) }}>←</button>
              <span style={{ fontSize:12, color:'var(--ink-3)' }}>p.{genPage+1}</span>
              <button className="btn" style={{fontSize:11}} disabled={genForms.length<GEN_PAGE}
                onClick={() => { setGenPage(p=>p+1); loadGen(curBatch, genPage+1) }}>→</button>
            </div>
            {genForms.length === 0
              ? <p style={{ color: 'var(--ink-4)', fontSize: 13 }}>No generated formulas. Run exploration first.</p>
              : <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 280, overflowY: 'auto' }}>
                  {genForms.map(rec => (
                    <div key={rec.id} onClick={() => setSelected({ tree: rec.tree, repr: rec.repr, label: rec.id })}
                      style={{
                        padding: '8px 12px', borderRadius: 'var(--radius)', cursor: 'pointer',
                        background: selected?.label===rec.id ? 'var(--orange-dim)' : 'var(--bg-subtle)',
                        border: `1px solid ${selected?.label===rec.id ? 'var(--orange)' : 'transparent'}`,
                        display: 'grid', gridTemplateColumns: '1fr auto auto auto', gap: 10, alignItems: 'center',
                      }}>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11,
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {rec.repr}
                      </div>
                      <AccBadge value={rec.score?.accuracy} />
                      <Tag variant={rec.score?.direction===1?'green':'orange'}>
                        {rec.score?.direction===1?'GOOD':'BAD'}
                      </Tag>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-4)' }}>{rec.id}</span>
                    </div>
                  ))}
                </div>
            }
          </div>
        )}

        {/* Evolved picker */}
        {sourceTab === 'evolved' && (
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 11, color: 'var(--ink-4)', marginBottom: 4 }}>Formula</div>
              <select value={curFid} onChange={e => { setCurFid(e.target.value); loadRuns(e.target.value) }}
                style={{ padding: '6px 10px', borderRadius: 'var(--radius)', border: '1px solid var(--border)',
                  fontSize: 12, fontFamily: 'var(--font-mono)', background: 'var(--bg-card)', cursor: 'pointer' }}>
                <option value="">-- select --</option>
                {evolvedList.map(f => <option key={f.formula_id} value={f.formula_id}>{f.formula_id}</option>)}
              </select>
            </div>
            {fRuns.length > 0 && (
              <div>
                <div style={{ fontSize: 11, color: 'var(--ink-4)', marginBottom: 4 }}>Run</div>
                <select value={curRid} onChange={e => setCurRid(e.target.value)}
                  style={{ padding: '6px 10px', borderRadius: 'var(--radius)', border: '1px solid var(--border)',
                    fontSize: 12, fontFamily: 'var(--font-mono)', background: 'var(--bg-card)', cursor: 'pointer' }}>
                  {fRuns.map(r => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id} — {r.best_accuracy ? (r.best_accuracy*100).toFixed(2)+'%' : 'no best'}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {curFid && curRid && (
              <div style={{ paddingTop: 22 }}>
                <button className="btn" onClick={async () => {
                  try {
                    const best = await apiGet(`/api/evolve/${curFid}/${curRid}/best`)
                    if (best?.tree) setSelected({ tree: best.tree, repr: best.repr, label: `${curFid}/${curRid}` })
                  } catch {}
                }}>
                  Load best formula
                </button>
              </div>
            )}
          </div>
        )}

        {/* Selected formula indicator */}
        {selected && (
          <div style={{ marginTop: 14, background: 'var(--orange-dim)', borderRadius: 'var(--radius)',
            padding: '10px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
            <div>
              <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--orange)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 }}>
                Selected — {selected.label}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 600 }}>
                {selected.repr}
              </div>
            </div>
            <button className="btn btn-primary" onClick={handleEvaluate} disabled={loading}>
              {loading ? '⟳ Evaluating...' : '▶ Evaluate'}
            </button>
          </div>
        )}

        {evalError && (
          <div style={{ marginTop: 12, background: 'var(--red-dim)', color: 'var(--red)',
            padding: '8px 12px', borderRadius: 'var(--radius)', fontSize: 12 }}>
            {evalError}
          </div>
        )}
      </Card>

      {/* ── Results ── */}
      {!results && !loading && (
        <EmptyState icon="◈" title="Select a formula and click Evaluate"
          sub="The dashboard will show you situational performance across all game contexts." />
      )}

      {loading && (
        <EmptyState icon="⟳" title="Evaluating..." sub="Running formula on 9,840+ games..." />
      )}

      {results && (
        <>
          {/* ── Overview stats ── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
            <StatBox label="Train accuracy"
              value={<AccBadge value={train?.overall?.accuracy} />}
              sub={`${train?.overall?.n_games?.toLocaleString()} games`} />
            <StatBox label="Test accuracy"
              value={test ? <AccBadge value={test?.overall?.accuracy} /> : <span style={{color:'var(--ink-4)'}}>—</span>}
              sub={test ? `${test?.overall?.n_games?.toLocaleString()} games` : 'no test data'} />
            <StatBox label="Baseline (always home)"
              value={<span style={{ fontFamily:'var(--font-mono)', fontWeight:700, color:'var(--ink-3)' }}>
                {(baseline*100).toFixed(2)}%
              </span>} />
            <StatBox label="vs baseline (train)"
              value={<DeltaBadge value={delta(train?.overall?.accuracy, baseline)} />} />
            <StatBox label="Predicts home"
              value={<span style={{ fontFamily:'var(--font-mono)', fontWeight:700 }}>
                {train?.pred_dist ? (train.pred_dist.pct_predict_home*100).toFixed(1)+'%' : '—'}
              </span>}
              sub={`of ${train?.overall?.n_games?.toLocaleString()} games`} />
          </div>

          {/* ── Formula info ── */}
          <Card>
            <SectionTitle>Formula</SectionTitle>
            <div style={{ display: 'flex', gap: 8, margin: '10px 0 10px', flexWrap: 'wrap' }}>
              <Tag variant="orange">size: {results.formula_size}</Tag>
              <Tag variant="blue">depth: {results.formula_depth}</Tag>
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, background: 'var(--bg-subtle)',
              borderRadius: 'var(--radius)', padding: '10px 14px',
              overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all', lineHeight: 1.8 }}>
              {results.formula_repr}
            </div>
          </Card>

          {/* ── Prediction distribution ── */}
          {train?.pred_dist && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <Card>
                <SectionTitle>Prediction breakdown</SectionTitle>
                <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {[
                    { label: 'When predicts HOME', acc: train.pred_dist.accuracy_when_predict_home, n: train.pred_dist.n_predict_home },
                    { label: 'When predicts AWAY', acc: train.pred_dist.accuracy_when_predict_away, n: train.pred_dist.n_predict_away },
                  ].map(row => (
                    <div key={row.label}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{row.label}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-4)' }}>
                          {row.n?.toLocaleString()} games
                        </span>
                      </div>
                      <AccBar accuracy={row.acc} baseline={baseline} />
                    </div>
                  ))}
                </div>
              </Card>

              <Card>
                <SectionTitle>True result breakdown</SectionTitle>
                <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {[
                    { label: 'On true home wins', data: train.by_true_result?.true_home_wins },
                    { label: 'On true away wins', data: train.by_true_result?.true_away_wins },
                  ].map(row => row.data && (
                    <div key={row.label}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: 12, color: 'var(--ink-2)' }}>{row.label}</span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-4)' }}>
                          {row.data.n_games?.toLocaleString()} games
                        </span>
                      </div>
                      <AccBar accuracy={row.data.accuracy} baseline={baseline} />
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          )}

          {/* ── Season slices chart ── */}
          {sliceData.length > 0 && (
            <Card>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <SectionTitle>Performance by season phase</SectionTitle>
                <span style={{ fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)' }}>
                  dotted line = baseline {(baseline*100).toFixed(1)}%
                </span>
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={sliceData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontFamily: 'var(--font-mono)', fontSize: 11 }} />
                  <YAxis domain={[Math.max(0, baseline * 100 - 10), Math.min(100, baseline * 100 + 15)]}
                    tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                    tickFormatter={v => v.toFixed(0) + '%'} width={40} />
                  <Tooltip content={<ChartTooltip baseline={baseline} />} />
                  <ReferenceLine y={baseline * 100} stroke="var(--ink-4)" strokeDasharray="4 3" />
                  <Bar dataKey="acc" radius={[4, 4, 0, 0]}>
                    {sliceData.map((entry, i) => (
                      <Cell key={i} fill={barColor(entry.acc)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}

          {/* ── Rest days chart ── */}
          {restData.length > 0 && (
            <Card>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <SectionTitle>Performance by home team rest days</SectionTitle>
              </div>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={restData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }} />
                  <YAxis domain={[Math.max(0, baseline * 100 - 10), Math.min(100, baseline * 100 + 15)]}
                    tick={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                    tickFormatter={v => v.toFixed(0) + '%'} width={40} />
                  <Tooltip content={<ChartTooltip baseline={baseline} />} />
                  <ReferenceLine y={baseline * 100} stroke="var(--ink-4)" strokeDasharray="4 3" />
                  <Bar dataKey="acc" radius={[4, 4, 0, 0]}>
                    {restData.map((entry, i) => (
                      <Cell key={i} fill={barColor(entry.acc)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}

          {/* ── Situational breakdown table ── */}
          {train?.situational && (
            <Card>
              <SectionTitle>Situational breakdown — training set</SectionTitle>
              <div style={{ marginTop: 12, overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid var(--border)' }}>
                      {['Context', 'Accuracy', 'vs baseline', 'N games', 'Bar'].map(h => (
                        <th key={h} style={{ padding: '6px 12px', textAlign: 'left',
                          fontFamily: 'var(--font-mono)', fontSize: 10,
                          textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--ink-3)' }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(train.situational)
                      .filter(([, v]) => v && v.n_games >= 30)
                      .sort((a, b) => (b[1]?.accuracy ?? 0) - (a[1]?.accuracy ?? 0))
                      .map(([label, data]) => {
                        const d = delta(data.accuracy, baseline)
                        return (
                          <tr key={label} style={{ borderBottom: '1px solid var(--border)' }}>
                            <td style={{ padding: '8px 12px', color: 'var(--ink-2)' }}>{label}</td>
                            <td style={{ padding: '8px 12px' }}><AccBadge value={data.accuracy} /></td>
                            <td style={{ padding: '8px 12px' }}><DeltaBadge value={d} /></td>
                            <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)',
                              fontSize: 11, color: 'var(--ink-4)' }}>
                              {data.n_games?.toLocaleString()}
                            </td>
                            <td style={{ padding: '8px 12px', minWidth: 160 }}>
                              <AccBar accuracy={data.accuracy} baseline={baseline} />
                            </td>
                          </tr>
                        )
                      })}
                  </tbody>
                </table>
                <p style={{ marginTop: 8, fontSize: 11, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)' }}>
                  Filters with fewer than 30 games are hidden. Bar dotted line = baseline.
                </p>
              </div>
            </Card>
          )}

          {/* ── Test set comparison ── */}
          {test && (
            <Card>
              <SectionTitle>Test set (unseen data)</SectionTitle>
              <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                <StatBox label="Test accuracy"   value={<AccBadge value={test.overall?.accuracy} />} />
                <StatBox label="vs train acc"    value={<DeltaBadge value={delta(test.overall?.accuracy, train?.overall?.accuracy)} />} />
                <StatBox label="vs baseline"     value={<DeltaBadge value={delta(test.overall?.accuracy, baseline)} />} />
                <StatBox label="Test games"      value={test.overall?.n_games?.toLocaleString()} />
              </div>
              <p style={{ marginTop: 12, fontSize: 12, color: 'var(--ink-3)' }}>
                {test.overall?.accuracy >= train?.overall?.accuracy - 0.01
                  ? '✅ Formula generalizes well — test accuracy close to training.'
                  : test.overall?.accuracy >= baseline
                    ? '⚠️ Some overfitting — lower on test set but still beats baseline.'
                    : '❌ Overfitting likely — formula underperforms baseline on unseen data.'}
              </p>
            </Card>
          )}
        </>
      )}
    </div>
  )
}