import { useEffect, useState } from 'react'
import { request } from '../api'
import { ErrorBox, Spinner } from '../components'

interface OrgList {
  total: number
  organisations: {
    id: string
    name: string
    acronym: string | null
    org_type: string
    website: string | null
    verification_status: string
    location_count: number
  }[]
}

/** Organisation registry. Ships empty by design: organisations are entered
 * only with source evidence, and their presence (HQ vs office vs operations)
 * is stored as separate dated facts. */
export default function OrganisationsPage() {
  const [data, setData] = useState<OrgList | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    request<OrgList>('/api/v1/organisations').then(setData).catch((e: Error) => setError(String(e.message)))
  }, [])

  if (error) return <div className="max-w-6xl mx-auto px-4 py-10"><ErrorBox message={error} /></div>
  if (!data) return <Spinner />

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-xl font-bold">Organisations</h1>
      <p className="text-sm text-slate-500 mt-1">
        NGOs, UN agencies, government bodies, community-based organisations and
        other actors — with their presence recorded as separate, dated,
        source-backed facts.
      </p>

      {data.total === 0 ? (
        <div className="mt-8 border border-slate-200 rounded-lg bg-white p-8 text-center">
          <p className="text-3xl">🗂️</p>
          <p className="mt-3 font-semibold text-slate-800">
            The registry is intentionally empty right now
          </p>
          <p className="mt-2 text-sm text-slate-500 max-w-xl mx-auto">
            OpenAid does not pre-fill organisations without evidence. Every
            entry requires a verifiable source, and a headquarters or
            registration record is never presented as current operations.
            Contributions go through the review workflow.
          </p>
        </div>
      ) : (
        <div className="mt-6 grid md:grid-cols-2 gap-3">
          {data.organisations.map((o) => (
            <div key={o.id} className="border border-slate-200 rounded-lg p-4 bg-white">
              <div className="font-semibold">
                {o.name}
                {o.acronym && <span className="text-slate-400 font-normal"> ({o.acronym})</span>}
              </div>
              <div className="text-xs text-slate-500 mt-1">
                {o.org_type} · {o.location_count} recorded presence facts ·{' '}
                {o.verification_status}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
