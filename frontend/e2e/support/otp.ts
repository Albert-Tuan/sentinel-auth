/**
 * The OTP reader.
 *
 * The MFA code of the demo stack travels through a REAL SMTP hop into
 * the local sink (`scripts/ci_smtp_sink.py`), which appends one block
 * per message to `.ci/demo/demo-otp.log`:
 *
 *     TO=['<demo_admin@example.test>'] SUBJECT=Sentinel Auth verification code
 *     Your Sentinel Auth verification code is 352189. It expires in 5 minutes.
 *     ---
 *
 * The reader is OFFSET-BASED, and that is not an optimisation — it is a
 * correctness requirement.  The log accumulates the codes of EVERY
 * earlier login, so a code read without an offset may well belong to a
 * PREVIOUS login.  The API rejects a stale code as "Invalid MFA code",
 * and the test would fail for a reason that has nothing to do with the
 * behaviour it is supposed to check.
 *
 * The code therefore follows the same rule as
 * `scripts/demo_scenarios.py`: take the offset BEFORE the login is
 * triggered, and read only what was written after it.
 */

import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** The repository root. */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** The default OTP log. */
export const DEFAULT_OTP_LOG = resolve(REPO_ROOT, '.ci', 'demo', 'demo-otp.log')

/**
 * The pointer file the demo stack writes.
 *
 * `scripts/demo_stack.sh` resolves a relative `MFA_SMTP_LOG` against the
 * repository root and writes the RESOLVED path to this file, so the
 * sink and the reader can never disagree about which file it is.
 */
const OTP_LOG_POINTER = resolve(REPO_ROOT, '.ci', 'demo', 'otp-log.path')

/** The path of the OTP log the running demo stack actually writes to. */
export function otpLogPath(): string {
  if (existsSync(OTP_LOG_POINTER)) {
    const pointer = readFileSync(OTP_LOG_POINTER, 'utf8').trim()
    if (pointer) return pointer
  }
  return process.env.MFA_SMTP_LOG?.trim() || DEFAULT_OTP_LOG
}

/** The current size of the log, in bytes. */
export function otpOffset(): number {
  try {
    return statSync(otpLogPath()).size
  } catch {
    return 0
  }
}

/** The part of the log written after `offset`. */
function textFrom(offset: number): string {
  try {
    const buffer = readFileSync(otpLogPath())
    return buffer.subarray(offset).toString('utf8')
  } catch {
    return ''
  }
}

/**
 * The most recent code addressed to `recipient`, considering only the
 * bytes written after `offset`.
 */
export function latestCode(recipient: string, offset: number): string | null {
  const pattern = /(?<!\d)(\d{6})(?!\d)/
  const blocks = textFrom(offset).split('\n---\n')

  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (!block.includes(recipient)) continue
    // The body is the part after the header line.
    const body = block.includes('\n') ? block.slice(block.indexOf('\n') + 1) : block
    const match = pattern.exec(body)
    if (match) return match[1]
  }

  return null
}

/**
 * Wait for the SMTP sink to deliver a code to `recipient`.
 *
 * The wait is bounded: a code that never arrives is a FAILURE, not a
 * timeout that silently passes.  The suite has no zero-timeout policy —
 * a missing OTP is exactly the kind of defect this suite exists to
 * find.
 */
export async function waitForCode(
  recipient: string,
  offset: number,
  timeoutMs = 30_000,
): Promise<string> {
  const deadline = Date.now() + timeoutMs

  while (Date.now() < deadline) {
    const code = latestCode(recipient, offset)
    if (code) return code
    await new Promise((resolve_) => setTimeout(resolve_, 250))
  }

  throw new Error(
    `no MFA code arrived for '${recipient}' within ${timeoutMs}ms. ` +
      'The SMTP sink did not deliver a code for this login.',
  )
}
