export interface PlaceholderPageProps {
  title: string
}

/**
 * A stand-in for a feature page that has not been built yet.
 *
 * The individual feature screens arrive in the M12 stages that follow the
 * foundation; the authentication, authorization and token-refresh
 * lifecycle is already in place behind them.
 */
export function PlaceholderPage({ title }: PlaceholderPageProps) {
  return (
    <section className="border border-border bg-surface-raised p-6">
      <h1 className="page-title text-text">{title}</h1>
      <p className="mt-2 text-sm text-text-muted">
        Màn hình này sẽ được triển khai ở giai đoạn M12 tiếp theo. Hạ tầng xác
        thực, phân quyền và vòng đời refresh token đã sẵn sàng.
      </p>
    </section>
  )
}
