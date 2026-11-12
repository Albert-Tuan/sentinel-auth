export interface PlaceholderPageProps {
  title: string
}

/**
 * A stand-in for a feature page that has not been built yet.
 *
 * Stage 0-2 establishes the foundation, the auth flow and the refresh
 * lifecycle. The individual feature screens arrive in later stages.
 */
export function PlaceholderPage({ title }: PlaceholderPageProps) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-6">
      <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
      <p className="mt-2 text-sm text-slate-600">
        Màn hình này sẽ được triển khai ở giai đoạn M12 tiếp theo. Hạ tầng xác
        thực, phân quyền và vòng đời refresh token đã sẵn sàng.
      </p>
    </section>
  )
}
