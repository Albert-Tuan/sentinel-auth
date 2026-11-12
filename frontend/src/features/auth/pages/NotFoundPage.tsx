import { Link } from 'react-router-dom'
import { PATHS } from '@/app/router/paths'

export function NotFoundPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-100 px-4 text-center">
      <p className="text-sm font-semibold text-slate-500">404</p>
      <h1 className="text-2xl font-semibold text-slate-900">Không tìm thấy trang</h1>
      <p className="max-w-md text-sm text-slate-600">
        Đường dẫn bạn truy cập không tồn tại hoặc không thuộc phân quyền của bạn.
      </p>
      <Link
        to={PATHS.home}
        className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
      >
        Về trang chủ
      </Link>
    </main>
  )
}
