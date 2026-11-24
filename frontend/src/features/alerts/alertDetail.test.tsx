/**
 * Stage 4 — S-21 Alert Detail.
 *
 * The screen reads three real endpoints (alert, evidence, timeline), so
 * the tests mock at the network boundary. The contract under test:
 *
 *   - the three sections render independently, so a failing section never
 *     hides the others;
 *   - the nullable fields are distinguished from each other: a missing ML
 *     score is NOT a score of zero, and a rule-only fallback is called
 *     out explicitly;
 *   - the timeline shows the event type, the actor, the timestamp and the
 *     content of every event.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import MockAdapter from 'axios-mock-adapter'
import { Route, Routes } from 'react-router-dom'

import { apiClient, __resetClientState } from '@/lib/api/client'
import { __resetStore } from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { renderWithProviders } from '@/test/renderApp'

import { AlertDetailPage } from '@/features/alerts/pages/AlertDetailPage'

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
    policy_id: 'po000000-0000-0000-0000-000000000001',
    status: 'acknowledged',
    risk_level: 'high',
    detection_reason: 'Impossible travel: combined=0.7500',
    detection_scores: {
      rule_score: 0.5,
      ml_score: 0.25,
      combined_score: 0.75,
      ml_status: 'ok',
    },
    assigned_to_id: 'an000000-0000-0000-0000-000000000001',
    resolved_by_id: null,
    resolved_at: null,
    resolution: null,
    notes: 'Đã xác nhận, đang điều tra.',
    created_at: '2026-11-12T08:00:00.000000+00:00',
    updated_at: '2026-11-12T08:30:00.000000+00:00',
    ...overrides,
  }
}

function mockAlert(overrides: Record<string, unknown> = {}) {
  mock.onGet(ENDPOINTS.alerts.detail(ALERT_ID)).reply(200, makeAlert(overrides))
}

function mockEvidence(overrides: Record<string, unknown> = {}) {
  mock.onGet(ENDPOINTS.alerts.evidence(ALERT_ID)).reply(200, {
    alert: makeAlert(),
    login_attempt: {
      id: ATTEMPT_ID,
      event_id: 'ev-1',
      timestamp: '2026-11-12T07:59:00.000000+00:00',
      outcome: 'failure',
      username_attempted: 'victim@example.com',
      ip_address: '203.0.113.7',
      user_agent: 'Mozilla/5.0 Chrome/120.0',
      user_id: 'user-1',
      mfa_used: false,
      risk_level: 'high',
      detection_decision: 'block',
    },
    risk_assessment: {
      rule_score: 0.5,
      ml_score: 0.25,
      combined_score: 0.75,
      ml_status: 'ok',
      ml_model_version: 'v3.2.0',
      ml_reason_codes: ['rare_ip'],
      ml_features_used: { ip_entropy: 0.8 },
      rule_hits: [{ rule_name: 'impossible_travel' }],
      risk_level: 'high',
      decision: 'block',
    },
    detection_logs: [
      {
        id: 'dl-1',
        stage: 'rules',
        stage_detail: 'geo',
        rule_name: 'impossible_travel',
        triggered: true,
        score_contribution: 0.5,
        decision: 'block',
        reason: 'distance too large',
        details: null,
        created_at: '2026-11-12T07:59:01.000000+00:00',
      },
    ],
    timeline: [],
    ...overrides,
  })
}

function mockTimeline(events: unknown[] = []) {
  mock.onGet(ENDPOINTS.alerts.timeline(ALERT_ID)).reply(200, events)
}

/** The detail screen, mounted on the alert route. */
function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/alerts/:alertId" element={<AlertDetailPage />} />
    </Routes>,
    { initialEntries: [`/alerts/${ALERT_ID}`] },
  )
}

describe('S-21 Alert Detail', () => {
  it('shows the alert overview', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline()

    renderDetail()

    expect(
      await screen.findByText('Impossible travel: combined=0.7500'),
    ).toBeInTheDocument()
    // The risk level appears in the header and in the overview; both must
    // say the same thing.
    expect(screen.getAllByText('Cao').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Đã xác nhận').length).toBeGreaterThanOrEqual(1)
    expect(
      screen.getByText('Đã xác nhận, đang điều tra.'),
    ).toBeInTheDocument()
    expect(screen.getByText(ALERT_ID)).toBeInTheDocument()
  })

  it('shows the login attempt details', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline()

    renderDetail()

    expect(
      await screen.findByText('victim@example.com'),
    ).toBeInTheDocument()
    expect(screen.getByText('203.0.113.7')).toBeInTheDocument()
    expect(screen.getByText('failure')).toBeInTheDocument()
    expect(screen.getByText('Google Chrome')).toBeInTheDocument()
  })

  it('shows the risk assessment scores', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('Điểm quy tắc')).toBeInTheDocument()
    // The scores appear in the risk panel and in the overview's score
    // block; both must show the same numbers.
    expect(screen.getAllByText('0.5000').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('0.2500').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('0.7500').length).toBeGreaterThanOrEqual(1)
  })

  it('shows the detection logs', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('impossible_travel')).toBeInTheDocument()
    expect(screen.getByText('distance too large')).toBeInTheDocument()
    expect(screen.getByText('Log phát hiện')).toBeInTheDocument()
  })

  it('shows a null score as "no data", never as zero', async () => {
    mockAlert()
    mockEvidence({
      risk_assessment: {
        rule_score: 0.5,
        ml_score: null,
        combined_score: null,
        ml_status: 'unavailable',
        ml_model_version: null,
        ml_reason_codes: null,
        ml_features_used: null,
        rule_hits: null,
        risk_level: 'medium',
        decision: 'allow',
      },
    })
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('Điểm ML')).toBeInTheDocument()

    // Two missing scores -> two "no data" markers, and no "0.0000" that
    // could be mistaken for a real zero.
    const noData = screen.getAllByText('Không có dữ liệu')
    expect(noData.length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('0.0000')).not.toBeInTheDocument()
  })
  it('marks the rule-only fallback explicitly', async () => {
    mockAlert()
    mockEvidence({
      risk_assessment: {
        rule_score: 0.5,
        ml_score: null,
        combined_score: 0.5,
        ml_status: 'unavailable',
        ml_model_version: null,
        ml_reason_codes: ['ml_unavailable'],
        ml_features_used: null,
        rule_hits: null,
        risk_level: 'medium',
        decision: 'allow',
      },
    })
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('unavailable')).toBeInTheDocument()
    expect(
      screen.getByText(/chỉ dùng điểm quy tắc \(rule-only\)/),
    ).toBeInTheDocument()
  })

  it('marks an ML error as a rule-only fallback too', async () => {
    mockAlert()
    mockEvidence({
      risk_assessment: {
        rule_score: 0.5,
        ml_score: null,
        combined_score: 0.5,
        ml_status: 'error',
        ml_model_version: null,
        ml_reason_codes: null,
        ml_features_used: null,
        rule_hits: null,
        risk_level: 'medium',
        decision: 'allow',
      },
    })
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('error')).toBeInTheDocument()
    expect(
      screen.getByText(/chỉ dùng điểm quy tắc \(rule-only\)/),
    ).toBeInTheDocument()
  })

  it('shows a score of zero as zero', async () => {
    mockAlert()
    mockEvidence({
      risk_assessment: {
        rule_score: 0,
        ml_score: 0,
        combined_score: 0,
        ml_status: 'ok',
        ml_model_version: 'v1',
        ml_reason_codes: [],
        ml_features_used: null,
        rule_hits: [],
        risk_level: 'low',
        decision: 'allow',
      },
    })
    mockTimeline()

    renderDetail()

    await screen.findByText('Điểm ML')

    // A real zero is shown as "0.0000" — never as "no data".
    expect(screen.getAllByText('0.0000').length).toBeGreaterThanOrEqual(1)
    // The risk panel itself has no "no data" marker: every score is a
    // real number.
    const riskPanel = screen.getByText('Điểm quy tắc').closest('div')
      ?.parentElement as HTMLElement
    expect(within(riskPanel).queryByText('Không có dữ liệu')).toBeNull()
  })

  it('shows an alert without a login attempt', async () => {
    mockAlert()
    mockEvidence({ login_attempt: null })
    mockTimeline()

    renderDetail()

    expect(
      await screen.findByText('Không có dữ liệu lần đăng nhập'),
    ).toBeInTheDocument()
  })

  it('shows an alert without a risk assessment', async () => {
    mockAlert()
    mockEvidence({ risk_assessment: null })
    mockTimeline()

    renderDetail()

    expect(
      await screen.findByText('Không có đánh giá rủi ro'),
    ).toBeInTheDocument()
  })

  it('shows an empty detection log', async () => {
    mockAlert()
    mockEvidence({ detection_logs: [] })
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('Không có log phát hiện')).toBeInTheDocument()
  })

  it('shows the timeline with the type, the actor and the content', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline([
      {
        id: 'tl-1',
        alert_id: ALERT_ID,
        event_type: 'created',
        actor_id: null,
        actor_type: 'system',
        old_value: null,
        new_value: 'open',
        comment: 'Alert created automatically by the Detection Engine.',
        ip_address: null,
        created_at: '2026-11-12T08:00:00.000000+00:00',
      },
      {
        id: 'tl-2',
        alert_id: ALERT_ID,
        event_type: 'acknowledged',
        actor_id: 'user-1',
        actor_type: 'user',
        old_value: 'open',
        new_value: 'acknowledged',
        comment: 'Đã tiếp nhận.',
        ip_address: '127.0.0.1',
        created_at: '2026-11-12T08:30:00.000000+00:00',
      },
    ])

    renderDetail()

    expect(await screen.findByText('Được tạo')).toBeInTheDocument()
    const timeline = screen.getByRole('list', {
      name: 'Dòng thời gian cảnh báo',
    })
    expect(within(timeline).getByText('Đã xác nhận')).toBeInTheDocument()
    expect(
      screen.getByText('Alert created automatically by the Detection Engine.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Đã tiếp nhận.')).toBeInTheDocument()
    // The actor of the second event.
    expect(screen.getByText(/user-1/)).toBeInTheDocument()
    // The transition of the second event. ("acknowledged" also appears as
    // the status badge, so the timeline entry is checked in its own list.)
    // "open" appears twice inside the feed: as the new value of the
    // creation event and as the old value of the acknowledgement.
    expect(within(timeline).getAllByText('open').length).toBe(2)
    expect(within(timeline).getByText('acknowledged')).toBeInTheDocument()
  })

  it('shows an empty timeline', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline([])

    renderDetail()

    expect(
      await screen.findByText('Chưa có sự kiện nào'),
    ).toBeInTheDocument()
  })

  it('reports a 404 on the alert', async () => {
    mock.onGet(ENDPOINTS.alerts.detail(ALERT_ID)).reply(404, {
      detail: 'Alert not found',
    })
    mockEvidence()
    mockTimeline()

    renderDetail()

    expect(
      await screen.findByText('Không thể tải cảnh báo'),
    ).toBeInTheDocument()
  })

  it('reports a 403 on the evidence but keeps the alert visible', async () => {
    mockAlert()
    mock.onGet(ENDPOINTS.alerts.evidence(ALERT_ID)).reply(403, {
      detail: 'Insufficient permissions',
    })
    mockTimeline()

    renderDetail()

    expect(
      await screen.findByText('Không thể tải bằng chứng'),
    ).toBeInTheDocument()
    // The overview is still there: one failing section must not hide the
    // others.
    expect(
      screen.getByText('Impossible travel: combined=0.7500'),
    ).toBeInTheDocument()
  })

  it('reports a 401 on the timeline', async () => {
    mockAlert()
    mockEvidence()
    mock.onGet(ENDPOINTS.alerts.timeline(ALERT_ID)).reply(401, {
      detail: 'Invalid or expired session',
    })

    renderDetail()

    expect(
      await screen.findByText('Không thể tải dòng thời gian'),
    ).toBeInTheDocument()
  })

  it('never requests an internal endpoint', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline()

    renderDetail()

    await screen.findByText('Impossible travel: combined=0.7500')

    await waitFor(() => {
      const internal = mock.history.get.filter((request) =>
        request.url?.includes('/internal/'),
      )
      expect(internal).toHaveLength(0)
    })
  })

  it('requests the alert, the evidence and the timeline', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline()

    renderDetail()

    await screen.findByText('Impossible travel: combined=0.7500')

    await waitFor(() => {
      const urls = mock.history.get.map((request) => request.url)
      expect(urls).toContain(ENDPOINTS.alerts.detail(ALERT_ID))
      expect(urls).toContain(ENDPOINTS.alerts.evidence(ALERT_ID))
      expect(urls).toContain(ENDPOINTS.alerts.timeline(ALERT_ID))
    })
  })

  it('renders the detection scores of the overview', async () => {
    mockAlert()
    mockEvidence()
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('Điểm phát hiện')).toBeInTheDocument()
    const panel = screen
      .getByText('Điểm phát hiện')
      .closest('div') as HTMLElement
    expect(within(panel).getByText('rule_score')).toBeInTheDocument()
  })

  it('shows a null detection score as "no data", never as the text "null"', async () => {
    // The rule-only fallback the backend sends: `ml_score` and
    // `ml_model_version` are JSON null inside `detection_scores`.
    mockAlert({
      detection_scores: {
        rule_score: 0.4,
        ml_score: null,
        combined_score: 0.4,
        ml_status: 'unavailable',
        ml_model_version: null,
      },
    })
    mockEvidence()
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('Điểm phát hiện')).toBeInTheDocument()

    const panel = screen
      .getByText('Điểm phát hiện')
      .closest('div') as HTMLElement

    // The two null entries are rendered as "no data".
    expect(
      within(panel).getAllByText('Không có dữ liệu').length,
    ).toBeGreaterThanOrEqual(2)

    // The literal text "null" must never leak into the UI.
    expect(within(panel).queryByText('null')).not.toBeInTheDocument()
    expect(within(panel).queryByText(/^null$/)).not.toBeInTheDocument()
    expect(panel.textContent).not.toContain('null')

    // The real scores are still rendered (both 0.4 values).
    expect(within(panel).getAllByText('0.4000').length).toBeGreaterThanOrEqual(2)
  })

  it('shows a detection score of zero as zero, not as "no data"', async () => {
    mockAlert({
      detection_scores: {
        rule_score: 0,
        ml_score: 0,
        combined_score: 0,
      },
    })
    mockEvidence()
    mockTimeline()

    renderDetail()

    expect(await screen.findByText('Điểm phát hiện')).toBeInTheDocument()

    const panel = screen
      .getByText('Điểm phát hiện')
      .closest('div') as HTMLElement

    expect(within(panel).getAllByText('0.0000').length).toBeGreaterThanOrEqual(3)
    expect(within(panel).queryByText('Không có dữ liệu')).not.toBeInTheDocument()
  })
})
