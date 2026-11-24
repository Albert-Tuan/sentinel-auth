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

export interface AuditLogItem {
  id: string
  actor_id: string | null
  actor_type: string | null
  action: string
  resource: string | null
  resource_id: string | null
  before_state: Record<string, unknown> | null
  after_state: Record<string, unknown> | null
  ip_address: string | null
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
  reason?: string | null
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

export interface RuleDefinition {
  type: string
  [key: string]: unknown
}

export interface PolicyUpdateRequest {
  name?: string
  description?: string
  rules?: RuleDefinition[]
  config?: Record<string, unknown>
  /**
   * The `updated_at` string exactly as returned by the backend. Must stay a
   * string — the backend compares microsecond-precision values and a
   * `Date` round-trip causes spurious 409 conflicts.
   */
  expected_updated_at?: string
}

export interface PolicyCreateRequest {
  version: string
  name: string
  description?: string
  rules: RuleDefinition[]
  config: Record<string, unknown>
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
