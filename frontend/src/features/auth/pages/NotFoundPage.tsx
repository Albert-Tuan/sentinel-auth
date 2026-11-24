import { Link } from 'react-router-dom'
import { PATHS } from '@/app/router/paths'

export function NotFoundPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-surface px-4 text-center">
      <p className="label-ops text-degraded">404</p>
      <h1 className="page-title text-text">Không tìm thấy trang</h1>
      <p className="max-w-md text-sm text-text-muted">
        Đường dẫn bạn truy cập không tồn tại hoặc không thuộc phân quyền của bạn.
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
