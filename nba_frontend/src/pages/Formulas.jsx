// pages/Formulas.jsx
import { useState, useEffect } from 'react'
import { apiGet, apiPost } from '../hooks/useApi'
import { Card, SectionTitle, Slider, Tag, EmptyState, AccBadge, IntBadge } from '../components/Ui'

const INTEREST_LABELS = {
  0:'50/50',5:'52.5%+',10:'55%+',15:'57.5%+',20:'60%+',
  25:'62.5%+',30:'65%+',35:'67.5%+',40:'70%+',45:'72.5%+',50:'75%+',
}
function interestLabel(v) {
  return INTEREST_LABELS[Math.round(v/5)*5] ?? `${v}%`
}

const DEFAULT_EVOL = {
  mutation_strength: 0.5, attempts_per_gen: 5,
  min_improvement: 0.0005, eval_block_size: 300,
  stagnation_limit: 0, max_generations: 0,
  direction: 'up',
  max_tree_size: 80, max_tree_depth: 8,
}
const GEN_PAGE = 30


// ── SidePanel extracted as top-level component to prevent re-mount on slider drag ──
function EvolutionSidePanel({ evCfg, setEvCfg, showNew, setShowNew, contMode, contTarget,
  startNode, startLabel, starting, error, onStartRun }) {
  function set(k) { return v => setEvCfg(c => ({...c, [k]: v})) }
  const pct  = v => `${(v*100).toFixed(2)}%`
  const pct2 = v => `${Math.round(v*100)}%`

  return (
    <div className="train-panel" style={{ position:'sticky', top:24 }}>
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:20 }}>
        <SectionTitle style={{ color:'rgba(255,255,255,0.5)' }}>
          {contMode ? 'Continue Run' : 'New Evolution Run'}
        </SectionTitle>
        <button onClick={() => setShowNew(false)}
          style={{ background:'none', border:'none', color:'rgba(255,255,255,0.4)', cursor:'pointer', fontSize:18 }}>✕</button>
      </div>

      {/* Source info */}
      <div style={{ background:'rgba(255,255,255,0.06)', borderRadius:'var(--radius)', padding:'10px 14px', marginBottom:20 }}>
        <div style={{ fontSize:10, fontFamily:'var(--font-mono)', color:'rgba(255,255,255,0.4)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:4 }}>
          {contMode ? 'Continuing from' : 'Starting formula'}
        </div>
        <div style={{ color:'var(--orange-2)', fontSize:11, fontFamily:'var(--font-mono)' }}>
          {contMode
            ? `↻ ${contTarget?.fid} / ${contTarget?.rid}`
            : startNode
              ? `⊕ ${startLabel || 'Formula loaded ✓'}`
              : <span style={{ color:'rgba(255,255,255,0.3)' }}>Click "Evolve →" to select</span>
          }
        </div>
      </div>

      {/* Direction */}
      <div style={{ marginBottom:16 }}>
        <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:8 }}>Direction</div>
        <div style={{ display:'flex', gap:8 }}>
          {['up','down'].map(d => (
            <button key={d} onClick={() => set('direction')(d)} style={{
              flex:1, padding:'8px 0', borderRadius:'var(--radius)', fontSize:12,
              fontFamily:'var(--font-mono)', cursor:'pointer', border:'1px solid',
              background:  evCfg.direction===d ? 'var(--orange)' : 'rgba(255,255,255,0.05)',
              borderColor: evCfg.direction===d ? 'var(--orange)' : 'rgba(255,255,255,0.12)',
              color:       evCfg.direction===d ? '#fff'          : 'rgba(255,255,255,0.5)',
            }}>{d==='up' ? '▲ Maximize' : '▼ Minimize'}</button>
          ))}
        </div>
      </div>

      {/* Mutation */}
      <div style={{ marginBottom:4 }}>
        <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>Mutation</div>
        <div className="slider-row" style={{ gridTemplateColumns:'1fr 1fr' }}>
          <Slider label="Strength"     value={evCfg.mutation_strength} min={0.1} max={1.0} step={0.1} onChange={set('mutation_strength')} format={pct2} />
          <Slider label="Attempts/gen" value={evCfg.attempts_per_gen}  min={1}   max={30}  step={1}   onChange={set('attempts_per_gen')} />
        </div>
      </div>

      {/* Evaluation */}
      <div style={{ marginBottom:4 }}>
        <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>Evaluation</div>
        <div className="slider-row" style={{ gridTemplateColumns:'1fr 1fr' }}>
          <Slider label="Block size"      value={evCfg.eval_block_size}  min={100} max={2000} step={100}    onChange={set('eval_block_size')} />
          <Slider label="Min improvement" value={evCfg.min_improvement}  min={0.0001} max={0.005} step={0.0001} onChange={set('min_improvement')} format={pct} />
        </div>
      </div>

      {/* Tree limits */}
      <div style={{ marginBottom:4 }}>
        <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>Tree size limits</div>
        <div className="slider-row" style={{ gridTemplateColumns:'1fr 1fr' }}>
          <Slider label="Max nodes (0=∞)" value={evCfg.max_tree_size}  min={0} max={200} step={10} onChange={set('max_tree_size')} />
          <Slider label="Max depth (0=∞)" value={evCfg.max_tree_depth} min={0} max={16}  step={1}  onChange={set('max_tree_depth')} />
        </div>
      </div>

      {/* Stop conditions */}
      <div style={{ marginBottom:20 }}>
        <div style={{ color:'rgba(255,255,255,0.35)', fontSize:10, fontFamily:'var(--font-mono)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:10 }}>Stop conditions</div>
        <div className="slider-row" style={{ gridTemplateColumns:'1fr 1fr' }}>
          <Slider label="Stagnation (0=∞)"  value={evCfg.stagnation_limit}  min={0} max={500} step={10} onChange={set('stagnation_limit')} />
          <Slider label="Max gen (0=∞)"     value={evCfg.max_generations}   min={0} max={1000} step={50} onChange={set('max_generations')} />
        </div>
      </div>

      {error && <div style={{ background:'var(--red-dim)', color:'var(--red)', padding:'8px 12px', borderRadius:'var(--radius)', fontSize:12, marginBottom:12 }}>{error}</div>}

      <button className="btn btn-primary" style={{ width:'100%', padding:12 }}
        disabled={(!startNode && !contMode) || starting} onClick={onStartRun}>
        {starting ? '...' : contMode ? '↻ Continue Run' : '▶ Start Evolution Run'}
      </button>
    </div>
  )
}

export default function Formulas({ pendingFormula, onOpenRun }) {
  const [tab,       setTab]      = useState('evolved')
  const [formulas,  setFormulas] = useState([])
  const [selected,  setSelected] = useState(null)
  const [batches,   setBatches]  = useState([])
  const [curBatch,  setCurBatch] = useState('')
  const [genForms,  setGenForms] = useState([])
  const [genPage,   setGenPage]  = useState(0)
  const [expanded,  setExpanded] = useState(null)  // expanded gen formula
  const [showNew,   setShowNew]  = useState(false)
  const [evCfg,     setEvCfg]    = useState(DEFAULT_EVOL)
  const [startNode, setStartNode]= useState(null)
  const [startLabel,setStartLabel]=useState('')
  const [starting,  setStarting] = useState(false)
  const [contMode,  setContMode] = useState(false) // continue vs new run
  const [contTarget,setContTarget]=useState(null)  // {fid, rid}
  const [error,     setError]    = useState(null)

  useEffect(() => { loadFormulas(); loadBatches() }, [])

  useEffect(() => {
    if (!pendingFormula) return
    setStartNode(pendingFormula.tree)
    setStartLabel(`From Generate: ${pendingFormula.id}`)
    setContMode(false)
    setShowNew(true); setTab('evolved')
  }, [pendingFormula])

  async function loadFormulas() {
    try { setFormulas(await apiGet('/api/formulas')) } catch {}
  }

  async function loadBatches() {
    try {
      const data = await apiGet('/api/explore/batches')
      setBatches(data)
      if (data.length > 0) {
        const latest = data[data.length-1].name
        setCurBatch(latest); loadGen(latest, 0)
      }
    } catch {}
  }

  async function loadGen(batch, pg) {
    try {
      const data = await apiGet(`/api/explore/batch/${batch}?offset=${pg*GEN_PAGE}&limit=${GEN_PAGE}`)
      setGenForms(data)
    } catch {}
  }

  async function expandFormula(fid) {
    try {
      const runs = await apiGet(`/api/evolve/${fid}/runs`)
      setSelected(s => s?.formula_id===fid ? null : { formula_id: fid, runs })
    } catch {}
  }

  function set(k) { return v => setEvCfg(c => ({...c, [k]: v})) }
  const pct  = v => `${(v*100).toFixed(2)}%`
  const pct2 = v => `${Math.round(v*100)}%`

  async function handleStartRun() {
    if (!startNode && !contMode) { setError('No formula selected'); return }
    setStarting(true); setError(null)

    try {
      if (contMode && contTarget) {
        // Continue existing run
        const res = await apiPost('/api/evolve/start', {
          formula_id: contTarget.fid,
          run_id:     contTarget.rid,
          continue:   true,
          config:     evCfg,
        })
        setShowNew(false); setStarting(false)
        await loadFormulas()
        onOpenRun(contTarget.fid, res.run_id ?? contTarget.rid)
      } else {
        // New run
        const fid = selected?.formula_id ?? `gen_${Date.now()}`
        const res = await apiPost('/api/evolve/start', {
          formula_id: fid, tree: startNode, config: evCfg,
        })
        setShowNew(false); setStarting(false)
        await loadFormulas()
        onOpenRun(fid, res.run_id)
      }
    } catch (e) { setError(e.message); setStarting(false) }
  }


  return (
    <div style={{ padding:32, display:'grid', gridTemplateColumns:'1fr 380px', gap:20, alignItems:'start' }}>
      <div>
        {/* Header */}
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:16 }}>
          <h2 style={{ fontFamily:'var(--font-display)', fontWeight:700, fontSize:22 }}>Formulas</h2>
          <div style={{ display:'flex', gap:8 }}>
            <button className="btn" onClick={() => { loadFormulas(); loadBatches() }}>↻ Refresh</button>
            <button className="btn btn-primary"
              onClick={() => { setContMode(false); setStartNode(null); setStartLabel(''); setShowNew(true) }}>
              + New Run
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="tabs">
          <button className={`tab ${tab==='evolved'?'active':''}`} onClick={() => setTab('evolved')}>
            Evolved ({formulas.length})
          </button>
          <button className={`tab ${tab==='generated'?'active':''}`} onClick={() => setTab('generated')}>
            Generated ({batches.reduce((s,b) => s+b.n_formulas, 0)})
          </button>
        </div>

        {/* ── Evolved tab ── */}
        {tab === 'evolved' && (
          formulas.length === 0
            ? <EmptyState icon="⌥" title="No evolved formulas yet" sub="Pick a generated formula and click 'Evolve →'." />
            : <div style={{ display:'flex', flexDirection:'column', gap:8 }}>
                {formulas.map(f => (
                  <div key={f.formula_id}>
                    <div onClick={() => expandFormula(f.formula_id)} style={{
                      background: selected?.formula_id===f.formula_id ? 'var(--bg-subtle)' : 'var(--bg-card)',
                      border: `1px solid ${selected?.formula_id===f.formula_id ? 'var(--orange)' : 'var(--border)'}`,
                      borderRadius: 'var(--radius)', padding:'12px 16px', cursor:'pointer',
                      display:'flex', justifyContent:'space-between', alignItems:'center',
                    }}>
                      <div>
                        <div style={{ fontFamily:'var(--font-mono)', fontSize:12, fontWeight:600 }}>{f.formula_id}</div>
                        <div style={{ fontSize:12, color:'var(--ink-3)', marginTop:2 }}>
                          {f.runs?.length ?? 0} run{(f.runs?.length??0)!==1?'s':''}
                        </div>
                      </div>
                      <div style={{ display:'flex', gap:8, alignItems:'center' }}>
                        {f.runs?.length > 0 && (
                          <AccBadge value={f.runs.reduce((b,r) => (r.best_accuracy??0)>b?(r.best_accuracy??0):b, 0)||null} />
                        )}
                        <button className="btn btn-primary" style={{ fontSize:11 }}
                          onClick={e => { e.stopPropagation(); onOpenRun(f.formula_id, f.runs?.[f.runs.length-1]?.run_id) }}>
                          View →
                        </button>
                      </div>
                    </div>

                    {/* Expanded runs */}
                    {selected?.formula_id === f.formula_id && (selected.runs??[]).map(r => (
                      <div key={r.run_id} style={{
                        marginLeft:16, marginTop:4, background:'var(--bg-card)',
                        border:'1px solid var(--border)', borderRadius:'var(--radius)',
                        padding:'8px 14px', display:'flex', justifyContent:'space-between', alignItems:'center',
                      }}>
                        <div>
                          <span style={{ fontFamily:'var(--font-mono)', fontSize:11 }}>{r.run_id}</span>
                          <span style={{ color:'var(--ink-4)', fontSize:11, marginLeft:8 }}>{r.n_accepted} accepted</span>
                        </div>
                        <div style={{ display:'flex', gap:6, alignItems:'center' }}>
                          <AccBadge value={r.best_accuracy} />
                          <button className="btn" style={{ fontSize:11 }}
                            onClick={() => onOpenRun(f.formula_id, r.run_id)}>Open →</button>
                          <button className="btn" style={{ fontSize:11 }}
                            onClick={() => {
                              setContMode(true)
                              setContTarget({ fid: f.formula_id, rid: r.run_id })
                              setStartNode(null)
                              setShowNew(true)
                            }}>
                            Continue ↻
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
        )}

        {/* ── Generated tab ── */}
        {tab === 'generated' && (
          <div>
            {batches.length > 0 && (
              <div style={{ display:'flex', gap:8, marginBottom:12, alignItems:'center' }}>
                <select value={curBatch}
                  onChange={e => { setCurBatch(e.target.value); setGenPage(0); loadGen(e.target.value, 0) }}
                  style={{ padding:'6px 10px', borderRadius:'var(--radius)', border:'1px solid var(--border)',
                    fontSize:12, fontFamily:'var(--font-mono)', background:'var(--bg-card)', cursor:'pointer' }}>
                  {batches.map(b => <option key={b.name} value={b.name}>{b.name} ({b.n_formulas})</option>)}
                </select>
                <button className="btn" style={{fontSize:11}} disabled={genPage===0}
                  onClick={() => { setGenPage(p=>p-1); loadGen(curBatch, genPage-1) }}>←</button>
                <span style={{ padding:'6px 10px', fontSize:12, color:'var(--ink-3)' }}>p.{genPage+1}</span>
                <button className="btn" style={{fontSize:11}} disabled={genForms.length<GEN_PAGE}
                  onClick={() => { setGenPage(p=>p+1); loadGen(curBatch, genPage+1) }}>→</button>
              </div>
            )}
            {genForms.length === 0
              ? <EmptyState icon="◈" title="No generated formulas" sub="Run exploration in Generate." />
              : <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
                  {genForms.map(rec => (
                    <div key={rec.id} style={{ display:'flex', flexDirection:'column' }}>
                      <div style={{
                        background: expanded===rec.id ? 'var(--orange-dim)' : 'var(--bg-card)',
                        border: `1px solid ${expanded===rec.id ? 'var(--orange)' : 'var(--border)'}`,
                        borderRadius: expanded===rec.id ? 'var(--radius) var(--radius) 0 0' : 'var(--radius)',
                        padding:'10px 14px', cursor:'pointer',
                        display:'grid', gridTemplateColumns:'1fr auto auto auto auto', gap:10, alignItems:'center',
                      }} onClick={() => setExpanded(expanded===rec.id ? null : rec.id)}>
                        <div>
                          <div style={{ fontFamily:'var(--font-mono)', fontSize:10, color:'var(--ink-4)', marginBottom:2 }}>{rec.id}</div>
                          <div style={{ fontFamily:'var(--font-mono)', fontSize:11, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:360 }}>
                            {rec.repr}
                          </div>
                        </div>
                        <div style={{ textAlign:'center' }}>
                          <div style={{ fontSize:9, color:'var(--ink-4)', marginBottom:2 }}>INT</div>
                          <IntBadge value={rec.score?.interest} />
                        </div>
                        <div style={{ textAlign:'center' }}>
                          <div style={{ fontSize:9, color:'var(--ink-4)', marginBottom:2 }}>ACC</div>
                          <AccBadge value={rec.score?.accuracy} />
                        </div>
                        <Tag variant={rec.score?.direction===1?'green':'orange'}>
                          {rec.score?.direction===1?'GOOD':'BAD'}
                        </Tag>
                        <button className="btn btn-primary" style={{ fontSize:11 }}
                          onClick={e => {
                            e.stopPropagation()
                            setStartNode(rec.tree); setStartLabel(rec.id)
                            setContMode(false); setShowNew(true); setTab('evolved')
                          }}>
                          Evolve →
                        </button>
                      </div>

                      {/* Full formula expanded */}
                      {expanded === rec.id && (
                        <div style={{
                          background:'var(--bg-subtle)', border:`1px solid var(--orange)`,
                          borderTop:'none', borderRadius:'0 0 var(--radius) var(--radius)',
                          padding:'14px 16px',
                        }}>
                          <div style={{ display:'flex', gap:6, marginBottom:8, flexWrap:'wrap' }}>
                            <Tag variant="orange">size: {rec.tree_size}</Tag>
                            <Tag variant="blue">depth: {rec.tree_depth}</Tag>
                            {(rec.vars??[]).map(v => <Tag key={v} variant="gold">{v.split('.').pop()}</Tag>)}
                          </div>
                          <div style={{ fontFamily:'var(--font-mono)', fontSize:12, lineHeight:1.9,
                            background:'var(--bg-card)', borderRadius:'var(--radius)', padding:'12px 14px',
                            overflowX:'auto', whiteSpace:'pre-wrap', wordBreak:'break-all' }}>
                            {rec.repr}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
            }
          </div>
        )}
      </div>

      {showNew && <EvolutionSidePanel evCfg={evCfg} setEvCfg={setEvCfg} showNew={showNew} setShowNew={setShowNew} contMode={contMode} contTarget={contTarget} startNode={startNode} startLabel={startLabel} starting={starting} error={error} onStartRun={handleStartRun} />}
    </div>
  )
}
