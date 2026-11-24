/**
 * S-30 / S-31 / S-32 — Detection policy API calls.
 *
 * The Core-owned detection configuration, gated by role on every route:
 *
 *   - `GET  /policies`        → SECURITY_ADMIN | SECURITY_MANAGER
 *   - `GET  /policies/{id}`   → SECURITY_ADMIN | SECURITY_MANAGER
 *   - `POST /policies`        → SECURITY_ADMIN
 *   - `PUT  /policies/{id}`   → SECURITY_ADMIN
 *   - `POST /policies/{id}/activate` → SECURITY_ADMIN
 *
 * The contracts that shape these signatures:
 *
 *   - **The listing endpoint returns a SUMMARY.** It carries `id`,
 *     `version`, `name`, `description`, `rule_count`, `is_active`,
 *     `created_at` and `activated_at` — but NOT the rules and NOT the
 *     config. A client that wants to edit a policy has to read the
 *     detail endpoint first, because that is where `updated_at` lives.
 *
 *   - **`expected_updated_at` is mandatory on an edit.** It is the
 *     optimistic-concurrency token: the client sends back the
 *     `updated_at` it last read and the backend answers 409 when the
 *     policy changed in the meantime. The value must stay a STRING —
 *     the backend compares microsecond-precision instants and a `Date`
 *     round-trip would trigger spurious conflicts.
 *
 *   - **A policy that has ever been active is FROZEN.** The backend
 *     answers 409 "Policy is immutable" for both a currently-active
 *     policy and one that was activated in the past: their rules are
 *     referenced by the risk assessments they produced. The UI freezes
 *     the editor to match, and offers "create a new version" instead.
 *
 *   - **The server owns `is_active`, `created_by` and every timestamp.**
 *     Sending them is a 400 that names the offending field, so the write
 *     payloads never carry them.
 *
 *   - **Activation is a separate, explicit step.** A policy is created
 *     INACTIVE so a half-finished policy can never influence the
 *     scoring of a login.
 */

import { apiGet, apiPost, apiPut } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type {
  PolicyConfig,
  PolicyCreateRequest,
  PolicyDetail,
  PolicyRule,
  PolicySummary,
  PolicyUpdateRequest,
} from '@/types/api'

/**
 * `GET /policies` — the policy summaries, newest first.
 *
 * The backend returns a bare JSON array (not a `{policies, total}`
 * envelope), so the list is returned as-is.
 */
export async function fetchPolicies(): Promise<PolicySummary[]> {
  return apiGet<PolicySummary[]>(ENDPOINTS.policies.list)
}

/**
 * `GET /policies/{policy_id}` — the full policy.
 *
 * This is the only endpoint that exposes the rules, the config and
 * `updated_at`, so it is the one the editor loads.
 */
export async function fetchPolicy(policyId: string): Promise<PolicyDetail> {
  return apiGet<PolicyDetail>(ENDPOINTS.policies.detail(policyId))
}

/**
 * `POST /policies` — create a draft policy.
 *
 * The policy is created INACTIVE; activation is a separate call.
 */
export async function createPolicy(
  payload: PolicyCreateRequest,
): Promise<PolicyDetail> {
  return apiPost<PolicyDetail>(ENDPOINTS.policies.list, payload)
}

/**
 * `PUT /policies/{policy_id}` — edit a draft policy.
 *
 * `expected_updated_at` is mandatory: it is the optimistic-concurrency
 * token that protects the policy against a lost update.
 */
export async function updatePolicy(
  policyId: string,
  payload: PolicyUpdateRequest,
): Promise<PolicyDetail> {
  return apiPut<PolicyDetail>(ENDPOINTS.policies.detail(policyId), payload)
}

/**
 * `POST /policies/{policy_id}/activate` — activate the policy.
 *
 * Only ONE policy may be active at a time; the backend deactivates the
 * current one inside the same transaction.
 */
export async function activatePolicy(policyId: string): Promise<PolicyDetail> {
  return apiPost<PolicyDetail>(ENDPOINTS.policies.activate(policyId))
}

export type { PolicyDetail, PolicySummary, PolicyConfig, PolicyRule }
