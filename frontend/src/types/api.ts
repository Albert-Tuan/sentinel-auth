/**
 * Typed API contracts for Sentinel Auth.
 *
 * These types mirror the live FastAPI OpenAPI schema (v3.3, `origin/dev`
 * @ c89bff5). Field names and optionality are transcribed from
 * `app/schemas.py` and verified by `scripts/check_m12_docs_drift.py`.
 *
 * Rules for this file:
 *  - Tokens are OPAQUE strings. Never decode them, never treat them as JWT.
 *  - Timestamps are ISO-8601 strings with microsecond precision. Keep them as
 *    strings; parsing them to `Date` loses precision and causes spurious 409s
 *    on policy updates.
 */

// ---------------------------------------------------------------------------
// Enums (mirrored from app/schemas.py)
// ---------------------------------------------------------------------------

export const UserRole = {
  USER: 'USER',
  SECURITY_ADMIN: 'SECURITY_ADMIN',
  SOC_ANALYST: 'SOC_ANALYST',
  SECURITY_MANAGER: 'SECURITY_MANAGER',
} as const
export type UserRole = (typeof UserRole)[keyof typeof UserRole]

export const UserStatus = {
  active: 'active',
  suspended: 'suspended',
  locked: 'locked',
} as const
export type UserStatus = (typeof UserStatus)[keyof typeof UserStatus]

export const RiskLevel = {
  low: 'low',
  medium: 'medium',
  high: 'high',
  critical: 'critical',
} as const
export type RiskLevel = (typeof RiskLevel)[keyof typeof RiskLevel]

export const SecurityAction = {
  REQUIRE_MFA: 'REQUIRE_MFA',
  REVOKE_SESSIONS: 'REVOKE_SESSIONS',
  LOCK_USER: 'LOCK_USER',
  FORCE_LOGOUT: 'FORCE_LOGOUT',
} as const
export type SecurityAction = (typeof SecurityAction)[keyof typeof SecurityAction]

/** Alert resolution values, constrained by the backend regex. */
export const AlertResolution = {
  true_attack: 'true_attack',
  false_positive: 'false_positive',
  benign_true_positive: 'benign_true_positive',
  insufficient_evidence: 'insufficient_evidence',
} as const
export type AlertResolution = (typeof AlertResolution)[keyof typeof AlertResolution]

/**
 * The four canonical alert statuses.
 *
 * Mirrors `app/alerts.py::ALERT_STATUSES` and the `chk_alerts_status`
 * CHECK constraint. `ESCALATED` is deliberately NOT a status: escalation
 * is recorded as an `alert_timeline` event instead.
 */
export const AlertStatus = {
  open: 'open',
  acknowledged: 'acknowledged',
  resolved: 'resolved',
  false_positive: 'false_positive',
} as const
export type AlertStatus = (typeof AlertStatus)[keyof typeof AlertStatus]

/**
 * The canonical timeline event types.
 *
 * Mirrors `app/alerts.py::TIMELINE_EVENT_TYPES` and the
 * `alert_timeline.event_type` CHECK constraint.
 */
export const TimelineEventType = {
  created: 'created',
  assigned: 'assigned',
  unassigned: 'unassigned',
  acknowledged: 'acknowledged',
  escalated: 'escalated',
  note_added: 'note_added',
  status_changed: 'status_changed',
  resolved: 'resolved',
  false_positive: 'false_positive',
} as const
export type TimelineEventType = (typeof TimelineEventType)[keyof typeof TimelineEventType]

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  /** Empty string when `mfa_required` is true. */
  access_token: string
  /** Empty string when `mfa_required` is true. */
  refresh_token: string
  mfa_required: boolean
  /**
   * When `mfa_required` is true this is the MfaTransaction id (NOT an
   * authenticated session id). It must be echoed back to
   * `POST /auth/mfa/verify`.
   */
  session_id: string | null
}

export interface MfaVerifyRequest {
  session_id: string
  /** Exactly 6 digits — the backend enforces `^\d{6}$`. */
  mfa_code: string
}

export interface MfaVerifyResponse {
  access_token: string
  refresh_token: string
  /** The real authenticated session id. */
  session_id: string
}

export interface RefreshRequest {
  refresh_token: string
}

export interface RefreshResponse {
  access_token: string
  refresh_token: string
}

export interface LogoutResponse {
  /**
   * The backend's literal value. `LogoutResponse.status` defaults to "ok"
   * and both `/auth/logout` and `/auth/logout-all` return exactly that.
   */
  status: string
}

export interface UserRegisterRequest {
  username: string
  email: string
  password: string
}

export interface UserRegisterResponse {
  user_id: string
  username: string
  email: string
  status: UserStatus
  admin_mfa_required: boolean
  roles: UserRole[]
  message: string
}

/** `GET /auth/me` — the canonical source of the current user's roles. */
export interface CurrentUser {
  id: string
  username: string
  email: string
  full_name: string | null
  status: UserStatus
  admin_mfa_required: boolean
  roles: UserRole[]
  last_login_at: string | null
  failed_login_count: number
  locked_at: string | null
  created_at: string
}

export interface SessionItem {
  id: string
  ip_address: string | null
  user_agent: string | null
  expires_at: string
  last_activity_at: string | null
  created_at: string
  is_current: boolean
}

export interface SessionList {
  sessions: SessionItem[]
  total: number
}

// ---------------------------------------------------------------------------
// Trusted devices
// ---------------------------------------------------------------------------

export interface TrustedDeviceItem {
  id: string
  device_name: string | null
  /** The hashed device fingerprint. Never a raw fingerprint. */
  device_fingerprint: string
  last_ip: string | null
  last_user_agent: string | null
  last_used_at: string
  /** Null means the device never expires. */
  expires_at: string | null
  created_at: string
}

export interface TrustedDeviceList {
  devices: TrustedDeviceItem[]
  total: number
}

export interface TrustDeviceRequest {
  /** At most 100 characters — the backend enforces `max_length=100`. */
  device_name?: string | null
  /** 1..365, default 30 on the backend. */
  remember_for_days?: number | null
}

export interface TrustDeviceResponse {
  id: string
  device_name: string | null
  message: string
}

export interface PendingTrustedDeviceRequest {
  username: string
  password: string
  device_name?: string | null
}

export interface PendingTrustedDeviceResponse {
  request_id: string
  /** `pending` | `already_trusted`. */
  status: string
  expires_at: string
  message: string
}

export interface TrustedDeviceApprovalResponse {
  request_id: string
  device_id: string
  /** Always `approved`. */
  status: string
  expires_at: string
}

/**
 * `POST /devices/check` — optional authentication.
 *
 * A missing or invalid token is NOT an error: the answer is simply
 * `trusted: false`.
 */
export interface DeviceTrustCheckResponse {
  trusted: boolean
  reason: string
}

// ---------------------------------------------------------------------------
// Admin / IAM
// ---------------------------------------------------------------------------

export interface AdminUserItem {
  id: string
  username: string
  email: string
  full_name: string | null
  status: UserStatus
  admin_mfa_required: boolean
  roles: UserRole[]
  last_login_at: string | null
  failed_login_count: number
  locked_at: string | null
  created_at: string
}

export interface AdminUserList {
  users: AdminUserItem[]
  total: number
  page: number
  limit: number
}

/**
 * One row of `GET /admin/audit-logs`.
 *
 * Mirrors `app/schemas.py::AuditLogItem`. `actor` is the USERNAME of the
 * account that caused the change, or `system` for an entry no user
 * caused — it is NOT a user id.
 */
export interface AuditLogItem {
  id: string
  request_id: string | null
  /** The username, or `system` for an entry no user caused. */
  actor: string
  action: string
  resource: string
  resource_id: string | null
  before_state: Record<string, unknown> | null
  after_state: Record<string, unknown> | null
  change_reason: string | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

export interface AuditLogList {
  logs: AuditLogItem[]
  total: number
  page: number
  limit: number
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export interface AlertItem {
  id: string
  /** Never null — the backend declares it NOT NULL. */
  login_attempt_id: string
  policy_id: string | null
  status: AlertStatus | string
  /** Null when the alert has not been risk-scored. */
  risk_level: RiskLevel | string | null
  detection_reason: string | null
  /**
   * Free-form score map. Null when the backend stored no scores at all —
   * which is NOT the same as an empty map, and NOT the same as a score of
   * zero.
   */
  detection_scores: Record<string, unknown> | null
  /** The `soc_analysts.id` UUID, NOT a `users.id`. */
  assigned_to_id: string | null
  resolved_by_id: string | null
  resolved_at: string | null
  resolution: AlertResolution | string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface AlertListResponse {
  alerts: AlertItem[]
  total: number
  page: number
  limit: number
}

/**
 * The login attempt behind an alert, as the evidence bundle reports it.
 *
 * Every optional field is genuinely nullable: the attempt may have been
 * recorded without a username, an IP or a user id.
 */
export interface LoginAttemptSummary {
  id: string
  event_id: string
  timestamp: string
  outcome: string
  username_attempted: string | null
  ip_address: string | null
  user_agent: string | null
  user_id: string | null
  mfa_used: boolean
  risk_level: RiskLevel | string | null
  detection_decision: string | null
}

/**
 * The risk assessment behind an alert.
 *
 * Every field is nullable, and the nullability is MEANINGFUL:
 *   - `ml_score: null` means the ML engine produced no score (rule-only
 *    fallback, or the model was unavailable). It is NOT a score of zero.
 *   - `ml_status` explains the fallback: e.g. `fallback`, `unavailable`.
 *   - `rule_score: null` means no rule produced a score at all.
 *   - `combined_score: null` means the two could not be combined.
 *
 * The UI must never invent an ML score where the backend returned null.
 */
export interface RiskAssessmentSummary {
  rule_score: number | null
  ml_score: number | null
  combined_score: number | null
  /** e.g. `ok`, `fallback`, `unavailable`, `skipped`. */
  ml_status: string | null
  ml_model_version: string | null
  ml_reason_codes: unknown[] | null
  ml_features_used: Record<string, unknown> | null
  rule_hits: unknown[] | null
  risk_level: RiskLevel | string | null
  decision: string | null
}

/** One row of the detection pipeline log. */
export interface DetectionLogSummary {
  id: string
  stage: string
  stage_detail: string | null
  rule_name: string | null
  /** Null when the stage did not record a verdict. */
  triggered: boolean | null
  /** Null when the stage contributed nothing to the score. */
  score_contribution: number | null
  decision: string | null
  reason: string | null
  details: Record<string, unknown> | null
  created_at: string
}

/**
 * The full evidence bundle of one alert.
 *
 * `login_attempt` and `risk_assessment` are null when the underlying
 * record does not exist — the alert still renders, without that section.
 */
export interface AlertEvidence {
  alert: AlertItem
  login_attempt: LoginAttemptSummary | null
  risk_assessment: RiskAssessmentSummary | null
  detection_logs: DetectionLogSummary[]
  timeline: TimelineEvent[]
}

export interface AlertAcknowledgeRequest {
  notes?: string | null
}

export interface AlertResolveRequest {
  resolution: AlertResolution
  notes?: string | null
}

export interface AlertAssignRequest {
  assigned_to_id: string
  notes?: string | null
}

export interface AlertActionRequest {
  action: SecurityAction
  /**
   * The reason of the action.
   *
   * The backend REQUIRES it (`AlertActionRequest.reason` is
   * `Field(..., min_length=1)`), so an empty reason is rejected with a
   * 422 before the action is ever dispatched to Core.  The type says so,
   * because a nullable reason here would only produce a request the
   * server is bound to refuse.
   */
  reason: string
}

export interface AlertActionResponse {
  status: string
  action: string
  details: Record<string, unknown> | null
}

export interface TimelineEventCreate {
  event_type: TimelineEventType | string
  /** No server-side length limit; the UI caps it at 2000 characters. */
  comment?: string | null
}

export interface TimelineEvent {
  id: string
  alert_id: string
  event_type: string
  /** Null when the event has no actor (e.g. a system-generated event). */
  actor_id: string | null
  /** `user` | `system` | … — defaults to `user` on the backend. */
  actor_type: string
  old_value: string | null
  new_value: string | null
  comment: string | null
  ip_address: string | null
  created_at: string
}

// ---------------------------------------------------------------------------
// Policies
// ---------------------------------------------------------------------------

/**
 * One detection rule, exactly as the backend stores it.
 *
 * The backend keeps the rules as free-form JSON (`List[Dict[str, Any]]`),
 * so the shape is validated by the SERVER, not by the type. The optional
 * fields below mirror the canonical `RuleDefinition` schema in
 * `app/schemas.py`; the editor sends all of them.
 */
export interface PolicyRule {
  /** Unique within the policy — the backend rejects a duplicate name. */
  name: string
  /** One of the 6 detection features (`ip_address`, `hour_of_day`, …). */
  field: string
  /** One of `== != > >= < <= in between not_between`. */
  operator: string
  /** A scalar, or `[min, max]` for a range operator, or a list for `in`. */
  value: unknown
  /** Rule confidence, 0..1. */
  weight: number
  /** Severity when the rule triggers, 0..1. */
  score: number
  enabled: boolean
  description?: string | null
}

/** The scoring weights of a policy. `rule + ml` must sum to 1.0. */
export interface PolicyWeights {
  rule: number
  ml: number
}

/** The risk-level boundaries of a policy. Must be non-decreasing. */
export interface PolicyThresholds {
  low: number
  medium: number
  high: number
}

/** The `config` blob of a policy. */
export interface PolicyConfig {
  weights: PolicyWeights
  thresholds: PolicyThresholds
}

/**
 * One row of `GET /policies`.
 *
 * The listing endpoint returns a SUMMARY on purpose: it does NOT expose
 * the rules and does NOT expose the config. `rule_count` is the count of
 * the rules, and the rules themselves are only reachable through the
 * detail endpoint.
 */
export interface PolicySummary {
  id: string
  version: string
  name: string | null
  description: string | null
  rule_count: number
  is_active: boolean
  created_at: string
  activated_at: string | null
}

/**
 * The full policy, as returned by the detail / create / edit endpoints.
 *
 * `updated_at` is the optimistic-concurrency token: an edit has to send
 * it back as `expected_updated_at`.
 */
export interface PolicyDetail {
  id: string
  version: string
  name: string | null
  description: string | null
  rules: PolicyRule[]
  config: Partial<PolicyConfig>
  is_active: boolean
  created_by: string | null
  created_at: string
  updated_at: string
  activated_at: string | null
  deactivated_at: string | null
}

export interface PolicyUpdateRequest {
  name?: string
  description?: string
  rules?: PolicyRule[]
  config?: Partial<PolicyConfig>
  /**
   * The `updated_at` string exactly as returned by the backend. Must stay a
   * string — the backend compares microsecond-precision values and a
   * `Date` round-trip causes spurious 409 conflicts.
   */
  expected_updated_at?: string
}

export interface PolicyCreateRequest {
  version: string
  name?: string | null
  description?: string | null
  rules: PolicyRule[]
  config: Partial<PolicyConfig>
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------

export interface TrustDeviceRequest {
  device_name?: string | null
  remember_for_days?: number | null
}

export interface PendingTrustedDeviceRequest {
  username: string
  password: string
  device_name?: string | null
}

export interface PendingTrustedDeviceResponse {
  request_id: string
  status: string
  expires_at: string
  message: string
}

// ---------------------------------------------------------------------------
// Login history
// ---------------------------------------------------------------------------

/**
 * One row of `GET /login-attempts`.
 *
 * The timestamp field is `timestamp` (not `created_at`): the backend
 * reports the moment of the attempt.
 */
export interface LoginAttemptItem {
  id: string
  event_id: string
  user_id: string | null
  username_attempted: string | null
  ip_address: string | null
  user_agent: string | null
  device_fingerprint: string | null
  outcome: string
  mfa_used: boolean
  timestamp: string
  status: string
  risk_level: RiskLevel | string | null
  detection_decision: string | null
  policy_id: string | null
  primary_alert_id: string | null
  request_id: string | null
}

export interface LoginAttemptListResponse {
  attempts: LoginAttemptItem[]
  total: number
  page: number
  limit: number
}

// ---------------------------------------------------------------------------
// IAM — extra contracts
// ---------------------------------------------------------------------------

/**
 * The role enum as the API names it.
 *
 * `UserRole` (above) is the SAME vocabulary; this alias exists because
 * `AdminUserItem.roles` is typed with it, and the IAM API module needs a
 * name that cannot be confused with the auth context's role union.
 */
export type UserRoleEnum =
  | 'USER'
  | 'SECURITY_ADMIN'
  | 'SOC_ANALYST'
  | 'SECURITY_MANAGER'

export interface RoleAssignRequest {
  role: UserRoleEnum
}

export interface MfaToggleRequest {
  mfa_required: boolean
}

// ---------------------------------------------------------------------------
// Manager analytics
// ---------------------------------------------------------------------------

/**
 * The availability of one analytics source.
 *
 * `detail` is a CLOSED reason code from the backend (`timeout`,
 * `database_error`, `invalid_payload`, …) — never free text to guess at.
 */
export interface ManagerSourceStatus {
  status: 'ok' | 'unavailable'
  detail?: string | null
}

/** The window the backend actually used, echoed back to the caller. */
export interface ManagerWindow {
  from: string
  to: string
}

/**
 * The envelope shared by every Manager response.
 *
 * `degraded` means SOME source was unavailable — the payload is still
 * valid, but the sections that depend on the missing source are `null`.
 */
export interface ManagerEnvelope {
  generated_at: string
  window: ManagerWindow
  degraded: boolean
  sources: Record<string, ManagerSourceStatus>
}

export interface ManagerCriticalIncidentSubject {
  username?: string | null
  user_id?: string | null
}

export interface ManagerCriticalIncident {
  alert_id: string
  risk_level: string
  status: string
  created_at: string
  subject?: ManagerCriticalIncidentSubject | null
  detection_reason?: string | null
  combined_score?: number | null
  assigned_to?: string | null
  age_hours?: number | null
}

export interface ManagerActivePolicy {
  active_version?: string | null
  active_policy_id?: string | null
}

export interface ManagerAuditActivityRow {
  id: string
  action: string
  actor?: string | null
  resource?: string | null
  resource_id?: string | null
  created_at: string
}

export interface ManagerAuditActivity {
  by_action: Record<string, number>
  by_actor_type: Record<string, number>
  recent: ManagerAuditActivityRow[]
}

export interface ManagerDashboardCore {
  total_users: number
  users_by_status: Record<string, number>
  users_with_mfa_required: number
  users_under_forced_mfa: number
  new_users: number
  users_with_failed_logins: number
  active_sessions: number
  sessions_created: number
  sessions_revoked: number
  mfa_challenges: number
  mfa_completed: number
  mfa_failed: number
  audit_events: number
  audit_activity?: ManagerAuditActivity | null
}

export interface ManagerDashboardAlerts {
  total: number
  open: number
  acknowledged: number
  resolved: number
  false_positive: number
  critical_open: number
}

export interface ManagerEnforcementStats {
  attempted: number
  succeeded: number
  success_rate?: number | null
}

export interface ManagerMlFallbackStats {
  assessments: number
  fallback: number
  fallback_rate?: number | null
}

export interface ManagerDashboardDetection {
  login_attempts: number
  by_outcome: Record<string, number>
  by_risk_level: Record<string, number>
  by_decision: Record<string, number>
  avg_combined_score?: number | null
  alerts: ManagerDashboardAlerts
  critical_incidents: ManagerCriticalIncident[]
  enforcement?: ManagerEnforcementStats | null
  ml_fallback?: ManagerMlFallbackStats | null
  policy?: ManagerActivePolicy | null
}

export interface ManagerMlDailyPoint {
  day: string
  total: number
  anomalies: number
  successful: number
  errors: number
  degraded: number
  avg_processing_ms?: number | null
  avg_anomaly_score?: number | null
}

export interface ManagerDashboardMl {
  active_model_version?: string | null
  model_status: string
  inferences: number
  anomalies: number
  anomaly_rate?: number | null
  avg_processing_ms?: number | null
  daily: ManagerMlDailyPoint[]
}

export interface ManagerDashboardResponse extends ManagerEnvelope {
  core?: ManagerDashboardCore | null
  detection?: ManagerDashboardDetection | null
  ml?: ManagerDashboardMl | null
}

export interface ManagerTrendPoint {
  bucket_start: string
  total: number
  by_outcome: Record<string, number>
  by_risk_level: Record<string, number>
  avg_combined_score?: number | null
}

export interface ManagerTrendAlertsPoint {
  bucket_start: string
  total: number
  by_status: Record<string, number>
}

export interface ManagerTrendMlPoint {
  bucket_start: string
  total: number
  anomalies: number
  successful: number
  errors: number
  degraded: number
  avg_processing_ms?: number | null
  avg_anomaly_score?: number | null
}

export interface ManagerTrendSeries {
  login_attempts?: ManagerTrendPoint[] | null
  alerts?: ManagerTrendAlertsPoint[] | null
  ml?: ManagerTrendMlPoint[] | null
}

export interface ManagerTrendsResponse extends ManagerEnvelope {
  bucket: string
  series: ManagerTrendSeries
}

export interface ManagerAlertTotals {
  created: number
  open: number
  acknowledged: number
  resolved: number
  false_positive: number
}

export interface ManagerAlertBacklog {
  open_count: number
  oldest_open_age_hours?: number | null
  unassigned: number
  escalated: number
}

export interface ManagerAlertsResponse extends ManagerEnvelope {
  totals: ManagerAlertTotals
  by_status: Record<string, number>
  by_risk_level: Record<string, number>
  by_rule: Array<Record<string, unknown>>
  by_ml_reason: Array<Record<string, unknown>>
  backlog: ManagerAlertBacklog
  false_positive_rate?: number | null
  mtta_seconds?: number | null
  mttr_seconds?: number | null
  acknowledged_count: number
  resolved_count: number
}

/**
 * Every KPI is nullable.
 *
 * A KPI over an empty population is `null`; a KPI whose source is down is
 * also `null`. A `null` is NEVER rendered as a zero.
 */
export interface ManagerSocKpis {
  mtta_seconds?: number | null
  mttr_seconds?: number | null
  acknowledgement_rate?: number | null
  resolution_rate?: number | null
  false_positive_rate?: number | null
  escalation_rate?: number | null
  alerts_per_analyst?: number | null
  enforcement_attempted?: number | null
  enforcement_succeeded?: number | null
  enforcement_success_rate?: number | null
  ml_assessments?: number | null
  ml_fallback_count?: number | null
  ml_fallback_rate?: number | null
  mfa_enrollment_rate?: number | null
  forced_mfa_users?: number | null
  audit_events?: number | null
}

export interface ManagerSocKpiResponse extends ManagerEnvelope {
  kpis: ManagerSocKpis
}

export interface ManagerMlModelInfo {
  active_version?: string | null
  status?: string | null
  is_production: boolean
  algorithm?: string | null
  deployed_at?: string | null
  trained_by?: string | null
}

export interface ManagerMlVersionInfo {
  version: string
  status: string
  is_production: boolean
  training_date?: string | null
  inferences: number
}

export interface ManagerMlInferenceStats {
  total: number
  anomalies: number
  anomaly_rate?: number | null
  avg_normalized_score?: number | null
  avg_processing_ms?: number | null
  p95_processing_ms?: number | null
  errors: number
  degraded: number
}

export interface ManagerMlFeaturePoint {
  feature_name: string
  count: number
  mean?: number | null
  std?: number | null
  min?: number | null
  max?: number | null
  p25?: number | null
  p50?: number | null
  p75?: number | null
  p95?: number | null
  anomaly_rate?: number | null
  timestamp?: string | null
}

export interface ManagerMlStatsResponse extends ManagerEnvelope {
  model?: ManagerMlModelInfo | null
  versions: ManagerMlVersionInfo[]
  inference: ManagerMlInferenceStats
  by_status: Record<string, number>
  reason_codes: Array<Record<string, unknown>>
  daily: ManagerMlDailyPoint[]
  features: ManagerMlFeaturePoint[]
}

// ---------------------------------------------------------------------------
// Shared pagination
// ---------------------------------------------------------------------------

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  limit: number
}

export interface WindowQuery {
  from?: string
  to?: string
  page?: number
  limit?: number
}
