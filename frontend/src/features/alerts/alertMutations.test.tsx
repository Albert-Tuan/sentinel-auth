/**
 * Stage 5 — S-21 Alert mutations.
 *
 * The workflow panel talks to five mutation endpoints, and each one has a
 * failure mode the UI must not blur together:
 *
 *   - acknowledge / resolve / assign → 409 when the alert was already
 *     closed, and the alert becomes immutable after a resolve;
 *   - the protective action → 502 when the Detection Engine could not
 *     complete the action INSIDE Core, which means the action was NOT
 *     applied. A success banner here would be a lie;
 *   - the note → written as a `note_added` timeline event, because the
 *     backend has no dedicated note route (gap G-9);
 *   - the assignee field → a `soc_analysts.id` UUID, validated on the
 *     client, because an invalid UUID would reach PostgreSQL as a bad
 *     cast and come back as a 500.
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

import { AlertDetailPage } from '@/features/alerts/pages/AlertDetailPage'

const ALERT_ID = 'al000000-0000-0000-0000-000000000001'
const ATTEMPT_ID = 'at000000-0000-0000-0000-000000000001'
const VALID_ASSIGNEE = '8f3c0000-0000-4000-8000-00000000000a'

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
    policy_id: 'po000000-0000-0000-0000-000000000001',
    status: 'open',
    risk_level: 'high',
    detection_reason: 'Impossible travel: combined=0.7500',
    detection_scores: { combined_score: 0.75 },
    assigned_to_id: null,
    resolved_by_id: null,
    resolved_at: null,
    resolution: null,
    notes: null,
    created_at: '2026-11-12T08:00:00.000000+00:00',
    updated_at: '2026-11-12T08:30:00.000000+00:00',
    ...overrides,
  }
}

function mockReads(alertOverrides: Record<string, unknown> = {}) {
  mock.onGet(ENDPOINTS.alerts.detail(ALERT_ID)).reply(200, makeAlert(alertOverrides))
  mock.onGet(ENDPOINTS.alerts.evidence(ALERT_ID)).reply(200, {
    alert: makeAlert(alertOverrides),
    login_attempt: null,
    risk_assessment: null,
    detection_logs: [],
    timeline: [],
  })
  mock.onGet(ENDPOINTS.alerts.timeline(ALERT_ID)).reply(200, [])
}

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/alerts/:alertId" element={<AlertDetailPage />} />
    </Routes>,
    { initialEntries: [`/alerts/${ALERT_ID}`] },
  )
}

describe('S-21 Alert mutations', () => {
  it('acknowledges an open alert', async () => {
    mockReads()
    let body: unknown = null
    mock.onPost(ENDPOINTS.alerts.acknowledge(ALERT_ID)).reply((config) => {
      body = JSON.parse(config.data as string)
      return [200, makeAlert({ status: 'acknowledged' })]
    })

    renderDetail()

    const button = await screen.findByRole('button', {
      name: /xác nhận cảnh báo/i,
    })
    await userEvent.click(button)

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({})
  })

  it('sends the note as a note_added timeline event', async () => {
    mockReads()
    let body: unknown = null
    mock.onPost(ENDPOINTS.alerts.timeline(ALERT_ID)).reply((config) => {
      body = JSON.parse(config.data as string)
      return [201, { id: 'tl-1', alert_id: ALERT_ID, event_type: 'note_added' }]
    })

    renderDetail()

    const textarea = await screen.findByLabelText(/ghi chú điều tra/i)
    await userEvent.type(textarea, 'Đã kiểm tra log từ firewall')
    await userEvent.click(screen.getByRole('button', { name: /thêm ghi chú/i }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({
      event_type: 'note_added',
      comment: 'Đã kiểm tra log từ firewall',
    })
  })

  it('resolves an alert with a canonical resolution', async () => {
    mockReads()
    let body: unknown = null
    mock.onPost(ENDPOINTS.alerts.resolve(ALERT_ID)).reply((config) => {
      body = JSON.parse(config.data as string)
      return [200, makeAlert({ status: 'resolved', resolution: 'true_attack' })]
    })

    renderDetail()

    await userEvent.click(
      await screen.findByRole('button', { name: /xử lý cảnh báo/i }),
    )

    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(
      within(dialog).getByLabelText(/kết quả xử lý/i),
      'true_attack',
    )
    await userEvent.click(
      within(dialog).getByRole('button', { name: /^xử lý$/i }),
    )

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ resolution: 'true_attack' })
  })

  it('never sends an assignee that is not a UUID', async () => {
    mockReads()
    let called = false
    mock.onPost(ENDPOINTS.alerts.assign(ALERT_ID)).reply(() => {
      called = true
      return [200, makeAlert()]
    })

    renderDetail()

    await userEvent.click(
      await screen.findByRole('button', { name: /giao cho analyst/i }),
    )

    const dialog = await screen.findByRole('dialog')
    await userEvent.type(
      within(dialog).getByLabelText(/uuid analyst/i),
      'not-a-uuid',
    )

    // The confirm button stays disabled while the field is invalid.
    const confirm = within(dialog).getByRole('button', { name: /^giao$/i })
    expect(confirm).toBeDisabled()

    await userEvent.click(confirm)
    expect(called).toBe(false)
  })

  it('sends a valid analyst UUID when assigning', async () => {
    mockReads()
    let body: unknown = null
    mock.onPost(ENDPOINTS.alerts.assign(ALERT_ID)).reply((config) => {
      body = JSON.parse(config.data as string)
      return [200, makeAlert({ assigned_to_id: VALID_ASSIGNEE })]
    })

    renderDetail()

    await userEvent.click(
      await screen.findByRole('button', { name: /giao cho analyst/i }),
    )

    const dialog = await screen.findByRole('dialog')
    await userEvent.type(
      within(dialog).getByLabelText(/uuid analyst/i),
      VALID_ASSIGNEE,
    )
    await userEvent.click(
      within(dialog).getByRole('button', { name: /^giao$/i }),
    )

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ assigned_to_id: VALID_ASSIGNEE })
  })

  it('reports a failed protective action as NOT applied', async () => {
    mockReads()
    mock.onPost(ENDPOINTS.alerts.actions(ALERT_ID)).reply(502, {
      detail: 'Detection Engine unreachable',
    })

    renderDetail()

    await userEvent.click(
      await screen.findByRole('button', { name: /hành động bảo vệ/i }),
    )

    const dialog = await screen.findByRole('dialog')

    // The backend REQUIRES a reason (`AlertActionRequest.reason` is
    // `Field(..., min_length=1)`), so the dialog refuses to send the
    // action without one.
    const confirm = within(dialog).getByRole('button', { name: /chạy hành động/i })
    expect(confirm).toBeDisabled()

    await userEvent.type(
      within(dialog).getByLabelText(/lý do/i),
      'Hành động bảo vệ tự động',
    )
    expect(confirm).toBeEnabled()

    await userEvent.click(confirm)

    // A 502 means the action was NOT applied. The UI must say so
    // explicitly — it must never look like a success.
    expect(
      await screen.findByText(/HÀNH ĐỘNG KHÔNG ĐƯỢC ÁP DỤNG/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/thành công/i)).not.toBeInTheDocument()
  })

  it('surfaces a 409 conflict when the alert was already closed', async () => {
    mockReads()
    mock.onPost(ENDPOINTS.alerts.acknowledge(ALERT_ID)).reply(409, {
      detail: 'Alert is not open',
    })

    renderDetail()

    await userEvent.click(
      await screen.findByRole('button', { name: /xác nhận cảnh báo/i }),
    )

    expect(
      await screen.findByText(/không thể xác nhận cảnh báo/i),
    ).toBeInTheDocument()
  })

  it('disables the mutations of an already resolved alert', async () => {
    mockReads({ status: 'resolved', resolution: 'true_attack' })

    renderDetail()

    const acknowledge = await screen.findByRole('button', {
      name: /xác nhận cảnh báo/i,
    })
    expect(acknowledge).toBeDisabled()
    expect(
      screen.getByText(/đã được xử lý và bị đóng băng/i),
    ).toBeInTheDocument()
  })
})
