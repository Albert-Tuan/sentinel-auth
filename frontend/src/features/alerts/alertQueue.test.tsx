/**
 * Stage 4 — S-20 Alert Queue.
 *
 * The screen talks to the real API modules, so the tests mock at the
 * network boundary (the axios adapter). What is under test is the UI
 * contract:
 *
 *   - the queue renders exactly what the backend returned, in the
 *     backend's order;
 *   - the filters are sent to the backend and are mirrored in the URL;
 *   - the pagination is server-side and driven by `total`;
 *   - the empty, error and forbidden states are distinguishable;
 *   - nothing is ever requested from `/api/v1/internal/*`.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MockAdapter from 'axios-mock-adapter'
import { QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'

import { apiClient, __resetClientState } from '@/lib/api/client'
import { __resetStore } from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import {
  makeTestQueryClient,
  renderWithProviders,
} from '@/test/renderApp'

import { AlertQueuePage } from '@/features/alerts/pages/AlertQueuePage'

const ALERT_ID = 'al000000-0000-0000-0000-000000000001'
const ATTEMPT_ID = 'at000000-0000-0000-0000-000000000001'

let mock: MockAdapter

beforeEach(() => {
  __resetStore()
  __resetClientState()
  mock = new MockAdapter(apiClient)
})

function makeAlert(overrides: Record<string, unknown> = {}) {
  return {
    id: ALERT_ID,
    login_attempt_id: ATTEMPT_ID,
    policy_id: null,
    status: 'open',
    risk_level: 'critical',
    detection_reason: 'IP reputation: combined=0.9123',
    detection_scores: null,
    assigned_to_id: null,
    resolved_by_id: null,
    resolved_at: null,
    resolution: null,
    notes: null,
    created_at: '2026-11-12T08:00:00.000000+00:00',
    updated_at: '2026-11-12T08:00:00.000000+00:00',
    ...overrides,
  }
}

/** The queue's subject lookup — the login-attempt enrichment. */
function mockSubjects(attempts: unknown[] = []) {
  mock.onGet(ENDPOINTS.loginAttempts.list).reply(200, {
    attempts,
    total: attempts.length,
    page: 1,
    limit: 100,
  })
}

/** The last request the client sent to the alert queue. */
function lastAlertsRequest() {
  const calls = mock.history.get.filter(
    (request) => request.url === ENDPOINTS.alerts.list,
  )
  return calls[calls.length - 1]
}

/** The parameters of the last request to the alert queue. */
function lastAlertsParams() {
  return lastAlertsRequest()?.params as Record<string, unknown> | undefined
}

describe('S-20 Alert Queue', () => {
  it('renders the alerts the backend returned, in the backend order', async () => {
    const newer = makeAlert({
      id: 'al000000-0000-0000-0000-000000000002',
      detection_reason: 'Newest alert',
      created_at: '2026-11-12T09:00:00.000000+00:00',
    })
    const older = makeAlert({
      id: 'al000000-0000-0000-0000-000000000001',
      detection_reason: 'Older alert',
      created_at: '2026-11-12T07:00:00.000000+00:00',
    })

    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [newer, older],
      total: 2,
      page: 1,
      limit: 20,
    })
    mockSubjects()

    renderWithProviders(<AlertQueuePage />)

    expect(await screen.findByText('Newest alert')).toBeInTheDocument()
    expect(screen.getByText('Older alert')).toBeInTheDocument()

    // The backend owns the order: newest first, exactly as returned.
    const reasons = screen
      .getAllByText(/alert$/)
      .map((element) => element.textContent)
    expect(reasons).toEqual(['Newest alert', 'Older alert'])
  })

  it('shows the risk level and the status of every alert', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [makeAlert({ risk_level: 'critical', status: 'open' })],
      total: 1,
      page: 1,
      limit: 20,
    })
    mockSubjects()

    renderWithProviders(<AlertQueuePage />)

    expect(await screen.findByText('Nghiêm trọng')).toBeInTheDocument()
    expect(screen.getByText('Mở')).toBeInTheDocument()
  })

  it('renders "chưa đánh giá" for an alert without a risk level', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [makeAlert({ risk_level: null })],
      total: 1,
      page: 1,
      limit: 20,
    })
    mockSubjects()

    renderWithProviders(<AlertQueuePage />)

    expect(await screen.findByText('Chưa đánh giá')).toBeInTheDocument()
    // A missing risk level must never be shown as the lowest level.
    // (The lookup is scoped to the table: the filter dropdown legitimately
    // offers "Thấp" as an option.)
    const table = screen.getByRole('table')
    expect(within(table).queryByText('Thấp')).not.toBeInTheDocument()
  })

  it('shows the empty state when there is no alert', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />)

    expect(
      await screen.findByText('Không có cảnh báo nào'),
    ).toBeInTheDocument()
  })

  it('sends the status filter to the backend', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText('Không có cảnh báo nào')

    await userEvent.selectOptions(
      screen.getByLabelText('Trạng thái'),
      'acknowledged',
    )

    await waitFor(() => {
      expect(lastAlertsParams()).toMatchObject({ status: 'acknowledged' })
    })
  })

  it('sends the risk_level filter to the backend', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText('Không có cảnh báo nào')

    await userEvent.selectOptions(
      screen.getByLabelText('Mức rủi ro'),
      'critical',
    )

    await waitFor(() => {
      expect(lastAlertsParams()).toMatchObject({ risk_level: 'critical' })
    })
  })

  it('sends the assigned_to_id filter to the backend', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText('Không có cảnh báo nào')

    const assignee = screen.getByLabelText('Người được giao (UUID)')
    await userEvent.type(assignee, '8f3c1d2e-4b5a-6789-0abc-def012345678')

    await waitFor(() => {
      expect(lastAlertsParams()).toMatchObject({
        assigned_to_id: '8f3c1d2e-4b5a-6789-0abc-def012345678',
      })
    })
  })

  it('never sends an assigned_to_id that is not a UUID', async () => {
    // A non-UUID cannot be matched against the UUID column: the backend
    // would answer 500. The queue must not produce such a request.
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText('Không có cảnh báo nào')

    const assignee = screen.getByLabelText('Người được giao (UUID)')
    await userEvent.type(assignee, 'analyst-uuid-1')

    // The field says why the value is not a filter.
    expect(
      await screen.findByText(/Giá trị phải là UUID hợp lệ/),
    ).toBeInTheDocument()

    await waitFor(() => {
      const params = lastAlertsParams() ?? {}
      expect(params.assigned_to_id).toBeUndefined()
    })
  })

  it('does not send an incomplete UUID while the analyst is still typing', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText('Không có cảnh báo nào')

    const assignee = screen.getByLabelText('Người được giao (UUID)')
    await userEvent.type(assignee, '8f3c1d2e-4b5a-6789')

    await waitFor(() => {
      const params = lastAlertsParams() ?? {}
      expect(params.assigned_to_id).toBeUndefined()
    })
  })

  it('does not send an invalid assignee from a deep link either', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />, {
      initialEntries: ['/alerts?assigned_to_id=not-a-uuid'],
    })

    await screen.findByText('Không có cảnh báo nào')

    await waitFor(() => {
      const params = lastAlertsParams() ?? {}
      expect(params.assigned_to_id).toBeUndefined()
    })
  })

  it('mirrors the filters in the URL so the view can be deep-linked', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />, {
      initialEntries: ['/alerts?status=open&risk_level=high&page=2&limit=50'],
    })

    await screen.findByText('Không có cảnh báo nào')

    // The deep link drives the request exactly like the UI would.
    await waitFor(() => {
      expect(lastAlertsParams()).toMatchObject({
        status: 'open',
        risk_level: 'high',
        page: 2,
        limit: 50,
      })
    })

    // The controls reflect the deep-linked state.
    expect(screen.getByLabelText('Trạng thái')).toHaveValue('open')
    expect(screen.getByLabelText('Mức rủi ro')).toHaveValue('high')
  })

  it('returns to page 1 when a filter changes', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />, {
      initialEntries: ['/alerts?page=3'],
    })

    await screen.findByText('Không có cảnh báo nào')

    await userEvent.selectOptions(screen.getByLabelText('Trạng thái'), 'open')

    await waitFor(() => {
      expect(lastAlertsParams()).toMatchObject({ status: 'open', page: 1 })
    })
  })

  it('paginates with the total the backend reported', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [makeAlert()],
      total: 45,
      page: 1,
      limit: 20,
    })
    mockSubjects()

    renderWithProviders(<AlertQueuePage />)

    expect(await screen.findByText(/Hiển thị 1–20 trên 45 bản ghi/)).toBeInTheDocument()
    expect(screen.getByText('Trang 1 / 3')).toBeInTheDocument()
  })

  it('asks the backend for the next page', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [makeAlert()],
      total: 45,
      page: 1,
      limit: 20,
    })
    mockSubjects()

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText(/trên 45 bản ghi/)

    await userEvent.click(screen.getByRole('button', { name: 'Sau' }))

    await waitFor(() => {
      expect(lastAlertsParams()).toMatchObject({ page: 2 })
    })
  })

  it('reports a 400 from an invalid filter as an error', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(400, {
      detail: "status must be one of ['acknowledged', 'false_positive', 'open', 'resolved']",
    })

    renderWithProviders(<AlertQueuePage />)

    expect(
      await screen.findByText('Không thể tải danh sách cảnh báo'),
    ).toBeInTheDocument()
  })

  it('reports a 403 as an error', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(403, {
      detail: 'Insufficient permissions',
    })

    renderWithProviders(<AlertQueuePage />)

    expect(
      await screen.findByText('Không thể tải danh sách cảnh báo'),
    ).toBeInTheDocument()
  })

  it('reports a 401 as an error', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(401, {
      detail: 'Invalid or expired session',
    })

    renderWithProviders(<AlertQueuePage />)

    expect(
      await screen.findByText('Không thể tải danh sách cảnh báo'),
    ).toBeInTheDocument()
  })

  it('shows the subject of an alert when the backend knows it', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [makeAlert()],
      total: 1,
      page: 1,
      limit: 20,
    })
    mockSubjects([
      {
        id: ATTEMPT_ID,
        event_id: 'ev-1',
        user_id: 'user-1',
        username_attempted: 'victim@example.com',
        outcome: 'failure',
        mfa_used: false,
        ip_address: '203.0.113.7',
        user_agent: 'curl/8.0',
        device_fingerprint: null,
        timestamp: '2026-11-12T08:00:00.000000+00:00',
        status: 'processed',
        risk_level: 'critical',
        detection_decision: 'block',
        policy_id: null,
        primary_alert_id: ALERT_ID,
        request_id: null,
      },
    ])

    renderWithProviders(<AlertQueuePage />)

    expect(
      await screen.findByText('victim@example.com'),
    ).toBeInTheDocument()
    expect(screen.getByText('203.0.113.7')).toBeInTheDocument()
  })

  it('never requests an internal endpoint', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [makeAlert()],
      total: 1,
      page: 1,
      limit: 20,
    })
    mockSubjects()

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText(/IP reputation/)

    const internal = mock.history.get.filter((request) =>
      request.url?.includes('/internal/'),
    )
    expect(internal).toHaveLength(0)
  })

  it('opens the detail of an alert when its row is clicked', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [makeAlert()],
      total: 1,
      page: 1,
      limit: 20,
    })
    mockSubjects()

    // A minimal router: the queue page and the target route. The full
    // route table is not needed here — only the navigation the row click
    // performs.
    const router = createMemoryRouter(
      [
        { path: '/alerts', element: <AlertQueuePage /> },
        { path: '/alerts/:alertId', element: <div>Detail screen</div> },
      ],
      { initialEntries: ['/alerts'] },
    )

    render(
      <QueryClientProvider client={makeTestQueryClient()}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )

    expect(await screen.findByText(/IP reputation/)).toBeInTheDocument()

    await userEvent.click(screen.getByText(/IP reputation/))

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`/alerts/${ALERT_ID}`)
    })
  })
  it('does not show a login attempt that the backend does not know', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [makeAlert()],
      total: 1,
      page: 1,
      limit: 20,
    })
    mockSubjects([])

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText(/IP reputation/)

    // The subject is unknown, so the column stays empty — it is never
    // filled with a placeholder that looks like a real value.
    const cells = screen.getAllByRole('cell')
    const usernameCell = cells.find((cell) => cell.textContent === '—')
    expect(usernameCell).toBeDefined()
  })
})

describe('S-20 filter vocabulary', () => {
  it('offers only the statuses the backend accepts', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText('Không có cảnh báo nào')

    const options = within(screen.getByLabelText('Trạng thái')).getAllByRole(
      'option',
    )
    const values = options.map((option) => (option as HTMLOptionElement).value)

    expect(values).toContain('open')
    expect(values).toContain('acknowledged')
    expect(values).toContain('resolved')
    expect(values).toContain('false_positive')
    // `escalated` is a timeline event, not an alert status.
    expect(values).not.toContain('escalated')
  })

  it('offers only the risk levels the backend accepts', async () => {
    mock.onGet(ENDPOINTS.alerts.list).reply(200, {
      alerts: [],
      total: 0,
      page: 1,
      limit: 20,
    })

    renderWithProviders(<AlertQueuePage />)

    await screen.findByText('Không có cảnh báo nào')

    const options = within(screen.getByLabelText('Mức rủi ro')).getAllByRole(
      'option',
    )
    const values = options.map((option) => (option as HTMLOptionElement).value)

    expect(values).toEqual(
      expect.arrayContaining(['', 'low', 'medium', 'high', 'critical']),
    )
  })
})
