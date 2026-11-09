import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { getSession, clearSession, type Session } from './auth'
import HomePage from './pages/HomePage'
import MapPage from './pages/MapPage'
import CountriesPage from './pages/CountriesPage'
import CountryPage from './pages/CountryPage'
import IndicatorsPage from './pages/IndicatorsPage'
import DatasetsPage from './pages/DatasetsPage'
import LoginPage from './pages/LoginPage'
import MapProbePage from './pages/MapProbePage'
import OrganisationsPage from './pages/OrganisationsPage'

const navItem =
  'px-3 py-1.5 rounded-md text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100'

export default function App() {
  const [session, setSessionState] = useState<Session | null>(getSession())

  useEffect(() => {
    const sync = () => setSessionState(getSession())
    window.addEventListener('openaid-auth', sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener('openaid-auth', sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-slate-200 bg-white sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-6">
          <NavLink to="/" className="flex items-baseline gap-2">
            <span className="text-lg font-bold text-blue-700">OpenAid</span>
            <span className="hidden sm:inline text-xs text-slate-500">
              Open data. Stronger communities. Better decisions.
            </span>
          </NavLink>
          <nav className="ml-auto flex items-center gap-1">
            <NavLink to="/" className={navItem} end>Overview</NavLink>
            <NavLink to="/map" className={navItem}>Map</NavLink>
            <NavLink to="/countries" className={navItem}>Countries</NavLink>
            <NavLink to="/indicators" className={navItem}>Indicators</NavLink>
            <NavLink to="/organisations" className={navItem}>Organisations</NavLink>
            <NavLink to="/datasets" className={navItem}>Open Data</NavLink>
            <a
              href="/docs"
              className={navItem}
              target="_blank"
              rel="noreferrer"
            >
              API
            </a>
            {session ? (
              <span className="flex items-center gap-2 pl-2">
                <span className="text-xs text-slate-600">
                  {session.user.username} <span className="text-slate-400">({session.user.role})</span>
                </span>
                <button
                  onClick={() => clearSession()}
                  className="px-2.5 py-1 rounded-md border border-slate-300 text-xs font-medium text-slate-600 hover:bg-slate-100"
                >
                  Sign out
                </button>
              </span>
            ) : (
              <NavLink to="/login" className="px-3 py-1.5 rounded-md text-sm font-semibold text-white bg-blue-700 hover:bg-blue-800">
                Sign in
              </NavLink>
            )}
          </nav>
        </div>
      </header>

      <main className="flex-1">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/countries" element={<CountriesPage />} />
          <Route path="/countries/:iso3" element={<CountryPage />} />
          <Route path="/indicators" element={<IndicatorsPage />} />
          <Route path="/organisations" element={<OrganisationsPage />} />
          <Route path="/datasets" element={<DatasetsPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/map-probe" element={<MapProbePage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-6xl mx-auto px-4 py-6 text-xs text-slate-500 space-y-1">
          <p>
            OpenAid — open-source, Africa-wide community resource & humanitarian
            intelligence platform. Licensed AGPL-3.0. Data licences are recorded
            per source and may differ.
          </p>
          <p>
            Coverage is progressive: countries marked “placeholder” are
            structurally supported but have no validated data onboarded yet.
            Figures without provenance are never shown.
          </p>
        </div>
      </footer>
    </div>
  )
}

function NotFound() {
  return (
    <div className="max-w-6xl mx-auto px-4 py-24 text-center">
      <h1 className="text-2xl font-bold">Page not found</h1>
      <p className="text-slate-500 mt-2">The path you followed does not exist.</p>
    </div>
  )
}
