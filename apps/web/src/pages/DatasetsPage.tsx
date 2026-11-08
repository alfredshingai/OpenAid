import { useEffect, useState } from 'react'
import { api, type Dataset } from '../api'
import { ErrorBox, Spinner } from '../components'

export default function DatasetsPage() {
  const [datasets, setDatasets] = useState<Dataset[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.datasets().then(setDatasets).catch((e) => setError(String(e.message)))
  }, [])

  if (error) return <div className="max-w-6xl mx-auto px-4 py-10"><ErrorBox message={error} /></div>
  if (!datasets) return <Spinner />

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-xl font-bold">Open data catalogue</h1>
      <p className="text-sm text-slate-500 mt-1">
        Publisher, licence, attribution and access classification are recorded
        for every dataset. Access class (who may view) is separate from the
        reuse licence (what you may do).
      </p>
      <div className="mt-6 grid md:grid-cols-2 gap-4">
        {datasets.map((d) => (
          <div key={d.id} className="border border-slate-200 rounded-lg bg-white p-4">
            <div className="flex items-start justify-between gap-2">
              <h2 className="font-semibold text-sm">{d.title}</h2>
              <span className="inline-block bg-emerald-50 text-emerald-700 border border-emerald-200 rounded px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap">
                {d.access_class}
              </span>
            </div>
            <p className="mt-2 text-xs text-slate-600 leading-snug">{d.description}</p>
            <p className="mt-2 text-[11px] text-slate-500">
              Publisher: {d.publisher}
              <br />
              Licence: <b>{d.licence}</b>
            </p>
            {d.attribution && (
              <p className="mt-1 text-[11px] text-slate-400">Attribution: {d.attribution}</p>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {d.files.map((f, i) => (
                <span key={i} className="text-[11px] bg-slate-100 border border-slate-200 rounded px-1.5 py-0.5">
                  {f.filename}
                  {f.layer ? `:${f.layer}` : ''} ({f.format})
                </span>
              ))}
            </div>
            {d.homepage_url && (
              <a
                href={d.homepage_url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-xs text-blue-700 hover:underline"
              >
                Source bundle ↗
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
