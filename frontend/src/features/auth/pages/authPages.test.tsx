/**
 * Component tests for the login and MFA screens.
 *
 * Covers: the login form, the MFA challenge screen, and the reload rule
 * (a page reload clears the in-memory session and requires a new login).
 */

import { describe, expect, it, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderRouter } from '@/test/renderApp'
import { __resetStore, getAccessToken } from '@/lib/api/tokenStore'
import { ApiError } from '@/lib/errors'
import type { AuthApi } from '@/features/auth/useAuth'
import {
  FAKE_ACCESS_TOKEN,
  FAKE_MFA_TRANSACTION_ID,
  FAKE_REFRESH_TOKEN,
  makeUser,
} from '@/test/fixtures'

beforeEach(() => {
  __resetStore()
})

function makeApi(overrides: Partial<AuthApi> = {}): AuthApi {
  return {
    login: vi.fn().mockResolvedValue({
      access_token: FAKE_ACCESS_TOKEN,
      refresh_token: FAKE_REFRESH_TOKEN,
      mfa_required: false,
      session_id: 'session-1',
    }),
    verifyMfa: vi.fn().mockResolvedValue({
      access_token: FAKE_ACCESS_TOKEN,
      refresh_token: FAKE_REFRESH_TOKEN,
      session_id: 'session-1',
    }),
    fetchCurrentUser: vi.fn().mockResolvedValue(makeUser()),
    bestEffortLogout: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

describe('LoginPage', () => {
  it('renders the login form', () => {
    renderRouter({ api: makeApi(), initialEntries: ['/login'] })

    expect(screen.getByLabelText('Tên đăng nhập')).toBeInTheDocument()
    expect(screen.getByLabelText('Mật khẩu')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /Đăng nhập/ }),
    ).toBeInTheDocument()
  })

  it('submits the credentials and authenticates', async () => {
    const user = userEvent.setup()
    const api = makeApi()
    renderRouter({ api, initialEntries: ['/login'] })

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'correct-password')
    await user.click(screen.getByRole('button', { name: /Đăng nhập/ }))

    await waitFor(() => {
      expect(api.login).toHaveBeenCalledWith({
        username: 'analyst',
        password: 'correct-password',
      })
    })
    await waitFor(() => {
      expect(getAccessToken()).toBe(FAKE_ACCESS_TOKEN)
    })
  })

  it('shows an error message when the credentials are rejected', async () => {
    const user = userEvent.setup()
    const api = makeApi({
      login: vi.fn().mockRejectedValue(
        new ApiError({
          kind: 'unauthorized',
          status: 401,
          userMessage: 'Tên đăng nhập hoặc mật khẩu không đúng.',
        }),
      ),
    })
    renderRouter({ api, initialEntries: ['/login'] })

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'wrong')
    await user.click(screen.getByRole('button', { name: /Đăng nhập/ }))

    expect(
      await screen.findByText('Tên đăng nhập hoặc mật khẩu không đúng.'),
    ).toBeInTheDocument()
    expect(getAccessToken()).toBeNull()
  })

  it('does not leak internal backend detail into the UI', async () => {
    const user = userEvent.setup()
    const api = makeApi({
      login: vi.fn().mockRejectedValue(
        new ApiError({
          kind: 'server',
          status: 500,
          userMessage: 'Máy chủ gặp lỗi. Vui lòng thử lại sau.',
          detail: 'psycopg2.errors.UndefinedColumn: users.internal_secret',
        }),
      ),
    })
    renderRouter({ api, initialEntries: ['/login'] })

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'x')
    await user.click(screen.getByRole('button', { name: /Đăng nhập/ }))

    await screen.findByText('Máy chủ gặp lỗi. Vui lòng thử lại sau.')
    expect(
      screen.queryByText(/internal_secret|psycopg2/i),
    ).not.toBeInTheDocument()
  })

  it('sends the user to the MFA screen when MFA is required', async () => {
    const user = userEvent.setup()
    const api = makeApi({
      login: vi.fn().mockResolvedValue({
        access_token: '',
        refresh_token: '',
        mfa_required: true,
        session_id: FAKE_MFA_TRANSACTION_ID,
      }),
    })
    renderRouter({ api, initialEntries: ['/login'] })

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'admin')
    await user.type(screen.getByLabelText('Mật khẩu'), 'password')
    await user.click(screen.getByRole('button', { name: /Đăng nhập/ }))

    // The MFA challenge screen replaces the login form.
    expect(
      await screen.findByText('Xác thực hai yếu tố'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Mã xác thực')).toBeInTheDocument()
    // Still not authenticated.
    expect(getAccessToken()).toBeNull()
  })
})

describe('MfaVerifyPage', () => {
  it('sends the user back to login when there is no pending challenge', async () => {
    renderRouter({ api: makeApi(), initialEntries: ['/mfa'] })
    // The MFA screen redirects back to the login form.
    expect(await screen.findByLabelText('Tên đăng nhập')).toBeInTheDocument()
  })

  it('rejects a code that is not six digits without calling the API', async () => {
    const user = userEvent.setup()
    const api = makeApi()
    // Establish a pending challenge first.
    api.login = vi.fn().mockResolvedValue({
      access_token: '',
      refresh_token: '',
      mfa_required: true,
      session_id: FAKE_MFA_TRANSACTION_ID,
    })
    renderRouter({ api, initialEntries: ['/login'] })

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'admin')
    await user.type(screen.getByLabelText('Mật khẩu'), 'password')
    await user.click(screen.getByRole('button', { name: /Đăng nhập/ }))
    await screen.findByText('Xác thực hai yếu tố')

    await user.type(screen.getByLabelText('Mã xác thực'), '123')
    await user.click(screen.getByRole('button', { name: 'Xác thực' }))

    expect(
      await screen.findByText('Mã xác thực phải gồm đúng 6 chữ số.'),
    ).toBeInTheDocument()
    expect(api.verifyMfa).not.toHaveBeenCalled()
  })

  it('verifies the code and authenticates on success', async () => {
    const user = userEvent.setup()
    const api = makeApi()
    api.login = vi.fn().mockResolvedValue({
      access_token: '',
      refresh_token: '',
      mfa_required: true,
      session_id: FAKE_MFA_TRANSACTION_ID,
    })
    renderRouter({ api, initialEntries: ['/login'] })

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'admin')
    await user.type(screen.getByLabelText('Mật khẩu'), 'password')
    await user.click(screen.getByRole('button', { name: /Đăng nhập/ }))
    await screen.findByText('Xác thực hai yếu tố')

    await user.type(screen.getByLabelText('Mã xác thực'), '123456')
    await user.click(screen.getByRole('button', { name: 'Xác thực' }))

    await waitFor(() => {
      expect(api.verifyMfa).toHaveBeenCalledWith({
        session_id: FAKE_MFA_TRANSACTION_ID,
        mfa_code: '123456',
      })
    })
    await waitFor(() => {
      expect(getAccessToken()).toBe(FAKE_ACCESS_TOKEN)
    })
  })

  it('shows an error when the code is wrong and stays on the MFA screen', async () => {
    const user = userEvent.setup()
    const api = makeApi({
      verifyMfa: vi.fn().mockRejectedValue(
        new ApiError({
          kind: 'unauthorized',
          status: 401,
          userMessage: 'Mã xác thực không đúng hoặc đã hết hạn.',
        }),
      ),
      login: vi.fn().mockResolvedValue({
        access_token: '',
        refresh_token: '',
        mfa_required: true,
        session_id: FAKE_MFA_TRANSACTION_ID,
      }),
    })
    renderRouter({ api, initialEntries: ['/login'] })

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'admin')
    await user.type(screen.getByLabelText('Mật khẩu'), 'password')
    await user.click(screen.getByRole('button', { name: /Đăng nhập/ }))
    await screen.findByText('Xác thực hai yếu tố')

    await user.type(screen.getByLabelText('Mã xác thực'), '000000')
    await user.click(screen.getByRole('button', { name: 'Xác thực' }))

    expect(
      await screen.findByText('Mã xác thực không đúng hoặc đã hết hạn.'),
    ).toBeInTheDocument()
    expect(getAccessToken()).toBeNull()
  })
})

describe('reload behaviour', () => {
  it('requires a new login after a page reload, because the session is memory-only', async () => {
    const user = userEvent.setup()
    const api = makeApi()
    const { unmount } = renderRouter({ api, initialEntries: ['/login'] })

    await user.type(screen.getByLabelText('Tên đăng nhập'), 'analyst')
    await user.type(screen.getByLabelText('Mật khẩu'), 'password')
    await user.click(screen.getByRole('button', { name: /Đăng nhập/ }))
    await waitFor(() => {
      expect(getAccessToken()).toBe(FAKE_ACCESS_TOKEN)
    })

    // Simulate the reload: the module state is discarded.
    unmount()
    __resetStore()
    expect(getAccessToken()).toBeNull()

    // A fresh render starts at the login form again.
    renderRouter({ api, initialEntries: ['/login'] })
    expect(screen.getByLabelText('Tên đăng nhập')).toBeInTheDocument()
    expect(
      screen.queryByText('Xác thực hai yếu tố'),
    ).not.toBeInTheDocument()
  })
})
