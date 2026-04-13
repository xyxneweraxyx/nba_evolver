// pages/Stats.jsx — Variable reference page
import { useState, useEffect, useMemo } from 'react'
import { apiGet } from '../hooks/useApi'
import { Card, SectionTitle, Tag, EmptyState } from '../components/Ui'

const TIER_LABEL = { 1: 'High signal', 2: 'Medium', 3: 'Low / contextual' }
const TIER_COLOR = { 1: 'var(--green)', 2: 'var(--orange)', 3: 'var(--ink-4)' }

const CAT_ORDER = [
  'binary','context','season_stats','last10_stats','last5_stats',
  'home_stats','away_stats','b2b_stats','vs_above500_stats',
  'q1_stats','q4_stats','clutch_stats','player',
]

export default function Stats() {
  const [data,      setData]      = useState(null)
  const [search,    setSearch]    = useState('')
  const [catFilter, setCatFilter] = useState('all')
  const [tierFilter,setTierFilter]= useState('all')
  const [expanded,  setExpanded]  = useState(null)

  useEffect(() => {
    apiGet('/api/data/variables').then(setData).catch(() => {})
  }, [])

  const variables = useMemo(() => {
    if (!data?.variables) return []
    let v = data.variables

    if (catFilter !== 'all')
      v = v.filter(x => x.cat === catFilter)

    if (tierFilter !== 'all')
      v = v.filter(x => x.tier === +tierFilter)

    if (search.trim()) {
      const q = search.toLowerCase()
      v = v.filter(x =>
        x.name.toLowerCase().includes(q) ||
        x.desc.toLowerCase().includes(q) ||
        x.unit?.toLowerCase().includes(q)
      )
    }

    return v
  }, [data, search, catFilter, tierFilter])

  const cats  = data?.categories ?? {}
  const total = data?.variables?.length ?? 0

  // Group by category for display
  const grouped = useMemo(() => {
    const g = {}
    for (const v of variables) {
      const c = v.cat
      if (!g[c]) g[c] = []
      g[c].push(v)
    }
    // Sort by CAT_ORDER
    return CAT_ORDER
      .filter(c => g[c]?.length > 0)
      .map(c => ({ cat: c, vars: g[c], meta: cats[c] }))
  }, [variables, cats])

  if (!data) {
    return (
      <div style={{ padding: 32 }}>
        <EmptyState icon="⟳" title="Loading variables..." sub="" />
      </div>
    )
  }

  return (
    <div style={{ padding: 32 }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 28, marginBottom: 6 }}>
          Variable Reference
        </h2>
        <p style={{ color: 'var(--ink-3)', fontSize: 14 }}>
          {total} variables available to the formula engine.
          Each variable is evaluated independently for home and away teams — the formula receives <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--bg-subtle)', padding: '1px 5px', borderRadius: 3 }}>home[i] - away[i]</code> as its raw signal.
        </p>
      </div>

      {/* Filters */}
      <Card style={{ marginBottom: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 12, alignItems: 'center' }}>
          {/* Search */}
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by name, description, unit..."
            style={{
              padding: '8px 14px', borderRadius: 'var(--radius)',
              border: '1px solid var(--border)', fontSize: 13,
              fontFamily: 'var(--font-mono)', background: 'var(--bg-subtle)',
              color: 'var(--ink)', outline: 'none', width: '100%',
            }}
          />

          {/* Category filter */}
          <select value={catFilter} onChange={e => setCatFilter(e.target.value)}
            style={{ padding: '8px 12px', borderRadius: 'var(--radius)',
              border: '1px solid var(--border)', fontSize: 12,
              fontFamily: 'var(--font-mono)', background: 'var(--bg-card)', cursor: 'pointer' }}>
            <option value="all">All categories</option>
            {CAT_ORDER.map(c => (
              <option key={c} value={c}>{cats[c]?.label ?? c}</option>
            ))}
          </select>

          {/* Tier filter */}
          <select value={tierFilter} onChange={e => setTierFilter(e.target.value)}
            style={{ padding: '8px 12px', borderRadius: 'var(--radius)',
              border: '1px solid var(--border)', fontSize: 12,
              fontFamily: 'var(--font-mono)', background: 'var(--bg-card)', cursor: 'pointer' }}>
            <option value="all">All tiers</option>
            <option value="1">Tier 1 — High signal</option>
            <option value="2">Tier 2 — Medium</option>
            <option value="3">Tier 3 — Contextual</option>
          </select>
        </div>

        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--ink-4)', fontFamily: 'var(--font-mono)' }}>
          Showing {variables.length} / {total} variables
        </div>
      </Card>

      {/* Tier legend */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
        {[1,2,3].map(t => (
          <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: TIER_COLOR[t] }} />
            <span style={{ color: 'var(--ink-3)' }}>Tier {t} — {TIER_LABEL[t]}</span>
          </div>
        ))}
        <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--ink-4)' }}>
          Click any variable to see its index
        </div>
      </div>

      {/* Variables grouped by category */}
      {grouped.length === 0 ? (
        <EmptyState icon="◈" title="No variables found"
          sub="Try a different search term or category." />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {grouped.map(({ cat, vars, meta }) => (
            <div key={cat}>
              {/* Category header */}
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                marginBottom: 10,
              }}>
                <div style={{
                  width: 4, height: 20, borderRadius: 2,
                  background: meta?.color ?? 'var(--orange)',
                }} />
                <h3 style={{ fontFamily: 'var(--font-display)', fontWeight: 700, fontSize: 18 }}>
                  {meta?.label ?? cat}
                </h3>
                <span style={{ color: 'var(--ink-4)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
                  {vars.length} variable{vars.length !== 1 ? 's' : ''}
                </span>
              </div>

              {/* Variable table */}
              <div style={{
                background: 'var(--bg-card)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-lg)', overflow: 'hidden',
              }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ background: 'var(--bg-subtle)', borderBottom: '2px solid var(--border)' }}>
                      {['', 'Variable name', 'Description', 'Unit', 'Typical range'].map(h => (
                        <th key={h} style={{
                          padding: '8px 14px', textAlign: 'left',
                          fontFamily: 'var(--font-mono)', fontSize: 10,
                          textTransform: 'uppercase', letterSpacing: '0.07em',
                          color: 'var(--ink-3)', fontWeight: 500,
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {vars.map((v, i) => (
                      <>
                        <tr key={v.name}
                          onClick={() => setExpanded(expanded === v.name ? null : v.name)}
                          style={{
                            borderBottom: i < vars.length - 1 ? '1px solid var(--border)' : 'none',
                            background:   expanded === v.name ? 'var(--orange-dim)' : 'transparent',
                            cursor: 'pointer',
                          }}>
                          {/* Tier dot */}
                          <td style={{ padding: '8px 8px 8px 14px', width: 20 }}>
                            <div style={{
                              width: 7, height: 7, borderRadius: '50%',
                              background: TIER_COLOR[v.tier],
                            }} />
                          </td>
                          {/* Name */}
                          <td style={{ padding: '8px 14px', fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600, whiteSpace: 'nowrap' }}>
                            {v.name.split('.').pop()}
                            <span style={{ color: 'var(--ink-4)', fontSize: 10, fontWeight: 400, display: 'block' }}>
                              {v.name}
                            </span>
                          </td>
                          {/* Description */}
                          <td style={{ padding: '8px 14px', fontSize: 13, color: 'var(--ink-2)', maxWidth: 400 }}>
                            {v.desc.replace(/^\[.*?\]\s*/, '')}
                          </td>
                          {/* Unit */}
                          <td style={{ padding: '8px 14px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)', whiteSpace: 'nowrap' }}>
                            {v.unit || '—'}
                          </td>
                          {/* Range */}
                          <td style={{ padding: '8px 14px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)', whiteSpace: 'nowrap' }}>
                            {v.range ? `${v.range[0]} – ${v.range[1]}` : '—'}
                          </td>
                        </tr>

                        {/* Expanded row */}
                        {expanded === v.name && (
                          <tr key={`${v.name}-exp`}>
                            <td colSpan={5} style={{ padding: '10px 14px 14px 38px', background: 'var(--orange-dim)', borderBottom: '1px solid var(--border)' }}>
                              <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                                <div>
                                  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 }}>Registry index</div>
                                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: 'var(--orange)' }}>{v.index}</div>
                                </div>
                                <div>
                                  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 }}>Signal tier</div>
                                  <div style={{ fontSize: 13, fontWeight: 600, color: TIER_COLOR[v.tier] }}>
                                    Tier {v.tier} — {TIER_LABEL[v.tier]}
                                  </div>
                                </div>
                                <div>
                                  <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 }}>Use in formula</div>
                                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-2)', background: 'var(--bg-card)', padding: '3px 8px', borderRadius: 4 }}>
                                    LOAD {v.index}  <span style={{ color: 'var(--ink-4)' }}>← {v.name}</span>
                                  </div>
                                </div>
                                {v.range && (
                                  <div>
                                    <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--ink-4)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 }}>Typical NBA range</div>
                                    <div style={{ fontSize: 13 }}>{v.range[0]} → {v.range[1]} {v.unit}</div>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}