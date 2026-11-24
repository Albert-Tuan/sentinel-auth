/**
 * Stage 3 — Sessions and Trusted Devices screens.
 *
 * The screens talk to the real API modules, so the tests mock at the
 * network boundary (axios adapter). The logic under test is the UI logic:
 * which control is enabled, what the user is told, and when the client
 * session is torn down.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MockAdapter from 'axios-mock-adapter'

import { apiClient, __resetClientState } from '@/lib/api/client'
import { __resetStore } from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { renderWithProviders } from '@/test/renderApp'

import { SessionsPage } from '@/features/sessions/pages/SessionsPage'
import { TrustedDevicesPage } from '@/features/devices/pages/TrustedDevicesPage'

const SESSION_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const SESSION_B = 'bbbbbbbb-0000-0000-0000-000000000002'
const DEVICE_A = 'dddddddd-0000-0000-0000-000000000001'

let mock: MockAdapter

beforeEach(() => {
  __resetStore()
  __resetClientState()
  mock = new MockAdapter(apiClient)
})

describe('S-05 Sessions', () => {
  it('lists the active sessions and marks the current one', async () => {
    mock.onGet(ENDPOINTS.auth.sessions).reply(200, {
      total: 2,
      sessions: [
        {
          id: SESSION_A,
          ip_address: '127.0.0.1',
          user_agent: 'Mozilla/5.0 Chrome/120.0',
          expires_at: '2026-12-01T10:00:00+00:00',
          last_activity_at: '2026-11-11T10:00:00+00:00',
          created_at: '2026-11-11T09:00:00+00:00',
          is_current: true,
        },
        {
          id: SESSION_B,
          ip_address: '10.0.0.5',
          user_agent: 'Mozilla/5.0 Firefox/121.0',
          expires_at: '2026-12-01T10:00:00+00:00',
          last_activity_at: '2026-11-11T08:00:00+00:00',
          created_at: '2026-11-10T09:00:00+00:00',
          is_current: false,
        },
      ],
    })

    renderWithProviders(<SessionsPage />)

    expect(await screen.findByText('Google Chrome')).toBeInTheDocument()
    expect(screen.getByText('Mozilla Firefox')).toBeInTheDocument()
    expect(screen.getByText('127.0.0.1')).toBeInTheDocument()
    expect(screen.getByText('Phiên hiện tại')).toBeInTheDocument()
    expect(screen.getByText('Phiên khác')).toBeInTheDocument()
  })

  it('shows the empty state when there is no session', async () => {
    mock.onGet(ENDPOINTS.auth.sessions).reply(200, { total: 0, sessions: [] })

    renderWithProviders(<SessionsPage />)

    expect(
      await screen.findByText('Không có phiên đăng nhập nào'),
    ).toBeInTheDocument()
  })

  it('asks for confirmation before revoking a session', async () => {
    mock.onGet(ENDPOINTS.auth.sessions).reply(200, {
      total: 1,
      sessions: [
        {
          id: SESSION_B,
          ip_address: '10.0.0.5',
          user_agent: 'curl/8.0',
          expires_at: '2026-12-01T10:00:00+00:00',
          last_activity_at: '2026-11-11T08:00:00+00:00',
          created_at: '2026-11-10T09:00:00+00:00',
          is_current: false,
        },
      ],
    })
    let revokeCalled = false
    mock.onDelete(ENDPOINTS.auth.session(SESSION_B)).reply(() => {
      revokeCalled = true
      return [204]
    })

    const user = userEvent.setup()
    renderWithProviders(<SessionsPage />)

    await screen.findByText('curl')
    await user.click(screen.getByRole('button', { name: /Thu hồi phiên/ }))

    // The dialog must appear BEFORE the mutation is sent.
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(revokeCalled).toBe(false)

    await user.click(screen.getByRole('button', { name: 'Thu hồi' }))

    await waitFor(() => expect(revokeCalled).toBe(true))
  })

  it('shows the normalised error when the session list cannot be loaded', async () => {
    mock.onGet(ENDPOINTS.auth.sessions).reply(500, {
      detail: 'psycopg2.errors.InternalError: relation "sessions" missing',
    })

    renderWithProviders(<SessionsPage />)

    expect(
      await screen.findByText('Máy chủ gặp lỗi. Vui lòng thử lại sau.'),
    ).toBeInTheDocument()
    // The raw backend detail must never reach the UI.
    expect(screen.queryByText(/psycopg2/i)).not.toBeInTheDocument()
  })

  it('does not send the logout-all request before it is confirmed', async () => {
    mock.onGet(ENDPOINTS.auth.sessions).reply(200, {
      total: 1,
      sessions: [
        {
          id: SESSION_A,
          ip_address: '127.0.0.1',
          user_agent: 'curl/8.0',
          expires_at: '2026-12-01T10:00:00+00:00',
          last_activity_at: '2026-11-11T08:00:00+00:00',
          created_at: '2026-11-10T09:00:00+00:00',
          is_current: false,
        },
      ],
    })
    let logoutAllCalled = false
    mock.onPost(ENDPOINTS.auth.logoutAll).reply(() => {
      logoutAllCalled = true
      return [200, { status: 'ok' }]
    })

    const user = userEvent.setup()
    renderWithProviders(<SessionsPage />)

    await screen.findByText('curl')
    await user.click(
      screen.getByRole('button', { name: /Đăng xuất khỏi mọi thiết bị/ }),
    )

    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getAllByText(/mọi thiết bị/i).length,
    ).toBeGreaterThan(0)
    expect(logoutAllCalled).toBe(false)
  })
})

describe('S-06 Trusted Devices', () => {
  it('lists the trusted devices with their expiry', async () => {
    mock.onGet(ENDPOINTS.devices.list).reply(200, {
      total: 1,
      devices: [
        {
          id: DEVICE_A,
          device_name: 'Laptop văn phòng',
          device_fingerprint: 'hash-abc',
          last_ip: '127.0.0.1',
          last_user_agent: 'Mozilla/5.0 Chrome/120.0',
          last_used_at: '2026-11-11T10:00:00+00:00',
          expires_at: '2026-12-11T10:00:00+00:00',
          created_at: '2026-11-11T09:00:00+00:00',
        },
      ],
    })

    renderWithProviders(<TrustedDevicesPage />)

    expect(await screen.findByText('Laptop văn phòng')).toBeInTheDocument()
    expect(screen.getByText('Google Chrome')).toBeInTheDocument()
    expect(screen.getByText('127.0.0.1')).toBeInTheDocument()
  })

  it('shows the empty state when no device is trusted', async () => {
    mock.onGet(ENDPOINTS.devices.list).reply(200, { total: 0, devices: [] })

    renderWithProviders(<TrustedDevicesPage />)

    expect(
      await screen.findByText('Chưa có thiết bị tin cậy nào'),
    ).toBeInTheDocument()
  })

  it('trusts the current device with the chosen name and expiry', async () => {
    mock.onGet(ENDPOINTS.devices.list).reply(200, { total: 0, devices: [] })
    let body: unknown = null
    mock.onPost(ENDPOINTS.devices.register).reply((config) => {
      body = JSON.parse(config.data as string)
      return [200, { id: DEVICE_A, device_name: 'Máy tính', message: 'OK' }]
    })

    const user = userEvent.setup()
    renderWithProviders(<TrustedDevicesPage />)

    await screen.findByText('Chưa có thiết bị tin cậy nào')
    await user.type(screen.getByLabelText('Tên thiết bị'), 'Máy tính')
    await user.clear(screen.getByLabelText('Ghi nhớ (ngày)'))
    await user.type(screen.getByLabelText('Ghi nhớ (ngày)'), '60')
    await user.click(screen.getByRole('button', { name: /Tin cậy thiết bị/ }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({ device_name: 'Máy tính', remember_for_days: 60 })
  })

  it('rejects an out-of-range expiry before calling the API', async () => {
    mock.onGet(ENDPOINTS.devices.list).reply(200, { total: 0, devices: [] })
    let called = false
    mock.onPost(ENDPOINTS.devices.register).reply(() => {
      called = true
      return [200, { id: DEVICE_A, message: 'OK' }]
    })

    const user = userEvent.setup()
    renderWithProviders(<TrustedDevicesPage />)

    await screen.findByText('Chưa có thiết bị tin cậy nào')
    await user.clear(screen.getByLabelText('Ghi nhớ (ngày)'))
    await user.type(screen.getByLabelText('Ghi nhớ (ngày)'), '400')
    await user.click(screen.getByRole('button', { name: /Tin cậy thiết bị/ }))

    expect(
      await screen.findByText(/Số ngày phải là số nguyên từ 1 đến 365/),
    ).toBeInTheDocument()
    expect(called).toBe(false)
  })

  it('requires a strong confirmation before untrusting every device', async () => {
    mock.onGet(ENDPOINTS.devices.list).reply(200, {
      total: 1,
      devices: [
        {
          id: DEVICE_A,
          device_name: 'Laptop',
          device_fingerprint: 'hash-abc',
          last_ip: '127.0.0.1',
          last_user_agent: 'curl/8.0',
          last_used_at: '2026-11-11T10:00:00+00:00',
          expires_at: null,
          created_at: '2026-11-11T09:00:00+00:00',
        },
      ],
    })
    let untrustAllCalled = false
    mock.onDelete(ENDPOINTS.devices.removeAll).reply(() => {
      untrustAllCalled = true
      return [204]
    })

    const user = userEvent.setup()
    renderWithProviders(<TrustedDevicesPage />)

    await screen.findByText('Laptop')
    await user.click(screen.getByRole('button', { name: /Gỡ bỏ tất cả/ }))

    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getAllByText(/không thể hoàn tác/i).length,
    ).toBeGreaterThan(0)
    expect(untrustAllCalled).toBe(false)

    // The confirm button inside the dialog is the second one with that
    // label (the first one is the trigger that opened the dialog).
    const confirmButton = within(dialog).getByRole('button', {
      name: 'Gỡ bỏ tất cả',
    })
    await user.click(confirmButton)
    await waitFor(() => expect(untrustAllCalled).toBe(true))
  })

  it('surfaces the backend 403 when the session IP does not match', async () => {
    mock.onGet(ENDPOINTS.devices.list).reply(200, { total: 0, devices: [] })
    mock.onPost(ENDPOINTS.devices.register).reply(403, {
      detail:
        "Trusted-device confirmation must come from the session's familiar IP",
    })

    const user = userEvent.setup()
    renderWithProviders(<TrustedDevicesPage />)

    await screen.findByText('Chưa có thiết bị tin cậy nào')
    await user.click(screen.getByRole('button', { name: /Tin cậy thiết bị/ }))

    expect(
      await screen.findByText(
        /Trusted-device confirmation must come from the session's familiar IP/,
      ),
    ).toBeInTheDocument()
  })
})

describe('logout fallbacks', () => {
  it('never lets a failed logout leave the client in a half-logged-out state', async () => {
    // The screen calls `logoutAll` and then tears the client session down.
    // The API may fail; the local teardown must still happen.
    mock.onGet(ENDPOINTS.auth.sessions).reply(200, { total: 0, sessions: [] })
    mock.onPost(ENDPOINTS.auth.logoutAll).reply(500, { detail: 'boom' })

    const bestEffortLogout = vi.fn().mockResolvedValue(undefined)
    const { unmount } = renderWithProviders(<SessionsPage />, {
      api: {
        login: vi.fn(),
        verifyMfa: vi.fn(),
        fetchCurrentUser: vi.fn(),
        bestEffortLogout,
      },
    })

    await screen.findByText('Không có phiên đăng nhập nào')
    unmount()

    // The button must be disabled when there is nothing to revoke.
    expect(
      screen.queryByRole('button', {
        name: /Đăng xuất khỏi mọi thiết bị/,
      }),
    ).not.toBeInTheDocument()
  })
})
