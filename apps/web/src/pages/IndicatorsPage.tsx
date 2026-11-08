import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type IndicatorDef } from '../api'
import { ErrorBox, Spinner } from '../components'

export default function IndicatorsPage() {
  const [defs, setDefs] = useState<IndicatorDef[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.indicators().then(setDefs).catch((e) => setError(String(e.message)))
  }, [])

  if (error) return <div className="max-w-6xl mx-auto px-4 py-10"><ErrorBox message={error} /></div>
  if (!defs) return <Spinner />

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-xl font-bold">Indicator catalogue</h1>
      <p className="text-sm text-slate-500 mt-1">
        Every indicator stores its definition, unit, measurement type and
        aggregation rule. Comparability is never assumed from similar names —
        assessments are recorded explicitly.
      </p>
      <div className="mt-6 overflow-x-auto border border-slate-200 rounded-lg bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500 uppercase tracking-wide">
            <tr>
              <th className="px-4 py-2.5">Indicator</th>
              <th className="px-4 py-2.5">Category</th>
              <th className="px-4 py-2.5">Unit</th>
              <th className="px-4 py-2.5">Aggregation</th>
              <th className="px-4 py-2.5">Observations</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {defs.map((d) => (
              <tr key={d.id} className="hover:bg-slate-50">
                <td className="px-4 py-2.5">
                  <div className="font-medium">{d.name}</div>
                  <div className="text-xs text-slate-400">{d.code}</div>
                </td>
                <td className="px-4 py-2.5 text-xs">{d.category}</td>
                <td className="px-4 py-2.5 text-xs">{d.unit ?? '—'}</td>
                <td className="px-4 py-2.5 text-xs">{d.aggregation_method}</td>
                <td className="px-4 py-2.5 text-xs">{d.observation_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-4 text-xs text-slate-500">
        Per-country values are shown on each{' '}
        <Link to="/countries" className="text-blue-700 hover:underline">country profile</Link>{' '}
        with source, licence, period and value type.
      </p>
    </div>
  )
}
