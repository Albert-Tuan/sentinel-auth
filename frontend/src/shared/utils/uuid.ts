/**
 * UUID validation.
 *
 * The backend stores the analyst ids as real UUID columns, so a filter
 * that is not a UUID cannot be matched — PostgreSQL raises a data error
 * and the endpoint answers 500 instead of the expected 400/empty page.
 *
 * The frontend therefore checks the format BEFORE it sends the value, so
 * the queue never produces a request that is known to fail. This mirrors
 * the rule the filter bar already follows for `status` and `risk_level`:
 * only the values the backend accepts are sent.
 */

/**
 * The canonical 8-4-4-4-12 hexadecimal form.
 *
 * It accepts the version nibble of any RFC 4122 variant, because the
 * backend generates its ids with `uuid4()` but stores them as plain UUID
 * columns — the client must not reject a value the server would accept.
 */
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * True when the value is a syntactically valid UUID.
 *
 * An empty string is NOT a valid UUID: the caller decides what an empty
 * filter means (no filter at all).
 */
export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value.trim())
}

/**
 * The message shown when a value is not a UUID.
 */
export const UUID_FORMAT_MESSAGE =
  'Giá trị phải là UUID hợp lệ (ví dụ: 8f3c1d2e-4b5a-6789-0abc-def012345678).'
