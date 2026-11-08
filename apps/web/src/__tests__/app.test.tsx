import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import App from '../App'

// Minimal API mock: /api/v1/countries powers the home page stats.
const countries = Array.from({ length: 58 }, (_, i) => ({
  id: String(i),
  iso2: `X${i % 10}`,
  iso3: `T${String(i).padStart(2, '0')}`,
  name: `Test Country ${i}`,
  official_name: null,
  capital: null,
  region: 'Test Region',
  rep_lon: 20,
  rep_lat: 0,
  status: i === 0 ? 'active' : 'placeholder',
  levels:
    i === 0
      ? [
          { level_number: 1, level_name: 'Region', description: null, unit_count: 4 },
          { level_number: 2, level_name: 'Tinkhundla', description: null, unit_count: 55 },
        ]
      : [],
  total_units: i === 0 ? 59 : 0,
  max_level: i === 0 ? 2 : 0,
}))

afterEach(() => cleanup())

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.includes('/api/v1/countries')) {
        return Promise.resolve(new Response(JSON.stringify(countries), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
    }),
  )
})

describe('App', () => {
  it('renders the tagline and navigation', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText(/Open data\. Stronger communities\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Map' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Countries' })).toBeInTheDocument()
  })

  it('shows honest coverage stats: 58 supported, 1 onboarded', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getAllByText('58').length).toBeGreaterThan(0)
      expect(screen.getAllByText('1').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('Countries structurally supported')).toBeInTheDocument()
    expect(screen.getByText('Countries with onboarded data')).toBeInTheDocument()
  })

  it('lists the onboarded country and links its profile', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getAllByText('Test Country 0').length).toBeGreaterThan(0)
    })
    expect(screen.getByRole('link', { name: /Test Country 0/ })).toHaveAttribute(
      'href',
      '/countries/T00',
    )
  })
})
