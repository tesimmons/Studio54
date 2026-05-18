import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../../../api/client'
import { FiCheckCircle, FiXCircle, FiClock, FiActivity } from 'react-icons/fi'

interface StatRow {
  label: string
  value: number | undefined
  icon: React.ReactNode
  color: string
}

export default function JobActivityWidget({
  isEditMode: _isEditMode,
}: {
  widgetId: string
  isEditMode: boolean
  libraryType?: 'music' | 'audiobook'
  widgetSettings?: Record<string, unknown>
  onSettingsChange?: (settings: Record<string, unknown>) => void
}) {
  const { data, isError, isFetching } = useQuery({
    queryKey: ['job-activity-summary', 7],
    queryFn: () => adminApi.getJobActivitySummary(7),
    refetchInterval: 60_000,
    retry: false,
  })

  const rows: StatRow[] = [
    {
      label: 'Total Jobs',
      value: data?.total,
      icon: <FiActivity className="w-4 h-4" />,
      color: '#6b7280',
    },
    {
      label: 'Completed',
      value: data?.completed,
      icon: <FiCheckCircle className="w-4 h-4" />,
      color: '#22c55e',
    },
    {
      label: 'Failed',
      value: data?.failed,
      icon: <FiXCircle className="w-4 h-4" />,
      color: '#ef4444',
    },
    {
      label: 'Running / Pending',
      value: data?.running,
      icon: <FiClock className="w-4 h-4" />,
      color: '#f59e0b',
    },
  ]

  return (
    <div className="h-full flex flex-col p-4 gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-gray-900 dark:text-white">Activity (7 days)</p>
        {isFetching && (
          <span className="text-[11px] text-gray-400 animate-pulse">Refreshing…</span>
        )}
      </div>

      {/* Stats */}
      {isError ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-xs text-red-400">Failed to load job activity</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2 flex-1 justify-center">
          {rows.map((row) => (
            <div
              key={row.label}
              className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-50 dark:bg-[#0D1117]"
            >
              <div className="flex items-center gap-2" style={{ color: row.color }}>
                {row.icon}
                <span className="text-xs text-gray-600 dark:text-gray-400">{row.label}</span>
              </div>
              <span className="text-sm font-semibold tabular-nums text-gray-900 dark:text-white">
                {row.value != null ? row.value.toLocaleString() : '—'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
