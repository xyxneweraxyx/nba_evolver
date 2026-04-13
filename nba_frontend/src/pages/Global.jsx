// pages/Global.jsx — Overview dashboard
import { useState, useEffect } from 'react'
import { apiGet } from '../hooks/useApi'
import { Card, SectionTitle, StatBox, EmptyState, AccBadge, Tag, LiveDot } from '../components/Ui'

export default function Global({ onNavigate }) {
  const [status, setStatus] = useState(null)
  const [info,   setInfo]   = useState(null)

  useEffect(() => {
    const load = async () => {
      try {
        const [s, i] = await Promise.all([
          apiGet('/api/status'),
          apiGet('/api/data/info'),
        ])
        setStatus(s); setInfo(i)
      } catch {}
    }
    load()
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [])

  const exploreStats = status?.explore_stats
  const evolveStats  = status?.evolve_stats
  const totalTrain   = info?.training?.total_games ?? '—'
  const totalTest    = info?.testing?.total_games  ?? '—'
  const trainSeasons = info?.training?.seasons ?? []

  return (
    <div style={{ padding: 32 }}>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 32, letterSpacing: '0.01em' }}>
          NBA Formula Evolver
        </h1>
        <p style={{ color: 'var(--ink-3)', marginTop: 4 }}>
          Genetic Programming for NBA game prediction
        </p>
      </div>

      {/* Engine status */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        {/* Explore engine */}
        <Card>
          <SectionTitle>Exploration Engine</SectionTitle>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, marginBottom: 16 }}>
            <LiveDot active={status?.explore_running} />
            <span style={{ fontWeight: 600 }}>
              {status?.explore_running ? 'Running' : 'Idle'}
            </span>
            {status?.explore_running && (
              <Tag variant="green">LIVE</Tag>
            )}
          </div>
          {exploreStats ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <StatBox label="Generated" value={exploreStats.n_generated?.toLocaleString()} />
              <StatBox label="Saved" value={exploreStats.n_saved?.toLocaleString()} />
              <StatBox label="Speed" value={`${Math.round(exploreStats.formulas_per_s ?? 0)}/s`} />
              <StatBox label="Survival" value={`${((exploreStats.survival_rate ?? 0) * 100).toFixed(1)}%`} />
            </div>
          ) : (
            <p style={{ color: 'var(--ink-4)', fontSize: 13 }}>No data yet. Start exploring.</p>
          )}
          <button className="btn btn-primary" style={{ marginTop: 16, width: '100%' }}
            onClick={() => onNavigate('generate')}>
            Go to Generate →
          </button>
        </Card>

        {/* Evolution engine */}
        <Card>
          <SectionTitle>Evolution Engine</SectionTitle>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, marginBottom: 16 }}>
            <LiveDot active={status?.evolve_running} />
            <span style={{ fontWeight: 600 }}>
              {status?.evolve_running ? 'Running' : 'Idle'}
            </span>
            {status?.evolve_running && <Tag variant="green">LIVE</Tag>}
          </div>
          {evolveStats ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <StatBox label="Mutations tried" value={evolveStats.gen_tried?.toLocaleString()} />
              <StatBox label="Accepted" value={evolveStats.gen_accepted?.toLocaleString()} />
              <StatBox label="Speed" value={`${Math.round(evolveStats.mutations_per_s ?? 0)}/s`} />
              <StatBox label="Best acc" value={<AccBadge value={evolveStats.best_accuracy} />} />
            </div>
          ) : (
            <p style={{ color: 'var(--ink-4)', fontSize: 13 }}>No run started yet.</p>
          )}
          <button className="btn" style={{ marginTop: 16, width: '100%' }}
            onClick={() => onNavigate('formulas')}>
            Go to Formulas →
          </button>
        </Card>
      </div>

      {/* Dataset info */}
      <Card style={{ marginBottom: 24 }}>
        <SectionTitle>Dataset</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginTop: 12 }}>
          <StatBox label="Training games" value={totalTrain.toLocaleString?.() ?? totalTrain} />
          <StatBox label="Testing games"  value={totalTest.toLocaleString?.()  ?? totalTest} />
          <StatBox label="Training seasons" value={trainSeasons.length} />
          <StatBox label="Test seasons"   value={info?.testing?.seasons?.length ?? '—'} />
        </div>
        {trainSeasons.length > 0 && (
          <div style={{ marginTop: 12, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {trainSeasons.map(s => <Tag key={s} variant="blue">{s}</Tag>)}
            {(info?.testing?.seasons ?? []).map(s => <Tag key={s} variant="gold">{s} test</Tag>)}
          </div>
        )}
      </Card>

      {/* Quick start guide */}
      <Card>
        <SectionTitle>Getting started</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginTop: 16 }}>
          {[
            { n: '1', title: 'Generate formulas', desc: 'Run the exploration engine to generate thousands of random formulas and keep the most interesting ones.', page: 'generate', btn: 'Open Generate' },
            { n: '2', title: 'Pick a formula', desc: 'Browse generated formulas by interest score. Save the ones you want to evolve further.', page: 'formulas', btn: 'Open Formulas' },
            { n: '3', title: 'Evolve it', desc: 'Create an evolution run on a saved formula. Configure mutation strength, direction, threshold.', page: 'formulas', btn: 'Open Evolution' },
          ].map(step => (
            <div key={step.n} style={{
              background: 'var(--bg-subtle)',
              borderRadius: 'var(--radius)',
              padding: 16,
            }}>
              <div style={{ fontFamily: 'var(--font-display)', fontWeight: 800, fontSize: 32, color: 'var(--orange)', lineHeight: 1, marginBottom: 8 }}>{step.n}</div>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>{step.title}</div>
              <div style={{ color: 'var(--ink-3)', fontSize: 13, marginBottom: 12 }}>{step.desc}</div>
              <button className="btn" style={{ fontSize: 12 }} onClick={() => onNavigate(step.page)}>{step.btn}</button>
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
