// App.jsx — Main app shell with 4-page routing
import { useState } from 'react'
import Global      from './pages/Global'
import Generate    from './pages/Generate'
import Formulas    from './pages/Formulas'
import EvolutionRun from './pages/EvolutionRun'

const PAGES = [
  { id: 'global',   label: 'Overview',    icon: '◈' },
  { id: 'generate', label: 'Generate',    icon: '⊞' },
  { id: 'formulas', label: 'Formulas',    icon: '⌥' },
  { id: 'evolve',   label: 'Evolution',   icon: '⟳' },
]

export default function App() {
  const [page,          setPage]          = useState('global')
  const [pendingFormula,setPendingFormula] = useState(null)  // formula to send from Generate → Formulas
  const [activeRun,     setActiveRun]     = useState(null)   // { formulaId, runId }

  function handleSendToEvolve(formula) {
    setPendingFormula(formula)
    setPage('formulas')
  }

  function handleOpenRun(formulaId, runId) {
    setActiveRun({ formulaId, runId })
    setPage('evolve')
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-mark">
            NBA<span>FE</span>
          </div>
          <div className="sidebar-sub">Formula Evolver</div>
        </div>

        <nav className="sidebar-nav">
          {PAGES.map(p => (
            <button
              key={p.id}
              className={`nav-item${page === p.id ? ' active' : ''}`}
              onClick={() => setPage(p.id)}>
              <span className="nav-icon">{p.icon}</span>
              {p.label}
              {/* Live indicator dots */}
              {p.id === 'evolve' && activeRun && (
                <span style={{
                  marginLeft: 'auto', width: 7, height: 7, borderRadius: '50%',
                  background: 'var(--orange)', display: 'inline-block'
                }} />
              )}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          v2.0 — Layer 7<br/>
          NBA Formula Evolver
        </div>
      </aside>

      <main className="main-content">
        {page === 'global' && (
          <Global onNavigate={setPage} />
        )}
        {page === 'generate' && (
          <Generate onSendToEvolve={handleSendToEvolve} />
        )}
        {page === 'formulas' && (
          <Formulas
            pendingFormula={pendingFormula}
            onOpenRun={handleOpenRun}
          />
        )}
        {page === 'evolve' && (
          <EvolutionRun
            formulaId={activeRun?.formulaId}
            runId={activeRun?.runId}
            onBack={() => setPage('formulas')}
          />
        )}
      </main>
    </div>
  )
}
