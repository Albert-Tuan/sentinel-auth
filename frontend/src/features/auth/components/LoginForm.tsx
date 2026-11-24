import { useState, type FormEvent } from 'react'
import { Button } from '@/shared/components/Button'
import { Input } from '@/shared/components/Input'
import { ErrorState } from '@/shared/components/ErrorState'
import type { ApiError } from '@/lib/errors'

export interface LoginFormProps {
  onSubmit: (username: string, password: string) => Promise<boolean>
  loading?: boolean
  error?: ApiError | null
}

/**
 * The login form.
 *
 * The form never interprets the response itself — the auth state machine
 * owns that. It only reports the credentials and renders whatever error the
 * state machine produced.
 */
export function LoginForm({ onSubmit, loading = false, error }: LoginFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLocalError(null)

    if (!username.trim()) {
      setLocalError('Vui lòng nhập tên đăng nhập.')
      return
    }
    if (!password) {
      setLocalError('Vui lòng nhập mật khẩu.')
      return
    }

    await onSubmit(username.trim(), password)
  }

  const fieldError = (field: string) => error?.issueFor(field)?.message

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>
      {error && <ErrorState message={error.userMessage} />}
      {localError && !error && <ErrorState message={localError} />}

      <Input
        label="Tên đăng nhập"
        name="username"
        autoComplete="username"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        error={fieldError('username')}
        disabled={loading}
        required
      />

      <Input
        label="Mật khẩu"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        error={fieldError('password')}
        disabled={loading}
        required
      />

      <Button type="submit" loading={loading} fullWidth>
        {loading ? 'Đang đăng nhập...' : 'Đăng nhập'}
      </Button>
    </form>
  )
}
