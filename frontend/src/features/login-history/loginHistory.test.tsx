/**
 * S-22 — Login History.
 *
 * The screen reads `GET /api/v1/login-attempts`, the endpoint the backend
 * built for the SOC analyst (UC-DE-14). The contract under test:
 *
 *   - the rows are rendered exactly as the server returned them, newest
 *     first — the client never re-sorts;
 *   - the search vocabulary is the BACKEND's: `outcome` accepts only
 *     `success` and `failure`, `risk_level` only the four canonical
 *     levels. An unknown value would come back as a 400, so the dropdowns
 *     offer nothing else;
 *   - a filter the analyst leaves empty is not sent, because the backend
 *     would reject an empty `username` (min_length=1);
 *   - the pagination is the backend's: the client asks for a page and
 *     renders the total it got back.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MockAdapter from 'axios-mock-adapter'
import { Route, Routes } from 'react-router-dom'

import { apiClient, __resetClientState } from '@/lib/api/client'
import { __resetStore } from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { renderWithProviders } from '@/test/renderApp'

import { LoginHistoryPage } from '@/features/login-history/pages/LoginHistoryPage'

let mock: MockAdapter

beforeEach(() => {
  __resetStore()
  __resetClientState()
  mock = new MockAdapter(apiClient)
})

function makeAttempt(overrides: Record<string, unknown> = {}) {
  return {
    id: 'la000000-0000-0000-0000-000000000001',
    event_id: 'ev-1',
    user_id: 'u000000-0000-0000-0000-000000000001',
    username_attempted: 'victim@example.com',
    outcome: 'failure',
    mfa_used: false,
    ip_address: '203.0.113.7',
    user_agent: 'Mozilla/5.0 Chrome/120.0',
    device_fingerprint: null,
    timestamp: '2026-11-12T07:59:00.000000+00:00',
    status: 'processed',
    risk_level: 'high',
    detection_decision: 'challenge',
    policy_id: 'po000000-0000-0000-0000-000000000001',
    primary_alert_id: 'al000000-0000-0000-0000-000000000001',
    request_id: null,
    ...overrides,
  }
}

function mockHistory(
  attempts: unknown[],
  total = attempts.length,
  page = 1,
  limit = 20,
) {
  mock
    .onGet(ENDPOINTS.loginAttempts.list)
    .reply((config) => {
      const requested = Number(config.params?.page ?? 1)
      return [
        200,
        {
          attempts: requested === page ? attempts : [],
          total,
          page: requested,
          limit,
        },
      ]
    })
}

function renderHistory() {
  return renderWithProviders(
    <Routes>
      <Route path="/login-history" element={<LoginHistoryPage />} />
    </Routes>,
    { initialEntries: ['/login-history'] },
  )
}

describe('S-22 Login History', () => {
  it('lists the login attempts the backend returned', async () => {
    mockHistory([makeAttempt()])

    renderHistory()

    expect(
      await screen.findByText('victim@example.com'),
    ).toBeInTheDocument()
    expect(screen.getByText('203.0.113.7')).toBeInTheDocument()
    expect(screen.getAllByText('Cao').length).toBeGreaterThanOrEqual(1)
  })

  it('shows the empty state when nothing matches', async () => {
    mockHistory([])

    renderHistory()

    expect(await screen.findByText('Không có dữ liệu')).toBeInTheDocument()
  })

  it('sends the search filters the analyst chose', async () => {
    let params: Record<string, unknown> = {}
    mock.onGet(ENDPOINTS.loginAttempts.list).reply((config) => {
      params = (config.params ?? {}) as Record<string, unknown>
      return [200, { attempts: [], total: 0, page: 1, limit: 20 }]
    })

    renderHistory()

    await userEvent.type(
      await screen.findByLabelText(/tài khoản/i),
      'victim@example.com',
    )
    await userEvent.selectOptions(screen.getByLabelText(/kết quả/i), 'failure')
    await userEvent.selectOptions(screen.getByLabelText(/mức rủi ro/i), 'high')
    await userEvent.click(screen.getByRole('button', { name: /tìm kiếm/i }))

    await waitFor(() => expect(params.username).toBe('victim@example.com'))
    expect(params.outcome).toBe('failure')
    expect(params.risk_level).toBe('high')
    expect(params.page).toBe(1)
  })

  it('never sends an empty filter value', async () => {
    let params: Record<string, unknown> = {}
    mock.onGet(ENDPOINTS.loginAttempts.list).reply((config) => {
      params = (config.params ?? {}) as Record<string, unknown>
      return [200, { attempts: [], total: 0, page: 1, limit: 20 }]
    })

    renderHistory()

    await screen.findByRole('button', { name: /tìm kiếm/i })
    await userEvent.click(screen.getByRole('button', { name: /tìm kiếm/i }))

    await waitFor(() => expect(params.page).toBe(1))
    // An empty username would be rejected by the backend (min_length=1).
    expect(params.username).toBeUndefined()
    expect(params.outcome).toBeUndefined()
    expect(params.risk_level).toBeUndefined()
  })

  it('offers only the outcome values the backend accepts', async () => {
    mockHistory([])

    renderHistory()

    const select = await screen.findByLabelText(/kết quả/i)
    const options = within(select)
      .getAllByRole('option')
      .map((option) => option.getAttribute('value'))

    // "Tất cả" plus exactly the two search outcomes.
    expect(options).toEqual(['', 'success', 'failure'])
  })

  it('offers only the four canonical risk levels', async () => {
    mockHistory([])

    renderHistory()

    const select = await screen.findByLabelText(/mức rủi ro/i)
    const options = within(select)
      .getAllByRole('option')
      .map((option) => option.getAttribute('value'))

    expect(options).toEqual(['', 'low', 'medium', 'high', 'critical'])
  })

  it('links a row to the alert it produced', async () => {
    mockHistory([makeAttempt()])

    renderHistory()

    const link = await screen.findByRole('link', {
      name: 'al000000-0000-0000-0000-000000000001',
    })
    expect(link).toHaveAttribute(
      'href',
      '/alerts/al000000-0000-0000-0000-000000000001',
    )
  })

  it('shows an unknown outcome verbatim instead of folding it into a known one', async () => {
    mockHistory([makeAttempt({ outcome: 'some_new_outcome' })])

    renderHistory()

    expect(
      await screen.findByText('some_new_outcome'),
    ).toBeInTheDocument()
  })

  it('paginates with the total the backend reported', async () => {
    mockHistory([makeAttempt()], 42, 1, 20)

    renderHistory()

    expect(
      await screen.findByText('Hiển thị 1–20 trên 42 bản ghi'),
    ).toBeInTheDocument()
  })
})
