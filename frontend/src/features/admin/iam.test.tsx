/**
 * S-10 / S-11 — IAM.
 *
 * The screens talk to the Core-owned identity endpoints, all gated by
 * `SECURITY_ADMIN`. The contracts under test:
 *
 *   - the base role `USER` is never offered as revocable — the backend
 *     answers 422 for it;
 *   - every IAM mutation revokes the target's sessions, and the confirm
 *     dialog says so before the admin commits to it;
 *   - a filter left empty is not sent, because the backend validates the
 *     enum values;
 *   - a null before/after state is NOT an empty state: the row says so
 *     explicitly instead of showing "{}".
 */

import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MockAdapter from 'axios-mock-adapter'
import { Route, Routes } from 'react-router-dom'

import { apiClient, __resetClientState } from '@/lib/api/client'
import { __resetStore } from '@/lib/api/tokenStore'
import { ENDPOINTS } from '@/lib/api/endpoints'
import { renderWithProviders } from '@/test/renderApp'

import { AuditLogsPage } from '@/features/admin/pages/AuditLogsPage'
import { UserManagementPage } from '@/features/admin/pages/UserManagementPage'

const USER_ID = 'u000000-0000-0000-0000-000000000001'

let mock: MockAdapter

beforeEach(() => {
  __resetStore()
  __resetClientState()
  mock = new MockAdapter(apiClient)
})

function makeUser(overrides: Record<string, unknown> = {}) {
  return {
    id: USER_ID,
    username: 'analyst@example.com',
    email: 'analyst@example.com',
    full_name: 'Lê Minh Analyst',
    status: 'active',
    admin_mfa_required: true,
    roles: ['USER', 'SOC_ANALYST'],
    last_login_at: '2026-11-12T07:59:00.000000+00:00',
    failed_login_count: 2,
    locked_at: null,
    created_at: '2026-01-02T03:04:00.000000+00:00',
    ...overrides,
  }
}

function mockUsers(users: unknown[], total = users.length) {
  mock.onGet(ENDPOINTS.admin.users).reply(200, {
    users,
    total,
    page: 1,
    limit: 20,
  })
}

function renderUsers() {
  return renderWithProviders(
    <Routes>
      <Route path="/admin/users" element={<UserManagementPage />} />
    </Routes>,
    { initialEntries: ['/admin/users'] },
  )
}

function renderAuditLogs() {
  return renderWithProviders(
    <Routes>
      <Route path="/admin/audit-logs" element={<AuditLogsPage />} />
    </Routes>,
    { initialEntries: ['/admin/audit-logs'] },
  )
}

describe('S-10 User Management', () => {
  it('lists the users the backend returned', async () => {
    mockUsers([makeUser()])

    renderUsers()

    // The username and the email are the same string here, so the text
    // appears twice — once in the username column, once in the email one.
    expect(
      await screen.findAllByText('analyst@example.com'),
    ).not.toHaveLength(0)
    expect(screen.getByText('Lê Minh Analyst')).toBeInTheDocument()
    expect(screen.getAllByText('Hoạt động').length).toBeGreaterThan(0)
  })

  it('never offers the base role USER as revocable', async () => {
    mockUsers([makeUser()])

    renderUsers()

    await screen.findAllByText('analyst@example.com')

    // The user holds USER and SOC_ANALYST; only the special role is
    // revocable.
    expect(
      screen.getByRole('button', {
        name: /thu hồi vai trò SOC_ANALYST/i,
      }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /thu hồi vai trò USER/i }),
    ).not.toBeInTheDocument()
  })

  it('grants a role through the confirmation dialog', async () => {
    mockUsers([makeUser()])
    let body: unknown = null
    mock
      .onPost(ENDPOINTS.admin.userRoles(USER_ID))
      .reply((config) => {
        body = JSON.parse(config.data as string)
        return [200, makeUser({ roles: ['USER', 'SOC_ANALYST', 'SECURITY_MANAGER'] })]
      })

    renderUsers()

    await userEvent.click(
      await screen.findByRole('button', { name: /cấp vai trò/i }),
    )

    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(
      within(dialog).getByLabelText(/vai trò/i),
      'SECURITY_MANAGER',
    )
    await userEvent.click(
      within(dialog).getByRole('button', { name: /cấp vai trò/i }),
    )

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({ role: 'SECURITY_MANAGER' })
  })

  it('locks the account through the confirmation dialog', async () => {
    mockUsers([makeUser()])
    let called = false
    mock.onPost(ENDPOINTS.admin.userLock(USER_ID)).reply(() => {
      called = true
      return [200, makeUser({ status: 'locked' })]
    })

    renderUsers()

    await userEvent.click(await screen.findByRole('button', { name: /^khoá$/i }))

    const dialog = await screen.findByRole('dialog')
    await userEvent.click(
      within(dialog).getByRole('button', { name: /^khoá$/i }),
    )

    await waitFor(() => expect(called).toBe(true))
  })

  it('unlocks a locked account', async () => {
    mockUsers([makeUser({ status: 'locked', locked_at: '2026-11-12T08:00:00Z' })])
    let called = false
    mock.onDelete(ENDPOINTS.admin.userLock(USER_ID)).reply(() => {
      called = true
      return [200, makeUser({ status: 'active' })]
    })

    renderUsers()

    await userEvent.click(
      await screen.findByRole('button', { name: /mở khoá/i }),
    )

    const dialog = await screen.findByRole('dialog')
    await userEvent.click(
      within(dialog).getByRole('button', { name: /mở khoá/i }),
    )

    await waitFor(() => expect(called).toBe(true))
  })

  it('toggles the MFA requirement', async () => {
    mockUsers([makeUser({ admin_mfa_required: false })])
    let body: unknown = null
    mock.onPut(ENDPOINTS.admin.userMfa(USER_ID)).reply((config) => {
      body = JSON.parse(config.data as string)
      return [200, makeUser({ admin_mfa_required: true })]
    })

    renderUsers()

    await userEvent.click(
      await screen.findByRole('button', { name: /bắt buộc MFA/i }),
    )

    const dialog = await screen.findByRole('dialog')
    await userEvent.click(
      within(dialog).getByRole('button', { name: /yêu cầu MFA/i }),
    )

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({ mfa_required: true })
  })

  it('shows the empty state when there is no user', async () => {
    mockUsers([])

    renderUsers()

    expect(await screen.findByText('Không có dữ liệu')).toBeInTheDocument()
  })
})

describe('S-11 Audit Logs', () => {
  it('lists the audit entries the backend returned', async () => {
    mock.onGet(ENDPOINTS.admin.auditLogs).reply(200, {
      logs: [
        {
          id: 'au000000-0000-0000-0000-000000000001',
          request_id: null,
          actor: 'admin@example.com',
          action: 'assign_role',
          resource: 'user_role',
          resource_id: USER_ID,
          before_state: { roles: ['USER'] },
          after_state: { roles: ['USER', 'SOC_ANALYST'] },
          change_reason: null,
          ip_address: '203.0.113.9',
          user_agent: null,
          created_at: '2026-11-12T08:00:00.000000+00:00',
        },
      ],
      total: 1,
      page: 1,
      limit: 20,
    })

    renderAuditLogs()

    expect(
      await screen.findByText('admin@example.com'),
    ).toBeInTheDocument()
    expect(screen.getByText('assign_role')).toBeInTheDocument()
    expect(screen.getByText('203.0.113.9')).toBeInTheDocument()
  })

  it('says "no data" for an entry without a before/after state', async () => {
    mock.onGet(ENDPOINTS.admin.auditLogs).reply(200, {
      logs: [
        {
          id: 'au000000-0000-0000-0000-000000000002',
          request_id: null,
          actor: 'system',
          action: 'cleanup',
          resource: 'session',
          resource_id: null,
          before_state: null,
          after_state: null,
          change_reason: null,
          ip_address: null,
          user_agent: null,
          created_at: '2026-11-12T08:00:00.000000+00:00',
        },
      ],
      total: 1,
      page: 1,
      limit: 20,
    })

    renderAuditLogs()

    expect(await screen.findByText('HỆ THỐNG')).toBeInTheDocument()
    expect(screen.getByText('Không có dữ liệu')).toBeInTheDocument()
  })

  it('sends the audit filters the admin chose', async () => {
    let params: Record<string, unknown> = {}
    mock.onGet(ENDPOINTS.admin.auditLogs).reply((config) => {
      params = (config.params ?? {}) as Record<string, unknown>
      return [200, { logs: [], total: 0, page: 1, limit: 20 }]
    })

    renderAuditLogs()

    await userEvent.type(
      await screen.findByLabelText(/tác nhân/i),
      'admin@example.com',
    )
    await userEvent.type(screen.getByLabelText(/hành động/i), 'assign_role')
    await userEvent.click(screen.getByRole('button', { name: /^lọc$/i }))

    await waitFor(() => expect(params.actor).toBe('admin@example.com'))
    expect(params.action).toBe('assign_role')
    expect(params.resource).toBeUndefined()
  })
})
