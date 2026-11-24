/**
 * Trusted-device API calls.
 *
 * These calls use the shared `apiClient` so the refresh interceptor applies.
 *
 * Two of the endpoints are deliberately PUBLIC:
 *  - `POST /devices/pending`            — proves the password, no session yet.
 *  - `POST /devices/pending/{id}/complete` — exchanges an approved request
 *    for real session tokens.
 *
 * Neither may go through the refresh path: a 401 from them means "wrong
 * credentials" or "not approved yet", not "expired token". They are
 * therefore called with `_skipRefresh`, and their paths are on the client's
 * no-refresh list.
 */

import { apiClient, apiDelete, apiGet, apiPost } from '@/lib/api/client'
import { ENDPOINTS } from '@/lib/api/endpoints'
import type {
  DeviceTrustCheckResponse,
  LoginResponse,
  PendingTrustedDeviceRequest,
  PendingTrustedDeviceResponse,
  TrustDeviceRequest,
  TrustDeviceResponse,
  TrustedDeviceApprovalResponse,
  TrustedDeviceList,
} from '@/types/api'

/** `GET /devices` — the current user's trusted devices. */
export async function fetchTrustedDevices(): Promise<TrustedDeviceList> {
  return apiGet<TrustedDeviceList>(ENDPOINTS.devices.list)
}

/**
 * `POST /devices` — trust the current device.
 *
 * The backend binds the request to the session's familiar IP and returns
 * 403 when it does not match.
 */
export async function trustDevice(
  request: TrustDeviceRequest,
): Promise<TrustDeviceResponse> {
  return apiPost<TrustDeviceResponse>(ENDPOINTS.devices.register, request)
}

/** `DELETE /devices/{device_id}` — untrust one device. */
export async function untrustDevice(deviceId: string): Promise<void> {
  await apiDelete<void>(ENDPOINTS.devices.remove(deviceId))
}

/** `DELETE /devices/all` — revoke every trusted device of the current user. */
export async function untrustAllDevices(): Promise<void> {
  await apiDelete<void>(ENDPOINTS.devices.removeAll)
}

/**
 * `POST /devices/check` — is this device trusted?
 *
 * Optional authentication: with no token the backend answers
 * `{ trusted: false, reason: "No token" }` instead of 401.
 */
export async function checkDeviceTrusted(): Promise<DeviceTrustCheckResponse> {
  return apiPost<DeviceTrustCheckResponse>(ENDPOINTS.devices.check, {})
}

/**
 * `POST /devices/pending` — ask an already-signed-in device to approve this
 * one. PUBLIC: the caller has no session yet.
 */
export async function requestTrustedDeviceApproval(
  request: PendingTrustedDeviceRequest,
): Promise<PendingTrustedDeviceResponse> {
  return apiPost<PendingTrustedDeviceResponse>(
    ENDPOINTS.devices.pending,
    request,
    { _skipRefresh: true } as never,
  )
}

/**
 * `POST /devices/pending/{request_id}/approve` — approve the request from a
 * signed-in session.
 */
export async function approveTrustedDevice(
  requestId: string,
): Promise<TrustedDeviceApprovalResponse> {
  return apiPost<TrustedDeviceApprovalResponse>(
    ENDPOINTS.devices.pendingApprove(requestId),
    {},
  )
}

/**
 * `POST /devices/pending/{request_id}/complete` — exchange an approved
 * request for real session tokens. PUBLIC: the caller has no session yet.
 *
 * A 409 `still pending` is the normal "keep polling" answer, not an error
 * the user should see.
 */
export async function completeTrustedDeviceLogin(
  requestId: string,
): Promise<LoginResponse> {
  return apiPost<LoginResponse>(
    ENDPOINTS.devices.pendingComplete(requestId),
    {},
    { _skipRefresh: true } as never,
  )
}

/**
 * Raw axios access for the pending-approval calls.
 *
 * The pending flow must be able to distinguish "still pending" (409) from a
 * real failure, and it must never trigger a refresh, so it bypasses the
 * typed helpers.
 */
export async function rawPendingComplete(requestId: string) {
  return apiClient.post<LoginResponse>(
    ENDPOINTS.devices.pendingComplete(requestId),
    {},
    { _skipRefresh: true } as never,
  )
}
