import { Link } from 'react-router-dom'
import { PATHS } from '@/app/router/paths'

export function ForbiddenPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-surface px-4 text-center">
      <p className="label-ops text-warning">403</p>
      <h1 className="page-title text-text">
        Không đủ quyền truy cập
      </h1>
      <p className="max-w-md text-sm text-text-muted">
        Tài khoản của bạn không được phân quyền cho khu vực này. Nếu đây là
        nhầm lẫn, vui lòng liên hệ quản trị viên.
      </p>
      <Link
        to={PATHS.home}
        className="label-ops border border-primary bg-primary px-4 py-2 text-on-primary hover:bg-secondary hover:border-secondary"
      >
        Về trang chủ
      </Link>
    </main>
  )
}
