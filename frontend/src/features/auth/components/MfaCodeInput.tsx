import { useState, type FormEvent } from 'react'
import { Button } from '@/shared/components/Button'
import { ErrorState } from '@/shared/components/ErrorState'
import type { ApiError } from '@/lib/errors'

export interface MfaCodeInputProps {
  onSubmit: (code: string) => Promise<boolean>
  loading?: boolean
  error?: ApiError | null
  onCancel?: () => void
}

/**
 * The MFA code entry form.
 *
 * The backend requires exactly six digits (`^\d{6}$`), so the input is
 * restricted to digits and validated before the request is sent.
 */
export function MfaCodeInput({
  onSubmit,
  loading = false,
  error,
  onCancel,
}: MfaCodeInputProps) {
  const [code, setCode] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLocalError(null)

    if (!/^\d{6}$/.test(code)) {
      setLocalError('Mã xác thực phải gồm đúng 6 chữ số.')
      return
    }

    await onSubmit(code)
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      {error && <ErrorState message={error.userMessage} />}
      {localError && !error && <ErrorState message={localError} />}

      <div className="flex flex-col gap-1">
        <label htmlFor="mfa-code" className="text-sm font-medium text-slate-700">
          Mã xác thực
        </label>
        <input
          id="mfa-code"
          name="mfa_code"
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          pattern="\d{6}"
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ''))}
          disabled={loading}
          className="rounded-md border border-slate-300 px-3 py-2 text-center font-mono text-lg tracking-[0.5em] outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-100"
        />
        <p className="text-xs text-slate-500">
          Nhập mã 6 chữ số đã được gửi tới kênh xác thực của bạn.
        </p>
      </div>

      <div className="flex gap-2">
        <Button type="submit" loading={loading} fullWidth>
          {loading ? 'Đang xác thực...' : 'Xác thực'}
        </Button>
        {onCancel && (
          <Button type="button" variant="secondary" onClick={onCancel} disabled={loading}>
            Quay lại
          </Button>
        )}
      </div>
    </form>
  )
}
