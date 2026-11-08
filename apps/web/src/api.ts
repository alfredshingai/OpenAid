import type { FeatureCollection } from 'geojson'
// Typed client for the OpenAid public API (see /api/v1 OpenAPI schema).

export interface AdminLevel {
  level_number: number
  level_name: string
  description: string | null
  unit_count: number
}

export interface Country {
  id: string
  iso2: string
  iso3: string
  name: string
  official_name: string | null
  capital: string | null
  region: string | null
  rep_lon: number | null
  rep_lat: number | null
  status: 'active' | 'placeholder'
  levels: AdminLevel[]
  total_units: number
  max_level: number
}

export interface Unit {
  id: string
  name: string
  official_code: string
  country_iso3: string
  level_number: number
  level_name: string
  parent_unit_id: string | null
  parent_code: string | null
  reference_date: string | null
  verification_status: string
  source_unit_id: string | null
}

export interface Observation {
  id: string
  indicator: string
  indicator_name: string
  unit_label: string | null
  category: string
  period_start: string
  period_end: string | null
  value: number | null
  missing_type: string | null
  value_type: 'observed' | 'estimated' | 'modelled'
  sample_size: number | null
  source: string | null
  source_licence: string | null
  dataset_version: string | null
  methodology: string | null
  methodology_notes: string | null
  unit?: { id: string; official_code: string; name: string; level_number: number; level_name: string }
}

export interface IndicatorDef {
  id: string
  code: string
  name: string
  description: string | null
  category: string
  unit: string | null
  measurement_type: string
  aggregation_method: string
  methodology: string | null
  observation_count: number
}

export interface Facility {
  id: string
  name: string
  facility_type: string
  facility_type_label: string
  operational_status: string
  reference_date: string | null
  source: string | null
  verification_status: string
  properties: Record<string, unknown> | null
  lon?: number
  lat?: number
  unit?: { id: string; official_code: string | null; name: string | null }
}

export interface Dataset {
  id: string
  slug: string
  title: string
  description: string | null
  publisher: string | null
  licence: string | null
  attribution: string | null
  access_class: string
  language: string | null
  spatial_coverage: Record<string, unknown> | null
  temporal_coverage: Record<string, unknown> | null
  homepage_url: string | null
  is_synthetic: boolean
  files: { filename: string; format: string; layer: string | null }[]
  versions: { version_number: string; changelog: string | null; source_version: string | null }[]
}

async function request<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`API ${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  countries: () => request<Country[]>('/api/v1/countries'),
  country: (iso3: string) => request<Country>(`/api/v1/countries/${iso3}`),
  units: (iso3: string, params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))
    return request<Unit[]>(`/api/v1/countries/${iso3}/units?${qs}`)
  },
  boundaries: (iso3: string, level: number) =>
    request<FeatureCollection>(`/api/v1/countries/${iso3}/boundaries?level_number=${level}`),
  ancestors: (unitId: string) => request<Unit[]>(`/api/v1/units/${unitId}/ancestors`),
  countryIndicators: (iso3: string) => request<Observation[]>(`/api/v1/countries/${iso3}/indicators`),
  unitIndicators: (iso3: string, unitCode: string) =>
    request<Observation[]>(`/api/v1/countries/${iso3}/indicators?unit_code=${unitCode}`),
  indicators: () => request<IndicatorDef[]>('/api/v1/indicators'),
  countryFacilities: (iso3: string, params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))
    return request<{ total: number; facilities: Facility[] }>(`/api/v1/countries/${iso3}/facilities?${qs}`)
  },
  datasets: () => request<Dataset[]>('/api/v1/datasets'),
}
