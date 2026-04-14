// pages/Generate.jsx — Exploration engine dashboard
import { useState, useEffect } from 'react'
import { apiGet, apiPost } from '../hooks/useApi'
import { useSSE } from '../hooks/useSSE'
import { Card, SectionTitle, StatBox, Slider, LogBox, Tag, EmptyState, LiveDot, AccBadge, IntBadge } from '../components/Ui'

// interest_threshold is stored as accuracy % (e.g. 62.0 = 62.0% accuracy)
// interest score = (acc% - 50) / 50  → 62% = 0.24 interest
function interestLabel(v) {
  return `${v.toFixed(1)}% accuracy`
}

const DEFAULT_CFG = {
  max_depth: 4, max_size: 50,
  interest_threshold: 56.0, // accuracy % threshold (61.0–65.0, maps to interest score)
  block_size: 100,
  fast_prefilter_n: 500,
  interest_mode: 'both',
  max_saved: 32,   // 0 = unlimited
  dedup_enabled: true,
  report_every: 200,
}

const PAGE_SIZE = 30

export default function Generate({ onSendToEvolve }) {
  const [cfg,       setCfg]       = useState(DEFAULT_CFG)
  const [running,   setRunning]   = useState(false)
  const [stats,     setStats]     = useState(null)
  const [logs,      setLogs]      = useState([])
  const [batch,     setBatch]     = useState([])
  const [batchName, setBatchName] = useState('')
  const [allBatches,setAllBatches]= useState([])
  const [selected,  setSelected]  = useState(null)
  const [page,      setPage]      = useState(0)

  const { data: sseData } = useSSE('/api/explore/stream', running)

  useEffect(() => {
    const init = async () => {
      try {
        const status = await apiGet('/api/status')
        if (status.explore_running) {
          setRunning(true)
          if (status.explore_stats) setStats(status.explore_stats)
        }
        const batches = await apiGet('/api/explore/batches')
        setAllBatches(batches)
        if (batches.length > 0) {
          const latest = batches[batches.length - 1]
          setBatchName(latest.name)
          const data = await apiGet(`/api/explore/batch/${latest.name}?offset=0&limit=${PAGE_SIZE}`)
          setBatch(data)
        }
        const summ = await apiGet('/api/explore/summary')
        if (summ?.stats) setStats(summ.stats)
      } catch {}
    }
    init()
  }, [])

  useEffect(() => {
    if (!sseData) return
    setStats(sseData)
    if (sseData.n_saved > 0 && running) {
      setLogs(l => {
        const last = l[l.length - 1] ?? ''
        const msg = `[SAVE] ${sseData.n_saved} saved — best interest ${(sseData.best_interest*100).toFixed(1)}%`
        if (last === msg) return l
        return [...l, msg]
      })
    }
  }, [sseData])

  useEffect(() => {
    if (!running || !batchName) return
    const t = setInterval(() => loadBatch(batchName, page), 2500)
    return () => clearInterval(t)
  }, [running, batchName, page])

  async function loadBatch(name, pg = 0) {
    try {
      const data = await apiGet(`/api/explore/batch/${name}?offset=${pg * PAGE_SIZE}&limit=${PAGE_SIZE}`)
      setBatch(data)
    } catch {}
  }

  async function handleStart() {
    const name = `batch_${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}`
    const interest = (cfg.interest_threshold - 50) / 50  // acc% → interest score
    setBatchName(name); setBatch([]); setPage(0); setSelected(null); setStats(null)
    setLogs([`[START] batch: ${name} — threshold: ${interestLabel(cfg.interest_threshold)}`])
    try {
      await apiPost('/api/explore/start', {
        ...cfg,
        batch_name:        name,
        min_interest:      interest,
        save_min_interest: interest,
        fast_min_interest: Math.max(0.05, interest * 0.5),
        report_every:      cfg.report_every,
      })
      setRunning(true)
      setAllBatches(prev => [...prev, { name, n_formulas: 0 }])
    } catch (e) { setLogs(l => [...l, `[ERROR] ${e.message}`]) }
  }

  async function handleStop() {
    try {
      await apiPost('/api/explore/stop')
      setRunning(false)
      setLogs(l => [...l, '[STOP] Exploration stopped.'])
      if (batchName) await loadBatch(batchName, page)
    } catch (e) { setLogs(l => [...l, `[ERROR] ${e.message}`]) }
  }

  function set(k) { return v => setCfg(c => ({ ...c, [k]: v })) }

  return (
    <div style={{ padding: 32, display: 'grid', gridTemplateColumns: '320px 1fr', gap: 20, alignItems: 'start' }}>

      {/* ── LEFT: Config ── */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className="train-panel">
          <SectionTitle style={{ color: 'rgba(255,255,255,0.4)' }}>Exploration Config</SectionTitle>

          {/* Formula shape */}
          <div style={{ marginTop: 20 }}>
            <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:12 }}>Formula shape</div>
            <div className="slider-row" style={{ gridTemplateColumns:'1fr 1fr' }}>
              <Slider label="Max depth" value={cfg.max_depth} min={2} max={8} step={1} onChange={set('max_depth')} />
              <Slider label="Max size (nodes)" value={cfg.max_size} min={5} max={120} step={5} onChange={set('max_size')} />
            </div>
          </div>

          {/* Interest threshold — accuracy % */}
          <div style={{ marginTop: 20 }}>
            <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:12 }}>Interest threshold</div>
            <div className="slider-group">
              <label>Min accuracy to keep (above 60.37% baseline)</label>
              <div className="slider-value" style={{ fontSize: 18 }}>
                {interestLabel(cfg.interest_threshold)}
                <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', marginLeft: 8 }}>
                  interest = {((cfg.interest_threshold - 50) / 50 * 100).toFixed(1)}%
                </span>
              </div>
              <input type="range" min={55.0} max={65.0} step={0.1} value={cfg.interest_threshold}
                onChange={e => set('interest_threshold')(+e.target.value)} />
              <div style={{ display:'flex', justifyContent:'space-between', fontSize:9,
                fontFamily:'var(--font-mono)', color:'rgba(255,255,255,0.25)', marginTop:4 }}>
                <span>55%</span><span>57.5%</span><span>60%</span><span>62.5%</span><span>65%</span>
              </div>
            </div>
          </div>

          {/* Evaluation */}
          <div style={{ marginTop: 20 }}>
            <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:12 }}>Evaluation</div>
            <div className="slider-row" style={{ gridTemplateColumns:'1fr 1fr' }}>
              <Slider label="Block size (games)" value={cfg.block_size} min={50} max={500} step={50} onChange={set('block_size')} />
              <Slider label="Fast pre-filter" value={cfg.fast_prefilter_n} min={0} max={2000} step={100} onChange={set('fast_prefilter_n')} />
              <Slider label="Report every N" value={cfg.report_every} min={50} max={1000} step={50} onChange={set('report_every')} />
              <div className="slider-group">
                <label>Max saved (0 = ∞)</label>
                <div className="slider-value">{cfg.max_saved === 0 ? '∞' : cfg.max_saved}</div>
                <select value={cfg.max_saved} onChange={e => set('max_saved')(+e.target.value)}
                  style={{ width:'100%', padding:'6px 8px', borderRadius:'var(--radius)',
                    border:'1px solid rgba(255,255,255,0.15)', background:'rgba(255,255,255,0.08)',
                    color:'#fff', fontFamily:'var(--font-mono)', fontSize:12, cursor:'pointer' }}>
                  {[0,1,2,4,8,16,32,64,128,256].map(v => (
                    <option key={v} value={v}>{v === 0 ? '∞ unlimited' : v}</option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* Direction */}
          <div style={{ marginTop: 20 }}>
            <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', letterSpacing:'0.08em', textTransform:'uppercase', marginBottom:8 }}>Direction</div>
            <div style={{ display:'flex', gap:6 }}>
              {['both','good_only','bad_only'].map(m => (
                <button key={m} onClick={() => setCfg(c => ({...c, interest_mode: m}))}
                  style={{ flex:1, padding:'7px 0', borderRadius:'var(--radius)', fontSize:10,
                    fontFamily:'var(--font-mono)', cursor:'pointer', border:'1px solid',
                    background:   cfg.interest_mode===m ? 'var(--orange)'     : 'rgba(255,255,255,0.05)',
                    borderColor:  cfg.interest_mode===m ? 'var(--orange)'     : 'rgba(255,255,255,0.12)',
                    color:        cfg.interest_mode===m ? '#fff'              : 'rgba(255,255,255,0.5)',
                    textTransform:'uppercase', letterSpacing:'0.05em' }}>
                  {m==='both'?'Both':m==='good_only'?'Good':'Bad'}
                </button>
              ))}
            </div>
          </div>

          {/* Dedup */}
          <div style={{ marginTop:16 }}>
            <label style={{ display:'flex', alignItems:'center', gap:8, cursor:'pointer',
              fontFamily:'var(--font-mono)', fontSize:11, color:'rgba(255,255,255,0.5)' }}>
              <input type="checkbox" checked={cfg.dedup_enabled}
                onChange={e => setCfg(c => ({...c, dedup_enabled: e.target.checked}))} />
              Deduplicate formulas across batches
            </label>
          </div>

          {/* Start/Stop */}
          <div style={{ marginTop: 24 }}>
            {!running
              ? <button className="btn btn-primary" style={{ width:'100%', padding:12 }} onClick={handleStart}>▶ Start Exploration</button>
              : <button className="btn btn-danger"  style={{ width:'100%', padding:12 }} onClick={handleStop}>■ Stop</button>
            }
          </div>
        </div>

        {/* Live stats */}
        {stats && (
          <Card>
            <SectionTitle><LiveDot active={running} />Live stats</SectionTitle>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10, marginTop:12 }}>
              <StatBox label="Generated"    value={stats.n_generated?.toLocaleString()} />
              <StatBox label="Saved"        value={stats.n_saved?.toLocaleString()} />
              <StatBox label="Speed"        value={`${Math.round(stats.formulas_per_s??0)}/s`} />
              <StatBox label="Survival"     value={`${((stats.survival_rate??0)*100).toFixed(1)}%`} />
              <StatBox label="Prefiltered"  value={stats.n_prefiltered?.toLocaleString()} />
              <StatBox label="Filtered"     value={stats.n_filtered?.toLocaleString()} />
              <StatBox label="Best interest" value={<IntBadge value={stats.best_interest} />} />
              <StatBox label="Direction"    value={stats.best_direction===1?'▲ GOOD':'▼ BAD'} />
            </div>
          </Card>
        )}

        <Card>
          <SectionTitle>Log</SectionTitle>
          <div style={{ marginTop:8 }}><LogBox lines={logs} /></div>
        </Card>
      </div>

      {/* ── RIGHT: Formulas list ── */}
      <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <h2 style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:22 }}>
            Generated Formulas
          </h2>
          <div style={{ display:'flex', gap:8, alignItems:'center' }}>
            {allBatches.length > 0 && (
              <select value={batchName}
                onChange={async e => {
                  const name = e.target.value; setBatchName(name); setPage(0); setSelected(null)
                  const data = await apiGet(`/api/explore/batch/${name}?offset=0&limit=${PAGE_SIZE}`)
                  setBatch(data)
                }}
                style={{ padding:'6px 10px', borderRadius:'var(--radius)', border:'1px solid var(--border)',
                  fontSize:12, fontFamily:'var(--font-mono)', background:'var(--bg-card)', cursor:'pointer' }}>
                {allBatches.map(b => <option key={b.name} value={b.name}>{b.name} ({b.n_formulas})</option>)}
              </select>
            )}
            <button className="btn" style={{fontSize:12}} disabled={page===0}
              onClick={() => { setPage(p=>p-1); loadBatch(batchName, page-1) }}>←</button>
            <span style={{ padding:'6px 10px', color:'var(--ink-3)', fontSize:12 }}>p.{page+1}</span>
            <button className="btn" style={{fontSize:12}} disabled={batch.length < PAGE_SIZE}
              onClick={() => { setPage(p=>p+1); loadBatch(batchName, page+1) }}>→</button>
          </div>
        </div>

        {batch.length === 0 ? (
          <EmptyState icon="◈" title="No formulas yet"
            sub={running ? 'Running — formulas appear here as they are saved.' : 'Start exploration to find formulas.'} />
        ) : (
          <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
            {batch.map(rec => (
              <div key={rec.id} style={{ display:'flex', flexDirection:'column' }}>
                {/* Row */}
                <div onClick={() => setSelected(selected?.id===rec.id ? null : rec)}
                  style={{
                    background:   selected?.id===rec.id ? 'var(--orange-dim)' : 'var(--bg-card)',
                    border:       `1px solid ${selected?.id===rec.id ? 'var(--orange)' : 'var(--border)'}`,
                    borderRadius: selected?.id===rec.id ? 'var(--radius) var(--radius) 0 0' : 'var(--radius)',
                    padding:'10px 14px', cursor:'pointer',
                    display:'grid', gridTemplateColumns:'1fr auto auto auto', gap:12, alignItems:'center',
                  }}>
                  <div>
                    <div style={{ fontFamily:'var(--font-mono)', fontSize:10, color:'var(--ink-4)', marginBottom:3 }}>{rec.id}</div>
                    <div style={{ fontFamily:'var(--font-mono)', fontSize:12, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                      {rec.repr}
                    </div>
                  </div>
                  <div style={{ textAlign:'center' }}>
                    <div style={{ fontSize:9, color:'var(--ink-4)', marginBottom:2 }}>INTEREST</div>
                    <IntBadge value={rec.score?.interest} />
                  </div>
                  <div style={{ textAlign:'center' }}>
                    <div style={{ fontSize:9, color:'var(--ink-4)', marginBottom:2 }}>ACC</div>
                    <AccBadge value={rec.score?.accuracy} />
                  </div>
                  <Tag variant={rec.score?.direction===1 ? 'green' : 'orange'}>
                    {rec.score?.direction===1 ? 'GOOD' : 'BAD'}
                  </Tag>
                </div>

                {/* Expanded detail */}
                {selected?.id === rec.id && (
                  <div style={{
                    background:'var(--bg-subtle)', border:`1px solid var(--orange)`,
                    borderTop:'none', borderRadius:'0 0 var(--radius) var(--radius)',
                    padding:'14px 16px',
                  }}>
                    <div style={{ display:'flex', gap:8, marginBottom:10, flexWrap:'wrap' }}>
                      <Tag variant="orange">size: {rec.tree_size}</Tag>
                      <Tag variant="blue">depth: {rec.tree_depth}</Tag>
                      {(rec.vars??[]).map(v => <Tag key={v} variant="gold">{v.split('.').pop()}</Tag>)}
                    </div>
                    {/* Full formula — no truncation */}
                    <div style={{ fontFamily:'var(--font-mono)', fontSize:12, lineHeight:1.9,
                      background:'var(--bg-card)', borderRadius:'var(--radius)', padding:'12px 14px',
                      overflowX:'auto', whiteSpace:'pre-wrap', wordBreak:'break-all', marginBottom:12 }}>
                      {rec.repr}
                    </div>
                    <button className="btn btn-primary" onClick={() => onSendToEvolve(rec)}>
                      Send to Evolution →
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}