import { Link } from 'react-router-dom'
import { PATHS } from '@/app/router/paths'

export function ForbiddenPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-100 px-4 text-center">
      <p className="text-sm font-semibold text-slate-500">403</p>
      <h1 className="text-2xl font-semibold text-slate-900">
        Không đủ quyền truy cập
      </h1>
      <p className="max-w-md text-sm text-slate-600">
        Tài khoản của bạn không được phân quyền cho khu vực này. Nếu đây là
        nhầm lẫn, vui lòng liên hệ quản trị viên.
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
