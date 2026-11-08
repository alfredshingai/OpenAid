import type { Observation } from './api'

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return <p className="text-slate-500 text-sm py-8 text-center">{label}</p>
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="bg-red-50 border border-red-200 text-red-800 rounded-md p-4 text-sm">
      {message}
    </div>
  )
}

export function StatusChip({ status }: { status: string }) {
  const style =
    status === 'active'
      ? 'bg-green-100 text-green-800 border-green-200'
      : 'bg-slate-100 text-slate-600 border-slate-200'
  return (
    <span className={`inline-block border rounded px-2 py-0.5 text-xs font-medium ${style}`}>
      {status}
    </span>
  )
}

/** Human label for value types (blueprint: observed vs estimated vs modelled). */
export function ValueTypeBadge({ type }: { type: Observation['value_type'] }) {
  const style =
    type === 'observed'
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : type === 'modelled'
        ? 'bg-amber-50 text-amber-700 border-amber-200'
        : 'bg-sky-50 text-sky-700 border-sky-200'
  return (
    <span className={`inline-block border rounded px-1.5 py-0.5 text-[11px] font-medium ${style}`}>
      {type}
    </span>
  )
}

/** Renders a number with its unit and provenance line — no naked figures. */
export function ObservationCard({ obs }: { obs: Observation }) {
  const missing = obs.value === null
  return (
    <div className="border border-slate-200 rounded-lg p-4 bg-white">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold text-sm text-slate-800">{obs.indicator_name}</h3>
        <ValueTypeBadge type={obs.value_type} />
      </div>
      {missing ? (
        <p className="mt-2 text-sm text-slate-500">
          No value — recorded as <em>{obs.missing_type ?? 'unknown'}</em>. Missing values are
          never shown as zero.
        </p>
      ) : (
        <p className="mt-2 text-2xl font-bold text-slate-900">
          {formatNumber(obs.value!)}{' '}
          <span className="text-sm font-normal text-slate-500">{obs.unit_label}</span>
        </p>
      )}
      <p className="mt-2 text-[11px] text-slate-500 leading-snug">
        {obs.period_start.slice(0, 4)} · {obs.source} ({obs.source_licence}) · v
        {obs.dataset_version} · {obs.value_type}
      </p>
      {obs.methodology_notes && (
        <p className="mt-1 text-[11px] text-slate-400 leading-snug">{obs.methodology_notes}</p>
      )}
    </div>
  )
}

export function formatNumber(n: number): string {
  if (Math.abs(n) >= 1000) return n.toLocaleString('en-US', { maximumFractionDigits: 1 })
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 })
}
