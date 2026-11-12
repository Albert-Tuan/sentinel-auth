/**
 * S-04 — the trusted-device login flow.
 *
 * The flow is: request approval (202) → poll for completion → tokens.
 *
 * The poll has to distinguish three outcomes:
 *   - 200 → real tokens, the user is signed in.
 *   - 409 "still pending" → keep polling (NOT an error).
 *   - 409 "MFA required" → the risk gate wins, the user must use the
 *     normal login flow.
 *
 * A failure to tell those apart is the classic bug here: showing an error
 * while the approval is still in flight, or signing the user in with an
 * empty token.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MockAdapter from 'axios-mock-adapter'

import { apiClient, __resetClientState } from '@/lib/api/client'
import { __resetStore, getAccessToken } from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { renderWithProviders } from '@/test/renderApp'
import { makeUser } from '@/test/fixtures'

import { TrustedDeviceLoginPage } from '@/features/devices/pages/TrustedDeviceLoginPage'

const REQUEST_ID = 'cccccccc-0000-0000-0000-000000000001'

let mock: MockAdapter

beforeEach(() => {
  __resetStore()
  __resetClientState()
  mock = new MockAdapter(apiClient)
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

describe('S-04 trusted-device login', () => {
  it('reports invalid credentials without polling', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(401, {
      detail: 'Invalid credentials',
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'wrong')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )

    expect(
      await screen.findByText('Tên đăng nhập hoặc mật khẩu không đúng.'),
    ).toBeInTheDocument()
  })

  it('tells the user to use the normal flow when MFA is required', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(409, {
      detail:
        'Complete the required MFA through the normal login flow before trusting a device',
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'm12admin')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )

    expect(await screen.findByText(/xác thực hai yếu tố/i)).toBeInTheDocument()
  })

  it('enters the pending state and polls until the approval completes', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(202, {
      request_id: REQUEST_ID,
      status: 'pending',
      expires_at: '2026-11-11T23:30:00+00:00',
      message: 'Approval is pending on an existing signed-in device',
    })

    let pollCount = 0
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(() => {
      pollCount += 1
      if (pollCount < 2) {
        return [409, { detail: 'Trusted-device approval is still pending' }]
      }
      return [
        200,
        {
          access_token: 'trusted-access-token',
          refresh_token: 'trusted-refresh-token',
          mfa_required: false,
          session_id: 'session-trusted',
        },
      ]
    })

    mock.onGet(ENDPOINTS.auth.me).reply(200, makeUser())

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )

    // The pending state must be shown while the approval is outstanding.
    expect(
      await screen.findByText(/Đang chờ thiết bị đã đăng nhập xác nhận/),
    ).toBeInTheDocument()

    // The first poll answers "still pending" — that must NOT be shown as an
    // error, the flow keeps waiting.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3200)
    })
    await waitFor(() => expect(pollCount).toBeGreaterThanOrEqual(1))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    // The second poll succeeds and the session is installed.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3200)
    })
    await waitFor(() => expect(getAccessToken()).toBe('trusted-access-token'))
  })

  it('never installs a session when the completion returns an empty token', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(202, {
      request_id: REQUEST_ID,
      status: 'pending',
      expires_at: '2026-11-11T23:30:00+00:00',
      message: 'pending',
    })
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(200, {
      access_token: '',
      refresh_token: '',
      mfa_required: false,
      session_id: null,
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )

    await screen.findByText(/Đang chờ thiết bị đã đăng nhập xác nhận/)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3200)
    })

    await waitFor(() =>
      expect(
        screen.getByText('Máy chủ đã phản hồi nhưng không cấp token hợp lệ.'),
      ).toBeInTheDocument(),
    )
    expect(getAccessToken()).toBeNull()
  })

  it('stops polling and explains when the risk gate demands MFA', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(202, {
      request_id: REQUEST_ID,
      status: 'pending',
      expires_at: '2026-11-11T23:30:00+00:00',
      message: 'pending',
    })
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(409, {
      detail: 'Detection requires MFA for this login',
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )

    await screen.findByText(/Đang chờ thiết bị đã đăng nhập xác nhận/)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3200)
    })

    expect(
      await screen.findByText(/Hệ thống phát hiện rủi ro hoặc yêu cầu xác thực/),
    ).toBeInTheDocument()
    expect(getAccessToken()).toBeNull()
  })

  it('polls on a 3 second interval while the approval is still pending', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(202, {
      request_id: REQUEST_ID,
      status: 'pending',
      expires_at: '2026-11-11T23:30:00+00:00',
      message: 'pending',
    })
    let pollCount = 0
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(() => {
      pollCount += 1
      return [409, { detail: 'Trusted-device approval is still pending' }]
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )
    await screen.findByText(/Đang chờ thiết bị đã đăng nhập xác nhận/)

    // Nothing has been polled yet: the first poll is due at t = 3s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2900)
    })
    expect(pollCount).toBe(0)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200)
    })
    await waitFor(() => expect(pollCount).toBe(1))

    // ... and then it keeps going every 3 seconds.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    await waitFor(() => expect(pollCount).toBe(2))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000)
    })
    await waitFor(() => expect(pollCount).toBe(3))
  })

  it('cancels the polling when the page unmounts', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(202, {
      request_id: REQUEST_ID,
      status: 'pending',
      expires_at: '2026-11-11T23:30:00+00:00',
      message: 'pending',
    })
    let pollCount = 0
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(() => {
      pollCount += 1
      return [409, { detail: 'Trusted-device approval is still pending' }]
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    const { unmount } = renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )
    await screen.findByText(/Đang chờ thiết bị đã đăng nhập xác nhận/)

    unmount()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(pollCount).toBe(0)
  })

  it('explains a fingerprint or IP mismatch (403) and stops polling', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(202, {
      request_id: REQUEST_ID,
      status: 'pending',
      expires_at: '2026-11-11T23:30:00+00:00',
      message: 'pending',
    })
    let pollCount = 0
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(() => {
      pollCount += 1
      return [
        403,
        { detail: 'Trusted-device fingerprint does not match the request' },
      ]
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )
    await screen.findByText(/Đang chờ thiết bị đã đăng nhập xác nhận/)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3200)
    })
    expect(
      await screen.findByText(/thiết bị hoặc địa chỉ IP không khớp/),
    ).toBeInTheDocument()

    // The flow is over: no further polling.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(pollCount).toBe(1)
    expect(getAccessToken()).toBeNull()
  })

  it('stops polling when the transaction is no longer valid (410)', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(202, {
      request_id: REQUEST_ID,
      status: 'pending',
      expires_at: '2026-11-11T23:30:00+00:00',
      message: 'pending',
    })
    let pollCount = 0
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(() => {
      pollCount += 1
      return [410, { detail: 'Trusted-device request expired' }]
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )
    await screen.findByText(/Đang chờ thiết bị đã đăng nhập xác nhận/)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3200)
    })
    expect(
      await screen.findByText(/Yêu cầu phê duyệt đã hết hạn/),
    ).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
    })
    expect(pollCount).toBe(1)
  })

  it('does not sign the user in when GET /auth/me rejects the new tokens', async () => {
    mock.onPost(ENDPOINTS.devices.pending).reply(202, {
      request_id: REQUEST_ID,
      status: 'pending',
      expires_at: '2026-11-11T23:30:00+00:00',
      message: 'pending',
    })
    mock.onPost(ENDPOINTS.devices.pendingComplete(REQUEST_ID)).reply(200, {
      access_token: 'trusted-access-token',
      refresh_token: 'trusted-refresh-token',
      mfa_required: false,
      session_id: 'session-trusted',
    })
    // The tokens are issued but `GET /auth/me` refuses them.
    mock.onGet(ENDPOINTS.auth.me).reply(401, { detail: 'Invalid token' })
    mock.onPost(ENDPOINTS.auth.refresh).reply(401, {
      detail: 'Invalid refresh token',
    })

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderWithProviders(<TrustedDeviceLoginPage />)

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'secret')
    await user.click(
      screen.getByRole('button', { name: /Gửi yêu cầu phê duyệt/ }),
    )
    await screen.findByText(/Đang chờ thiết bị đã đăng nhập xác nhận/)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3200)
    })

    expect(
      await screen.findByText(/Không thể xác nhận phiên đăng nhập từ máy chủ/),
    ).toBeInTheDocument()
    expect(getAccessToken()).toBeNull()
  })
})
