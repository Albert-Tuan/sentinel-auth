/**
 * S-06 — Trusted Devices (`/devices`).
 *
 * The backend only ever returns the CURRENT user's devices, so the screen
 * never has to filter by owner.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { Badge } from '@/shared/components/Badge'
import { Button } from '@/shared/components/Button'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { DataTable, type TableColumn } from '@/shared/components/DataTable'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorState } from '@/shared/components/ErrorState'
import { Input } from '@/shared/components/Input'
import { Spinner } from '@/shared/components/Spinner'

import {
  fetchTrustedDevices,
  trustDevice,
  untrustAllDevices,
  untrustDevice,
} from '@/lib/api/devices.api'
import { describeUserAgent, formatDateTime, isExpired } from '@/lib/datetime'
import { errorMessage } from '@/lib/errors'
import type { TrustedDeviceItem } from '@/types/api'

const DEVICES_QUERY_KEY = ['devices'] as const

/** The backend accepts 1..365 days; 30 is its own default. */
const DEFAULT_REMEMBER_DAYS = 30

export function TrustedDevicesPage() {
  const queryClient = useQueryClient()

  const [deviceName, setDeviceName] = useState('')
  const [rememberDays, setRememberDays] = useState(String(DEFAULT_REMEMBER_DAYS))
  const [formError, setFormError] = useState<string | null>(null)
  const [untrustTarget, setUntrustTarget] = useState<TrustedDeviceItem | null>(
    null,
  )
  const [untrustAllOpen, setUntrustAllOpen] = useState(false)

  const devicesQuery = useQuery({
    queryKey: DEVICES_QUERY_KEY,
    queryFn: fetchTrustedDevices,
  })

  const trustMutation = useMutation({
    mutationFn: () =>
      trustDevice({
        device_name: deviceName.trim() || null,
        remember_for_days: Number(rememberDays),
      }),
    onSuccess: async () => {
      setDeviceName('')
      setFormError(null)
      await queryClient.invalidateQueries({ queryKey: DEVICES_QUERY_KEY })
    },
    onError: (error) => setFormError(errorMessage(error)),
  })

  const untrustMutation = useMutation({
    mutationFn: (deviceId: string) => untrustDevice(deviceId),
    onSuccess: async () => {
      setUntrustTarget(null)
      await queryClient.invalidateQueries({ queryKey: DEVICES_QUERY_KEY })
    },
  })

  const untrustAllMutation = useMutation({
    mutationFn: () => untrustAllDevices(),
    onSuccess: async () => {
      setUntrustAllOpen(false)
      await queryClient.invalidateQueries({ queryKey: DEVICES_QUERY_KEY })
    },
  })

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)

    const days = Number(rememberDays)
    if (!Number.isInteger(days) || days < 1 || days > 365) {
      setFormError('Số ngày phải là số nguyên từ 1 đến 365.')
      return
    }
    if (deviceName.trim().length > 100) {
      setFormError('Tên thiết bị không được vượt quá 100 ký tự.')
      return
    }

    trustMutation.mutate()
  }

  const columns: TableColumn<TrustedDeviceItem>[] = [
    {
      key: 'name',
      header: 'Tên thiết bị',
      render: (device) => device.device_name || <span className="text-slate-400">—</span>,
    },
    {
      key: 'device',
      header: 'Thiết bị',
      render: (device) => (
        <span title={device.last_user_agent ?? undefined}>
          {describeUserAgent(device.last_user_agent)}
        </span>
      ),
    },
    {
      key: 'ip',
      header: 'IP gần nhất',
      render: (device) => device.last_ip ?? '—',
    },
    {
      key: 'lastUsed',
      header: 'Dùng lần cuối',
      render: (device) => formatDateTime(device.last_used_at),
    },
    {
      key: 'expires',
      header: 'Hết hạn',
      render: (device) =>
        device.expires_at ? (
          <span className="flex items-center gap-2">
            {formatDateTime(device.expires_at)}
            {isExpired(device.expires_at) && (
              <Badge tone="danger">Đã hết hạn</Badge>
            )}
          </span>
        ) : (
          <Badge tone="neutral">Không hết hạn</Badge>
        ),
    },
    {
      key: 'actions',
      header: '',
      render: (device) => (
        <Button
          variant="ghost"
          className="text-red-600 hover:bg-red-50"
          onClick={() => setUntrustTarget(device)}
          aria-label={`Gỡ bỏ thiết bị ${device.device_name ?? device.id}`}
        >
          Gỡ bỏ
        </Button>
      ),
    },
  ]

  const devices = devicesQuery.data?.devices ?? []

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">
            Thiết bị tin cậy
          </h1>
          <p className="text-sm text-slate-500">
            Thiết bị đã được tin cậy có thể đăng nhập mà không cần mã xác
            thực hai yếu tố.
          </p>
        </div>
        <Button
          variant="danger"
          onClick={() => setUntrustAllOpen(true)}
          disabled={devices.length === 0}
        >
          Gỡ bỏ tất cả
        </Button>
      </header>

      <form
        onSubmit={handleSubmit}
        noValidate
        className="flex flex-wrap items-end gap-3 rounded-md border border-slate-200 bg-white p-4"
      >
        <div className="min-w-56 flex-1">
          <Input
            label="Tên thiết bị"
            value={deviceName}
            maxLength={100}
            placeholder="Ví dụ: Laptop văn phòng"
            onChange={(event) => setDeviceName(event.target.value)}
          />
        </div>
        <div className="w-40">
          <Input
            label="Ghi nhớ (ngày)"
            type="number"
            min={1}
            max={365}
            value={rememberDays}
            onChange={(event) => setRememberDays(event.target.value)}
          />
        </div>
        <Button type="submit" loading={trustMutation.isPending}>
          Tin cậy thiết bị này
        </Button>
      </form>

      {formError && (
        <ErrorState title="Không thể tin cậy thiết bị" message={formError} />
      )}

      {trustMutation.isSuccess && (
        <p className="text-sm text-emerald-700">
          {trustMutation.data.message}
        </p>
      )}

      {devicesQuery.isPending && (
        <div className="flex items-center gap-2 text-sm text-slate-600">
          <Spinner /> Đang tải danh sách thiết bị…
        </div>
      )}

      {devicesQuery.isError && (
        <ErrorState
          message={errorMessage(devicesQuery.error)}
          action={
            <Button
              variant="secondary"
              onClick={() => void devicesQuery.refetch()}
            >
              Thử lại
            </Button>
          }
        />
      )}

      {devicesQuery.isSuccess && (
        <DataTable
          columns={columns}
          rows={devices}
          rowKey={(device) => device.id}
          caption="Danh sách thiết bị tin cậy"
          empty={
            <EmptyState
              title="Chưa có thiết bị tin cậy nào"
              description="Tin cậy thiết bị này để đăng nhập nhanh hơn ở lần sau."
            />
          }
        />
      )}

      {untrustMutation.isError && (
        <ErrorState
          title="Không thể gỡ bỏ thiết bị"
          message={errorMessage(untrustMutation.error)}
        />
      )}

      <ConfirmDialog
        open={untrustTarget !== null}
        title="Gỡ bỏ thiết bị tin cậy?"
        message="Thiết bị này sẽ phải đăng nhập lại và xác thực hai yếu tố ở lần sau."
        confirmLabel="Gỡ bỏ"
        destructive
        busy={untrustMutation.isPending}
        onCancel={() => setUntrustTarget(null)}
        onConfirm={() => {
          if (untrustTarget) untrustMutation.mutate(untrustTarget.id)
        }}
      />

      <ConfirmDialog
        open={untrustAllOpen}
        title="Gỡ bỏ tất cả thiết bị tin cậy?"
        message="Mọi thiết bị đã tin cậy sẽ bị gỡ bỏ. Hành động này không thể hoàn tác và mọi thiết bị sẽ phải đăng nhập lại kèm xác thực hai yếu tố."
        confirmLabel="Gỡ bỏ tất cả"
        destructive
        busy={untrustAllMutation.isPending}
        onCancel={() => setUntrustAllOpen(false)}
        onConfirm={() => untrustAllMutation.mutate()}
      />
    </div>
  )
}
