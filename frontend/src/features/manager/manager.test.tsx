/**
 * S-40 … S-44 — Manager analytics.
 *
 * The contracts under test, all of them taken from the Core facade:
 *
 *   - every response carries the envelope: the EFFECTIVE window (the
 *     backend applies a default when the caller sends none), the
 *     `degraded` flag and the per-source status;
 *   - a `degraded` payload is a VALID payload — the sections that could
 *     be computed are present, and the missing ones render as an
 *     explicit "không có dữ liệu", never as zeros;
 *   - a `null` KPI is NOT a zero. A KPI over an empty population and a
 *     KPI whose source is down are both `null`, and the screen says
 *     "không có dữ liệu" for both;
 *   - the bucket is a QUERY PARAMETER and the backend echoes back the
 *     one it actually used;
 *   - a filter left unset is NOT sent, because the backend validates
 *     the vocabulary and answers 400 for an invalid value.
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MockAdapter from 'axios-mock-adapter'
import { Route, Routes } from 'react-router-dom'

import { apiClient, __resetClientState } from '@/lib/api/client'
import { __resetStore } from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { renderWithProviders } from '@/test/renderApp'

import { ManagerDashboardPage } from '@/features/manager/pages/ManagerDashboardPage'
import { ManagerTrendsPage } from '@/features/manager/pages/ManagerTrendsPage'
import { ManagerAlertsPage } from '@/features/manager/pages/ManagerAlertsPage'
import { ManagerSocKpiPage } from '@/features/manager/pages/ManagerSocKpiPage'
import { ManagerMlStatsPage } from '@/features/manager/pages/ManagerMlStatsPage'

let mock: MockAdapter

beforeEach(() => {
  __resetStore()
  __resetClientState()
  mock = new MockAdapter(apiClient)
})

const WINDOW = {
  from: '2026-11-23T08:00:00+00:00',
  to: '2026-11-24T08:00:00+00:00',
}

function makeEnvelope(overrides: Record<string, unknown> = {}) {
  return {
    generated_at: '2026-11-24T08:00:00+00:00',
    window: WINDOW,
    degraded: false,
    sources: {
      core: { status: 'ok', detail: null },
      detection: { status: 'ok', detail: null },
      ml: { status: 'ok', detail: null },
    },
    ...overrides,
  }
}

function renderPage(element: React.ReactNode, path: string) {
  return renderWithProviders(
    <Routes>
      <Route path={path} element={element} />
    </Routes>,
    { initialEntries: [path] },
  )
}

describe('S-40 Manager Dashboard', () => {
  it('shows the effective window the backend used', async () => {
    mock.onGet(ENDPOINTS.manager.dashboard).reply(
      200,
      makeEnvelope({ core: null, detection: null, ml: null }),
    )

    renderPage(<ManagerDashboardPage />, '/manager/dashboard')

    expect(await screen.findByText(/2026-11-23T08:00:00/)).toBeInTheDocument()
  })

  it('reports the healthy state when no source is down', async () => {
    mock.onGet(ENDPOINTS.manager.dashboard).reply(
      200,
      makeEnvelope({ core: null, detection: null, ml: null }),
    )

    renderPage(<ManagerDashboardPage />, '/manager/dashboard')

    expect(
      await screen.findByText('ALL_SYSTEMS_OPERATIONAL'),
    ).toBeInTheDocument()
  })

  it('names the unavailable source in the degraded banner', async () => {
    mock.onGet(ENDPOINTS.manager.dashboard).reply(
      200,
      makeEnvelope({
        degraded: true,
        sources: {
          core: { status: 'ok', detail: null },
          detection: { status: 'unavailable', detail: 'timeout' },
          ml: { status: 'ok', detail: null },
        },
        core: null,
        detection: null,
        ml: null,
      }),
    )

    renderPage(<ManagerDashboardPage />, '/manager/dashboard')

    expect(await screen.findByText('DEGRADED_MODE')).toBeInTheDocument()
    expect(screen.getByText('DETECTION: timeout')).toBeInTheDocument()
  })

  it('renders a missing section as "không có dữ liệu", never as zeros', async () => {
    mock.onGet(ENDPOINTS.manager.dashboard).reply(
      200,
      makeEnvelope({ core: null, detection: null, ml: null }),
    )

    renderPage(<ManagerDashboardPage />, '/manager/dashboard')

    await screen.findByText('ALL_SYSTEMS_OPERATIONAL')
    // Three sections are missing — each one says so.
    expect(
      screen.getAllByText('Không có dữ liệu').length,
    ).toBeGreaterThanOrEqual(3)
  })

  it('shows the failure state when the backend answers 503', async () => {
    mock.onGet(ENDPOINTS.manager.dashboard).reply(503, {
      detail: 'analytics sources unavailable',
      sources: {
        detection: { status: 'unavailable', detail: 'database_error' },
      },
    })

    renderPage(<ManagerDashboardPage />, '/manager/dashboard')

    expect(
      await screen.findByText(/không thể tải bảng điều khiển quản lý/i),
    ).toBeInTheDocument()
  })
})

describe('S-41 Manager Trends', () => {
  it('sends the bucket to the backend and renders the echoed bucket', async () => {
    mock.onGet(ENDPOINTS.manager.trends).reply(
      200,
      makeEnvelope({
        bucket: 'day',
        series: { login_attempts: [], alerts: [], ml: [] },
      }),
    )

    const user = userEvent.setup()
    renderPage(<ManagerTrendsPage />, '/manager/trends')

    await screen.findByText(/Bucket backend áp dụng/)

    await user.selectOptions(screen.getByLabelText('Độ phân giải'), 'day')

    await waitFor(() => {
      // The LAST call is the one the manager triggered; the earlier ones
      // belong to the initial render.
      const call = mock.history.get
        .filter((entry) => entry.url === ENDPOINTS.manager.trends)
        .pop()
      // The axios mock keeps the undefined keys, so the VALUE is what
      // matters: an unset parameter must be undefined, never an empty
      // string (which the backend answers 400 for).
      expect(call?.params.bucket).toBe('day')
    })
    expect(screen.getByText('day')).toBeInTheDocument()
  })

  it('renders an absent series as an explicit empty state', async () => {
    mock.onGet(ENDPOINTS.manager.trends).reply(
      200,
      makeEnvelope({
        bucket: 'hour',
        series: { login_attempts: null, alerts: null, ml: null },
      }),
    )

    renderPage(<ManagerTrendsPage />, '/manager/trends')

    await screen.findByText(/Bucket backend áp dụng/)
    expect(screen.getAllByText('Không có dữ liệu').length).toBe(3)
  })
})

describe('S-42 Manager Alert Analytics', () => {
  function makeAlerts(overrides: Record<string, unknown> = {}) {
    return makeEnvelope({
      totals: {
        created: 30,
        open: 5,
        acknowledged: 8,
        resolved: 15,
        false_positive: 2,
      },
      by_status: { open: 5, acknowledged: 8, resolved: 15, false_positive: 2 },
      by_risk_level: { low: 10, medium: 8, high: 7, critical: 5 },
      by_rule: [{ rule: 'fail_count_24h', count: 12 }],
      by_ml_reason: [{ reason: 'geo_velocity', count: 4 }],
      backlog: {
        open_count: 5,
        oldest_open_age_hours: 12.5,
        unassigned: 2,
        escalated: 1,
      },
      false_positive_rate: 0.067,
      mtta_seconds: 180.5,
      mttr_seconds: 3600.25,
      acknowledged_count: 8,
      resolved_count: 15,
      ...overrides,
    })
  }

  it('does not send an unset filter', async () => {
    mock.onGet(ENDPOINTS.manager.alerts).reply(200, makeAlerts())

    renderPage(<ManagerAlertsPage />, '/manager/alerts')

    await screen.findByText('Tổng quan cảnh báo')

    const call = mock.history.get.find(
      (entry) => entry.url === ENDPOINTS.manager.alerts,
    )
    expect(call?.params.status).toBeUndefined()
    expect(call?.params.risk_level).toBeUndefined()
  })

  it('sends the filters the manager chose', async () => {
    mock.onGet(ENDPOINTS.manager.alerts).reply(200, makeAlerts())

    const user = userEvent.setup()
    renderPage(<ManagerAlertsPage />, '/manager/alerts')

    await screen.findByText('Tổng quan cảnh báo')

    await user.selectOptions(screen.getByLabelText('Trạng thái'), 'open')
    await user.selectOptions(screen.getByLabelText('Mức rủi ro'), 'critical')

    await waitFor(() => {
      const call = mock.history.get
        .filter((entry) => entry.url === ENDPOINTS.manager.alerts)
        .pop()
      expect(call?.params.status).toBe('open')
      expect(call?.params.risk_level).toBe('critical')
    })
  })

  it('renders a null metric as "không có dữ liệu"', async () => {
    mock.onGet(ENDPOINTS.manager.alerts).reply(
      200,
      makeAlerts({ mtta_seconds: null, mttr_seconds: null }),
    )

    renderPage(<ManagerAlertsPage />, '/manager/alerts')

    await screen.findByText('Hiệu suất xử lý')
    const missing = screen.getAllByText('— không có dữ liệu')
    expect(missing.length).toBeGreaterThanOrEqual(2)
  })
})

describe('S-43 Manager SOC KPI', () => {
  it('renders a null KPI as "không có dữ liệu", never as 0', async () => {
    mock.onGet(ENDPOINTS.manager.socKpi).reply(
      200,
      makeEnvelope({
        kpis: {
          mtta_seconds: null,
          mttr_seconds: 3600,
          acknowledgement_rate: null,
          resolution_rate: 0.75,
        },
      }),
    )

    renderPage(<ManagerSocKpiPage />, '/manager/soc-kpi')

    await screen.findByText('Thời gian phản hồi')

    // The null KPI is marked as missing.
    const missing = screen.getAllByText('— không có dữ liệu')
    expect(missing.length).toBeGreaterThanOrEqual(2)
    // The measured KPI shows its real value.
    expect(screen.getByText('3600')).toBeInTheDocument()
    expect(screen.getByText('0.75')).toBeInTheDocument()
  })
})

describe('S-44 Manager ML Stats', () => {
  it('renders the model, the inference stats and the feature table', async () => {
    mock.onGet(ENDPOINTS.manager.mlStats).reply(
      200,
      makeEnvelope({
        model: {
          active_version: 'v2.1',
          status: 'production',
          is_production: true,
          algorithm: 'isolation_forest',
          deployed_at: '2026-10-01T00:00:00+00:00',
          trained_by: 'ml-ops',
        },
        versions: [
          {
            version: 'v2.1',
            status: 'production',
            is_production: true,
            inferences: 1200,
          },
        ],
        inference: {
          total: 1200,
          anomalies: 48,
          anomaly_rate: 0.04,
          avg_processing_ms: 12.4,
          p95_processing_ms: 18.9,
          errors: 3,
          degraded: 1,
        },
        by_status: { ok: 1196, degraded: 1, error: 3 },
        reason_codes: [],
        daily: [],
        features: [
          {
            feature_name: 'deviation_score',
            count: 1200,
            mean: 0.42,
            std: 0.11,
            min: 0.01,
            max: 0.98,
            p25: 0.33,
            p50: 0.41,
            p75: 0.5,
            p95: 0.71,
            anomaly_rate: 0.04,
          },
        ],
      }),
    )

    renderPage(<ManagerMlStatsPage />, '/manager/ml-stats')

    expect((await screen.findAllByText('v2.1')).length).toBeGreaterThan(0)
    expect(screen.getByText('isolation_forest')).toBeInTheDocument()
    expect(screen.getAllByText('1200').length).toBeGreaterThan(0)
    expect(screen.getByText('deviation_score')).toBeInTheDocument()
  })
})
