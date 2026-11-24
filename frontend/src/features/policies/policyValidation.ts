/**
 * Client-side mirror of the backend's policy validators.
 *
 * The backend owns the truth — `app/detection.py::validate_rule` and
 * `app/schemas.py::PolicyConfig` decide whether a policy is usable. This
 * module exists for one reason only: to show the operator WHY a rule is
 * rejected BEFORE the request is sent, instead of after a 400.
 *
 * Every rule here mirrors a backend rule exactly. When the backend
 * changes, this file must change with it — otherwise the editor starts
 * rejecting policies the Core would accept, which is a worse failure
 * than letting the Core answer.
 */

/** The 6 features a rule may reference (UC-DE-02). */
export const ALLOWED_FEATURE_FIELDS = [
  'hour_of_day',
  'fail_count_24h',
  'ip_change_rate_7d',
  'new_device',
  'average_login_interval_seconds',
  'deviation_score',
] as const

/** The comparison operators a rule may use. */
export const ALLOWED_OPERATORS = [
  '==',
  '!=',
  '>',
  '>=',
  '<',
  '<=',
  'in',
  'between',
  'not_between',
] as const

/** The operators whose value must be a 2-element `[min, max]` array. */
export const RANGE_OPERATORS = ['between', 'not_between'] as const

export type PolicyField = (typeof ALLOWED_FEATURE_FIELDS)[number]
export type PolicyOperator = (typeof ALLOWED_OPERATORS)[number]

/** The operators whose value must be a NON-EMPTY array. */
const LIST_OPERATORS = ['in'] as const

/**
 * Is this operator one that needs a `[min, max]` value?
 */
export function isRangeOperator(operator: string): boolean {
  return (RANGE_OPERATORS as readonly string[]).includes(operator)
}

/**
 * Does this operator need a list value?
 */
export function isListOperator(operator: string): boolean {
  return (LIST_OPERATORS as readonly string[]).includes(operator)
}

/**
 * Parse the raw text of a rule value into the JSON the backend expects.
 *
 * The value can be a number, a boolean, a scalar string, or a list. The
 * text is parsed as JSON when it looks like JSON (a number, `true`/
 * `false`, or a bracketed list); otherwise it is treated as a plain
 * string. A range operator always produces a 2-element list.
 *
 * @returns the parsed value, or `null` when the text cannot be parsed.
 */
export function parseRuleValue(
  raw: string,
  operator: string,
): unknown | null {
  const text = raw.trim()

  if (text === '') {
    // An empty value is invalid for every operator, but the caller
    // reports that itself; return a sentinel that never parses.
    return null
  }

  if (isRangeOperator(operator)) {
    const parts = text.split(',').map((part) => part.trim())
    if (parts.length !== 2) return null
    const min = Number(parts[0])
    const max = Number(parts[1])
    if (!Number.isFinite(min) || !Number.isFinite(max)) return null
    return [min, max]
  }

  if (isListOperator(operator)) {
    const parts = text
      .split(',')
      .map((part) => part.trim())
      .filter((part) => part !== '')
    if (parts.length === 0) return null
    return parts.map((part) => coerceScalar(part))
  }

  return coerceScalar(text)
}

/**
 * Turn one textual token into a number, a boolean or a string.
 */
function coerceScalar(text: string): string | number | boolean {
  if (text === 'true') return true
  if (text === 'false') return false
  if (text !== '' && !Number.isNaN(Number(text))) return Number(text)
  return text
}

/**
 * Validate one rule the way the backend does.
 *
 * @returns the list of problems. Empty means the rule is usable.
 */
export function validateRule(rule: {
  name: string
  field: string
  operator: string
  value: unknown
  weight: number
  score: number
}): string[] {
  const problems: string[] = []

  if (!rule.name.trim()) {
    problems.push('Tên quy tắc là bắt buộc')
  }

  if (!(ALLOWED_FEATURE_FIELDS as readonly string[]).includes(rule.field)) {
    problems.push(`Trường dữ liệu "${rule.field}" không hợp lệ`)
  }

  if (!(ALLOWED_OPERATORS as readonly string[]).includes(rule.operator)) {
    problems.push(`Toán tử "${rule.operator}" không được hỗ trợ`)
  }

  if (isRangeOperator(rule.operator)) {
    if (!Array.isArray(rule.value) || rule.value.length !== 2) {
      problems.push(`Toán tử "${rule.operator}" cần giá trị dạng [min, max]`)
    }
  } else if (isListOperator(rule.operator)) {
    if (!Array.isArray(rule.value) || rule.value.length === 0) {
      problems.push(`Toán tử "in" cần một danh sách giá trị không rỗng`)
    }
  } else if (Array.isArray(rule.value)) {
    problems.push(`Toán tử "${rule.operator}" chỉ nhận một giá trị, không phải danh sách`)
  }

  if (!Number.isFinite(rule.weight) || rule.weight < 0 || rule.weight > 1) {
    problems.push('Trọng số (weight) phải nằm trong [0.0, 1.0]')
  }

  if (!Number.isFinite(rule.score) || rule.score < 0 || rule.score > 1) {
    problems.push('Điểm (score) phải nằm trong [0.0, 1.0]')
  }

  return problems
}

/**
 * Validate the ensemble weights.
 *
 * The backend only enforces the sum when BOTH weights are non-zero, so a
 * policy that disables one side of the ensemble is legal.
 */
export function validateWeights(rule: number, ml: number): string[] {
  const problems: string[] = []

  if (!Number.isFinite(rule) || rule < 0 || rule > 1) {
    problems.push('Trọng số rule phải nằm trong [0.0, 1.0]')
  }
  if (!Number.isFinite(ml) || ml < 0 || ml > 1) {
    problems.push('Trọng số ML phải nằm trong [0.0, 1.0]')
  }
  if (problems.length > 0) return problems

  if (rule > 0 && ml > 0 && Math.abs(rule + ml - 1) > 1e-6) {
    problems.push('Tổng trọng số rule + ml phải bằng 1.0')
  }

  return problems
}

/**
 * Validate the risk thresholds.
 *
 * The backend requires `low <= medium <= high`.
 */
export function validateThresholds(
  low: number,
  medium: number,
  high: number,
): string[] {
  const problems: string[] = []

  for (const [name, value] of [
    ['low', low],
    ['medium', medium],
    ['high', high],
  ] as const) {
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      problems.push(`Ngưỡng "${name}" phải nằm trong [0.0, 1.0]`)
    }
  }

  if (problems.length > 0) return problems

  if (!(low <= medium && medium <= high)) {
    problems.push('Các ngưỡng phải thỏa mãn low <= medium <= high')
  }

  return problems
}

/**
 * The version string the backend accepts.
 *
 * The pattern is `^v\d+(\.\d+)*$` — `v1`, `v1.0`, `v3.3.1`. The version
 * is IMMUTABLE after creation, so the editor only ever creates it.
 */
export const VERSION_PATTERN = /^v\d+(\.\d+)*$/

/** Is this a version string the backend accepts? */
export function isValidVersion(version: string): boolean {
  return VERSION_PATTERN.test(version.trim())
}
