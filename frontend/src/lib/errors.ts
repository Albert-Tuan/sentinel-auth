/**
 * Centralized API error handling.
 *
 * Every network/HTTP failure in the app is normalised into an `ApiError` so
 * that UI code never has to inspect raw Axios payloads. `ApiError` carries a
 * stable `kind` for programmatic branching and a `userMessage` that is safe
 * to render — it never contains tokens, secrets or raw backend internals.
 */

/** Programmatic classification of a failure. */
export type ApiErrorKind =
  | 'validation' // 400 / 422
  | 'unauthorized' // 401
  | 'forbidden' // 403
  | 'not_found' // 404
  | 'conflict' // 409
  | 'gone' // 410
  | 'locked' // 423
  | 'rate_limited' // 429
  | 'dependency_unavailable' // 502 / 503 / 504
  | 'server' // other 5xx
  | 'network' // no response at all
  | 'cancelled' // request aborted
  | 'unknown'

export interface FieldIssue {
  field: string
  message: string
}

export interface ApiErrorInit {
  kind: ApiErrorKind
  status?: number
  /** Safe, human-readable summary suitable for direct rendering. */
  userMessage: string
  /** Field-level validation issues extracted from a 422 body. */
  issues?: FieldIssue[]
  /** Backend `detail` string, when it is safe to show. */
  detail?: string
  /** Underlying error, kept for logging only. Never rendered. */
  cause?: unknown
}

/** Default, non-sensitive message per error kind. */
const DEFAULT_USER_MESSAGE: Record<ApiErrorKind, string> = {
  validation: 'Dữ liệu gửi lên không hợp lệ.',
  unauthorized: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
  forbidden: 'Bạn không có quyền thực hiện thao tác này.',
  not_found: 'Không tìm thấy dữ liệu được yêu cầu.',
  conflict: 'Dữ liệu đã thay đổi so với phiên bản bạn đang xem.',
  gone: 'Tài nguyên này không còn tồn tại.',
  locked: 'Tài khoản đang bị khóa. Vui lòng liên hệ quản trị viên.',
  rate_limited: 'Quá nhiều yêu cầu. Vui lòng thử lại sau.',
  dependency_unavailable: 'Dịch vụ phụ thuộc chưa sẵn sàng. Vui lòng thử lại sau.',
  server: 'Máy chủ gặp lỗi. Vui lòng thử lại sau.',
  network: 'Không thể kết nối tới máy chủ.',
  cancelled: 'Yêu cầu đã bị hủy.',
  unknown: 'Đã xảy ra lỗi không xác định.',
}

/**
 * Map an HTTP status code to an error kind.
 */
export function kindForStatus(status: number): ApiErrorKind {
  if (status === 400 || status === 422) return 'validation'
  if (status === 401) return 'unauthorized'
  if (status === 403) return 'forbidden'
  if (status === 404) return 'not_found'
  if (status === 409) return 'conflict'
  if (status === 410) return 'gone'
  if (status === 423) return 'locked'
  if (status === 429) return 'rate_limited'
  if (status === 502 || status === 503 || status === 504) {
    return 'dependency_unavailable'
  }
  if (status >= 500) return 'server'
  if (status >= 400) return 'validation'
  return 'unknown'
}

/**
 * Extract field-level validation issues from a FastAPI 422 body.
 * FastAPI returns `{ detail: [{ loc: ["body", "field"], msg, type }] }`.
 */
export function parseFieldIssues(body: unknown): FieldIssue[] {
  if (!body || typeof body !== 'object') return []
  const detail = (body as { detail?: unknown }).detail
  if (!Array.isArray(detail)) return []

  const issues: FieldIssue[] = []
  for (const entry of detail) {
    if (!entry || typeof entry !== 'object') continue
    const { loc, msg } = entry as { loc?: unknown; msg?: unknown }
    if (!Array.isArray(loc) || typeof msg !== 'string') continue
    // loc[0] is "body" / "query" / "path"; keep the meaningful tail.
    const field = loc.slice(1).join('.') || loc.join('.')
    issues.push({ field, message: msg })
  }
  return issues
}

/**
 * Pull a short, safe `detail` string out of a backend error body.
 *
 * Only a plain string detail is used. Structured details (validation lists,
 * dicts) are ignored because they can echo user input or internal state.
 */
export function parseDetail(body: unknown): string | undefined {
  if (!body || typeof body !== 'object') return undefined
  const detail = (body as { detail?: unknown }).detail
  return typeof detail === 'string' && detail.length > 0 ? detail : undefined
}

/**
 * A normalised API error.
 */
export class ApiError extends Error {
  readonly kind: ApiErrorKind
  readonly status?: number
  readonly userMessage: string
  readonly issues: FieldIssue[]
  readonly detail?: string

  constructor(init: ApiErrorInit) {
    super(init.userMessage)
    this.name = 'ApiError'
    this.kind = init.kind
    this.status = init.status
    this.userMessage = init.userMessage
    this.issues = init.issues ?? []
    this.detail = init.detail
    if (init.cause !== undefined) {
      ;(this as { cause?: unknown }).cause = init.cause
    }
  }

  /** True when the failure means "the session is gone — log out". */
  get isAuthFailure(): boolean {
    return this.kind === 'unauthorized'
  }

  /** True when the failure is a field-level validation problem. */
  get isValidation(): boolean {
    return this.kind === 'validation'
  }

  /** True when the failure is temporary and worth retrying. */
  get isRetryable(): boolean {
    return (
      this.kind === 'network' ||
      this.kind === 'dependency_unavailable' ||
      this.kind === 'server' ||
      this.kind === 'rate_limited'
    )
  }

  /** Issue for a given field name, if the backend reported one. */
  issueFor(field: string): FieldIssue | undefined {
    return this.issues.find((issue) => issue.field === field)
  }
}

/**
 * Build an `ApiError` from a parsed response body and status code.
 */
export function apiErrorFromResponse(
  status: number,
  body: unknown,
  cause?: unknown,
): ApiError {
  const kind = kindForStatus(status)
  const issues = parseFieldIssues(body)
  const detail = parseDetail(body)

  // A 422 with field issues is a validation error; a 400 with a plain
  // detail is usually a business-rule rejection, so keep the detail visible
  // when it is a short, safe string.
  let userMessage = DEFAULT_USER_MESSAGE[kind]
  if (kind === 'validation' && issues.length > 0) {
    userMessage = 'Dữ liệu gửi lên không hợp lệ.'
  } else if (detail && status === 400 && detail.length <= 200) {
    userMessage = detail
  } else if (detail && status === 403 && detail.length <= 200) {
    userMessage = detail
  } else if (detail && status === 423 && detail.length <= 200) {
    userMessage = detail
  } else if (detail && status === 429 && detail.length <= 200) {
    userMessage = detail
  }

  return new ApiError({ kind, status, userMessage, issues, detail, cause })
}

/**
 * Wrap an arbitrary thrown value into an `ApiError`.
 */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error

  if (error && typeof error === 'object') {
    const candidate = error as {
      isAxiosError?: boolean
      code?: string
      response?: { status?: number; data?: unknown }
      message?: string
    }
    if (candidate.response?.status) {
      return apiErrorFromResponse(
        candidate.response.status,
        candidate.response.data,
        error,
      )
    }
    if (candidate.code === 'ERR_CANCELED' || candidate.code === 'ECONNABORTED') {
      return new ApiError({
        kind: 'cancelled',
        userMessage: DEFAULT_USER_MESSAGE.cancelled,
        cause: error,
      })
    }
    if (candidate.isAxiosError) {
      return new ApiError({
        kind: 'network',
        userMessage: DEFAULT_USER_MESSAGE.network,
        cause: error,
      })
    }
  }

  if (error instanceof Error) {
    return new ApiError({
      kind: 'unknown',
      userMessage: DEFAULT_USER_MESSAGE.unknown,
      cause: error,
    })
  }

  return new ApiError({
    kind: 'unknown',
    userMessage: DEFAULT_USER_MESSAGE.unknown,
    cause: error,
  })
}

/** Human-readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  return toApiError(error).userMessage
}
