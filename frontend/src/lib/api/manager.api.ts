/**
 * S-40 … S-44 — Manager analytics API calls.
 *
 * The Manager facade aggregates several upstreams (Core, Detection, ML)
 * behind five read-only endpoints. Three contracts shape these
 * signatures:
 *
 *   1. **Every response carries the same envelope.** `generated_at`,
 *      `window` (the window actually used, echoed back), `degraded` and
 *      `sources` (the availability of each upstream). The screen always
 *      shows the effective window, because the backend applies a DEFAULT
 *      window when the caller sends none — a manager must be able to
 *      tell "last 24 hours" from "last 14 days".
 *
 *   2. **`degraded` is NOT an error.** It means SOME source was
 *      unavailable. The payload is still valid and the sections that
 *      could be computed are present, while the others are `null`. A
 *      manager reading a degraded dashboard must see WHICH source is
 *      down, not a generic error.
 *
 *   3. **A 503 means EVERY source failed.** The body is NOT the
 *      endpoint's response model: it is
 *      `{"detail": "analytics sources unavailable", "sources": {...}}`.
 *      There is nothing to render, so the screen shows the failure
 *      state with the per-source reasons.
 *
 * The window parameters (`from`, `to`, `bucket`) are sent only when
 * they carry a value. An empty `from` would be sent as an empty
 * string, which the backend answers 400 for.
 */

import { apiGet } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type {
  ManagerAlertsResponse,
  ManagerDashboardResponse,
  ManagerMlStatsResponse,
  ManagerSocKpiResponse,
  ManagerTrendsResponse,
} from '@/types/api'

/** The buckets the backend accepts. */
export const MANAGER_BUCKETS = ['auto', 'hour', 'day'] as const
export type ManagerBucket = (typeof MANAGER_BUCKETS)[number]

/** The alert statuses the `/manager/alerts` filter accepts. */
export const MANAGER_ALERT_STATUSES = [
  'open',
  'acknowledged',
  'resolved',
  'false_positive',
] as const
export type ManagerAlertStatus = (typeof MANAGER_ALERT_STATUSES)[number]

/** The risk levels the `/manager/alerts` filter accepts. */
export const MANAGER_RISK_LEVELS = [
  'low',
  'medium',
  'high',
  'critical',
] as const
export type ManagerRiskLevel = (typeof MANAGER_RISK_LEVELS)[number]

/** The window and filter parameters shared by the analytics endpoints. */
export interface ManagerWindowQuery {
  from?: string
  to?: string
  bucket?: ManagerBucket
  status?: ManagerAlertStatus
  riskLevel?: string
}

/**
 * `GET /manager/dashboard` — the overview (S-40).
 *
 * The default window is 24 hours.
 */
export async function fetchManagerDashboard(
  query: ManagerWindowQuery = {},
): Promise<ManagerDashboardResponse> {
  return apiGet<ManagerDashboardResponse>(ENDPOINTS.manager.dashboard, {
    params: {
      from: query.from || undefined,
      to: query.to || undefined,
    },
  })
}

/**
 * `GET /manager/trends` — the time series (S-41).
 *
 * The default window is 14 days. `bucket=auto` (the default) resolves
 * to `hour` for a window up to 72 hours and `day` beyond that.
 */
export async function fetchManagerTrends(
  query: ManagerWindowQuery = {},
): Promise<ManagerTrendsResponse> {
  return apiGet<ManagerTrendsResponse>(ENDPOINTS.manager.trends, {
    params: {
      from: query.from || undefined,
      to: query.to || undefined,
      bucket: query.bucket || undefined,
    },
  })
}

/**
 * `GET /manager/alerts` — the alert analytics (S-42).
 *
 * The default window is 30 days. `status` and `risk_level` filter the
 * population the numbers are computed over.
 */
export async function fetchManagerAlerts(
  query: ManagerWindowQuery = {},
): Promise<ManagerAlertsResponse> {
  return apiGet<ManagerAlertsResponse>(ENDPOINTS.manager.alerts, {
    params: {
      from: query.from || undefined,
      to: query.to || undefined,
      status: query.status || undefined,
      risk_level: query.riskLevel || undefined,
    },
  })
}

/**
 * `GET /manager/soc-kpi` — the SOC KPI set (S-43).
 *
 * The default window is 30 days. Every KPI is nullable: a KPI over an
 * empty population is `null`, and a KPI whose source is down is also
 * `null`. The screen renders "không có dữ liệu" for a `null`, never a
 * zero.
 */
export async function fetchManagerSocKpi(
  query: ManagerWindowQuery = {},
): Promise<ManagerSocKpiResponse> {
  return apiGet<ManagerSocKpiResponse>(ENDPOINTS.manager.socKpi, {
    params: {
      from: query.from || undefined,
      to: query.to || undefined,
    },
  })
}

/**
 * `GET /manager/ml-stats` — the ML statistics (S-44).
 *
 * The default window is 30 days.
 */
export async function fetchManagerMlStats(
  query: ManagerWindowQuery = {},
): Promise<ManagerMlStatsResponse> {
  return apiGet<ManagerMlStatsResponse>(ENDPOINTS.manager.mlStats, {
    params: {
      from: query.from || undefined,
      to: query.to || undefined,
    },
  })
}

export type {
  ManagerAlertsResponse,
  ManagerDashboardResponse,
  ManagerMlStatsResponse,
  ManagerSocKpiResponse,
  ManagerTrendsResponse,
}
