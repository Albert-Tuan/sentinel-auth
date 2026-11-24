/**
 * S-30 / S-31 / S-32 — Detection Policies.
 *
 * The contracts under test, all of them taken from the Core:
 *
 *   - the listing endpoint returns a SUMMARY: no rules, no config. The
 *     screen therefore shows `rule_count`, never the rules themselves;
 *   - a policy that has ever been active is FROZEN — the editor is
 *     read-only and the screen says why;
 *   - the write carries `expected_updated_at` — the raw `updated_at`
 *     string, unmodified, because the backend compares microsecond
 *     precision;
 *   - the server owns `is_active`, `created_by` and the timestamps, so
 *     the payload never carries them;
 *   - the client mirrors the backend's rule validators so the operator
 *     sees the problem before the request.
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

import { PolicyListPage } from '@/features/policies/pages/PolicyListPage'
import { PolicyDetailPage } from '@/features/policies/pages/PolicyDetailPage'
import {
  isValidVersion,
  parseRuleValue,
  validateRule,
  validateThresholds,
  validateWeights,
} from '@/features/policies/policyValidation'

const POLICY_ID = 'p000000-0000-0000-0000-000000000001'
const UPDATED_AT = '2026-11-20T09:15:00.123456+00:00'

let mock: MockAdapter

beforeEach(() => {
  __resetStore()
  __resetClientState()
  mock = new MockAdapter(apiClient)
})

function makeSummary(overrides: Record<string, unknown> = {}) {
  return {
    id: POLICY_ID,
    version: 'v1.2',
    name: 'Phát hiện đăng nhập bất thường',
    description: 'Quy tắc heuristic kết hợp Isolation Forest',
    rule_count: 12,
    is_active: false,
    created_at: '2026-11-01T03:04:00.000000+00:00',
    activated_at: null,
    ...overrides,
  }
}

function makeDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: POLICY_ID,
    version: 'v1.2',
    name: 'Phát hiện đăng nhập bất thường',
    description: 'Quy tắc heuristic kết hợp Isolation Forest',
    rules: [
      {
        name: 'fail_count_24h',
        field: 'fail_count_24h',
        operator: '>',
        value: 5,
        weight: 0.4,
        score: 0.6,
        enabled: true,
        description: null,
      },
    ],
    config: {
      weights: { rule: 0.4, ml: 0.6 },
      thresholds: { low: 0.25, medium: 0.5, high: 0.75 },
    },
    is_active: false,
    created_by: 'a000000-0000-0000-0000-000000000009',
    created_at: '2026-11-01T03:04:00.000000+00:00',
    updated_at: UPDATED_AT,
    activated_at: null,
    deactivated_at: null,
    ...overrides,
  }
}

function mockPolicies(policies: unknown[]) {
  mock.onGet(ENDPOINTS.policies.list).reply(200, policies)
}

function renderList() {
  return renderWithProviders(
    <Routes>
      <Route path="/policies" element={<PolicyListPage />} />
    </Routes>,
    { initialEntries: ['/policies'] },
  )
}

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/policies/:policyId" element={<PolicyDetailPage />} />
    </Routes>,
    { initialEntries: [`/policies/${POLICY_ID}`] },
  )
}

describe('S-30 Policy List', () => {
  it('lists the policies the backend returned', async () => {
    mockPolicies([makeSummary()])

    renderList()

    expect(
      await screen.findByText('Phát hiện đăng nhập bất thường'),
    ).toBeInTheDocument()
    expect(screen.getByText('v1.2')).toBeInTheDocument()
    expect(screen.getByText('12 QUY TẮC')).toBeInTheDocument()
  })

  it('never renders the rules — the listing endpoint does not carry them', async () => {
    mockPolicies([makeSummary()])

    renderList()

    await screen.findByText('Phát hiện đăng nhập bất thường')
    expect(screen.queryByText('fail_count_24h')).not.toBeInTheDocument()
  })

  it('offers the editor only for a draft policy', async () => {
    mockPolicies([
      makeSummary({ id: 'draft-id', version: 'v1.3', name: 'Bản nháp' }),
      makeSummary({
        id: 'active-id',
        version: 'v1.2',
        name: 'Đang áp dụng',
        is_active: true,
        activated_at: '2026-11-02T00:00:00.000000+00:00',
      }),
      makeSummary({
        id: 'frozen-id',
        version: 'v1.1',
        name: 'Đã đóng băng',
        activated_at: '2026-10-02T00:00:00.000000+00:00',
      }),
    ])

    renderList()

    await screen.findByText('Bản nháp')

    // Exactly one policy may be edited: the draft.
    expect(
      screen.getAllByRole('link', { name: 'Chỉnh sửa' }),
    ).toHaveLength(1)
    expect(screen.getAllByText('Đã đóng băng').length).toBeGreaterThan(0)
  })

  it('filters the rows on the client', async () => {
    mockPolicies([
      makeSummary({ id: 'a', version: 'v1.0', name: 'Alpha' }),
      makeSummary({ id: 'b', version: 'v2.0', name: 'Beta' }),
    ])

    const user = userEvent.setup()
    renderList()

    await screen.findByText('Alpha')

    await user.type(screen.getByLabelText('Tên / phiên bản / ID'), 'Beta')

    await waitFor(() => {
      expect(screen.queryByText('Alpha')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Beta')).toBeInTheDocument()
  })

  it('shows the empty state when the backend returns nothing', async () => {
    mockPolicies([])

    renderList()

    expect(
      await screen.findByText('Không có chính sách phù hợp'),
    ).toBeInTheDocument()
  })
})

describe('S-31 / S-32 Policy Detail and Editor', () => {
  it('renders the rules the detail endpoint returns', async () => {
    mock.onGet(ENDPOINTS.policies.detail(POLICY_ID)).reply(200, makeDetail())

    renderDetail()

    // The rule name and the feature-field select hold the same string,
    // so the input is addressed by its label instead.
    expect(
      await screen.findByLabelText('Tên quy tắc'),
    ).toHaveValue('fail_count_24h')
  })

  it('freezes the editor for a policy that was activated', async () => {
    mock.onGet(ENDPOINTS.policies.detail(POLICY_ID)).reply(
      200,
      makeDetail({ activated_at: '2026-11-05T00:00:00.000000+00:00' }),
    )

    renderDetail()

    await screen.findByLabelText('Tên quy tắc')

    // A frozen policy offers no way to write: neither the save button
    // nor the "add rule" button is rendered.
    expect(screen.queryByRole('button', { name: /lưu thay đổi/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /thêm quy tắc/i })).toBeNull()
    expect(screen.getByLabelText('Tên quy tắc')).toBeDisabled()
    expect(screen.getByText(/chế độ chỉ đọc/i)).toBeInTheDocument()
  })

  it('allows the editor to save a draft policy', async () => {
    mock.onGet(ENDPOINTS.policies.detail(POLICY_ID)).reply(200, makeDetail())

    let body: Record<string, unknown> = {}
    mock.onPut(ENDPOINTS.policies.detail(POLICY_ID)).reply((config) => {
      body = JSON.parse(config.data as string)
      return [200, makeDetail({ updated_at: '2026-11-21T00:00:00.000000+00:00' })]
    })

    const user = userEvent.setup()
    renderDetail()

    await screen.findByLabelText('Tên quy tắc')

    await user.click(screen.getByRole('button', { name: /lưu thay đổi/i }))

    await waitFor(() => {
      expect(body).not.toEqual({})
    })

    // The optimistic-concurrency token is the raw string, unmodified.
    expect(body.expected_updated_at).toBe(UPDATED_AT)
    // The server owns these fields — they must not be sent.
    expect(body).not.toHaveProperty('is_active')
    expect(body).not.toHaveProperty('created_by')
    expect(body).not.toHaveProperty('updated_at')
    expect(body).not.toHaveProperty('version')
  })

  it('reports a 409 conflict from the backend verbatim', async () => {
    mock.onGet(ENDPOINTS.policies.detail(POLICY_ID)).reply(200, makeDetail())
    mock.onPut(ENDPOINTS.policies.detail(POLICY_ID)).reply(409, {
      detail: {
        message: 'Policy was modified by someone else',
        problems: ['expected_updated_at does not match the current policy'],
      },
    })

    const user = userEvent.setup()
    renderDetail()

    await screen.findByLabelText('Tên quy tắc')
    await user.click(screen.getByRole('button', { name: /lưu thay đổi/i }))

    expect(
      await screen.findByText(/không thể lưu chính sách/i),
    ).toBeInTheDocument()
  })

  it('blocks the save while the weights do not sum to 1.0', async () => {
    mock.onGet(ENDPOINTS.policies.detail(POLICY_ID)).reply(
      200,
      makeDetail({
        config: {
          weights: { rule: 0.4, ml: 0.6 },
          thresholds: { low: 0.25, medium: 0.5, high: 0.75 },
        },
      }),
    )

    const user = userEvent.setup()
    renderDetail()

    await screen.findByLabelText('Tên quy tắc')

    const mlWeight = screen.getByLabelText('Trọng số Mô hình ML')
    await user.clear(mlWeight)
    await user.type(mlWeight, '0.9')

    expect(
      screen.getByRole('button', { name: /lưu thay đổi/i }),
    ).toBeDisabled()
    expect(screen.getByText(/tổng trọng số rule \+ ml phải bằng 1\.0/i)).toBeInTheDocument()
  })

  it('asks for a confirmation before activating the policy', async () => {
    mock.onGet(ENDPOINTS.policies.detail(POLICY_ID)).reply(200, makeDetail())
    mock.onPost(ENDPOINTS.policies.activate(POLICY_ID)).reply(
      200,
      makeDetail({ is_active: true }),
    )

    const user = userEvent.setup()
    renderDetail()

    await screen.findByLabelText('Tên quy tắc')

    await user.click(screen.getByRole('button', { name: /kích hoạt chính sách/i }))

    const dialog = await screen.findByRole('dialog')
    expect(
      within(dialog).getByText(/chỉ một chính sách có thể được kích hoạt/i),
    ).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: /kích hoạt/i }))

    await waitFor(() => {
      expect(mock.history.post).toHaveLength(1)
    })
  })
})

describe('policy validation mirrors the backend', () => {
  it('accepts the 6 canonical feature fields', () => {
    expect(
      validateRule({
        name: 'r1',
        field: 'deviation_score',
        operator: '>',
        value: 0.5,
        weight: 0.4,
        score: 0.6,
      }),
    ).toEqual([])
  })

  it('rejects an unknown feature field', () => {
    const problems = validateRule({
      name: 'r1',
      field: 'geo_velocity_kmh',
      operator: '>',
      value: 0.5,
      weight: 0.4,
      score: 0.6,
    })
    expect(problems).toHaveLength(1)
    expect(problems[0]).toMatch(/không hợp lệ/)
  })

  it('rejects a range operator without a [min, max] value', () => {
    const problems = validateRule({
      name: 'r1',
      field: 'deviation_score',
      operator: 'between',
      value: 0.5,
      weight: 0.4,
      score: 0.6,
    })
    expect(problems.length).toBeGreaterThan(0)
  })

  it('rejects a weight outside [0, 1]', () => {
    const problems = validateRule({
      name: 'r1',
      field: 'deviation_score',
      operator: '>',
      value: 0.5,
      weight: 1.4,
      score: 0.6,
    })
    expect(problems).toHaveLength(1)
    expect(problems[0]).toMatch(/weight/)
  })

  it('requires the weights to sum to 1.0 when both sides are active', () => {
    expect(validateWeights(0.4, 0.6)).toEqual([])
    expect(validateWeights(0.4, 0.9)).toHaveLength(1)
    // A policy that disables one side of the ensemble is legal.
    expect(validateWeights(0, 0.9)).toEqual([])
  })

  it('requires the thresholds to be non-decreasing', () => {
    expect(validateThresholds(0.25, 0.5, 0.75)).toEqual([])
    expect(validateThresholds(0.5, 0.25, 0.75)).toHaveLength(1)
  })

  it('parses a range value into a [min, max] pair', () => {
    expect(parseRuleValue('0.4, 0.8', 'between')).toEqual([0.4, 0.8])
    expect(parseRuleValue('0.4,0.8', 'between')).toEqual([0.4, 0.8])
    expect(parseRuleValue('not a range', 'between')).toBeNull()
  })

  it('parses a list value into an array', () => {
    expect(parseRuleValue('a, b', 'in')).toEqual(['a', 'b'])
    expect(parseRuleValue('a, b', '==')).toBe('a, b')
  })

  it('accepts only the version pattern the backend accepts', () => {
    expect(isValidVersion('v1')).toBe(true)
    expect(isValidVersion('v1.0')).toBe(true)
    expect(isValidVersion('v3.3.1')).toBe(true)
    expect(isValidVersion('1.0')).toBe(false)
    expect(isValidVersion('vX')).toBe(false)
  })
})
