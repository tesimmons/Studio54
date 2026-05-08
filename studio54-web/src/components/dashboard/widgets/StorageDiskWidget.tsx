import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../../../api/client'
import { FiHardDrive, FiSettings, FiCheck } from 'react-icons/fi'

// ---------------------------------------------------------------------------
// Mount picker overlay
// ---------------------------------------------------------------------------
function MountPicker({ onSave }: { onSave: (path: string, label: string) => void }) {
  const [path, setPath] = useState('/')
  const [label, setLabel] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const p = path.trim()
    if (!p) return
    onSave(p, label.trim() || p)
  }

  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 p-4">
      <FiHardDrive className="w-6 h-6 text-gray-400" />
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider text-center">
        Configure Storage Widget
      </p>
      <form onSubmit={handleSubmit} className="w-full space-y-2">
        <input
          type="text"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="Mount point (e.g. /, /mnt/data)"
          className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:border-[#FF1493]/50 font-mono"
          autoFocus
        />
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Label (optional)"
          className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:border-[#FF1493]/50"
        />
        <button
          type="submit"
          disabled={!path.trim()}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 text-sm rounded-lg bg-[#FF1493] text-white hover:bg-[#FF1493]/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <FiCheck className="w-3.5 h-3.5" />
          Save
        </button>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Usage bar
// ---------------------------------------------------------------------------
function UsageBar({ percent }: { percent: number }) {
  const color =
    percent >= 90 ? '#ef4444' :
    percent >= 75 ? '#f59e0b' :
    '#22c55e'

  return (
    <div className="w-full h-2 rounded-full bg-gray-200 dark:bg-[#1e2a3a] overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${percent}%`, background: color }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------
export default function StorageDiskWidget({
  widgetId,
  isEditMode,
  widgetSettings,
  onSettingsChange,
}: {
  widgetId: string
  isEditMode: boolean
  libraryType?: 'music' | 'audiobook'
  widgetSettings?: Record<string, unknown>
  onSettingsChange?: (settings: Record<string, unknown>) => void
}) {
  const [reconfiguring, setReconfiguring] = useState(false)

  const mountPath = widgetSettings?.path as string | undefined
  const label     = widgetSettings?.label as string | undefined

  const isConfigured = !!mountPath

  const { data, isFetching, isError } = useQuery({
    queryKey: ['disk-usage', widgetId, mountPath],
    queryFn: () => adminApi.getDiskUsage(mountPath!),
    refetchInterval: 60_000,
    enabled: isConfigured && !reconfiguring,
    retry: false,
  })

  if (!isConfigured || reconfiguring) {
    return (
      <MountPicker
        onSave={(p, l) => {
          onSettingsChange?.({ path: p, label: l })
          setReconfiguring(false)
        }}
      />
    )
  }

  const displayLabel = label || mountPath!
  const percent = data?.percent ?? 0
  const color =
    percent >= 90 ? '#ef4444' :
    percent >= 75 ? '#f59e0b' :
    '#22c55e'

  return (
    <div className="h-full flex flex-col p-4 gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <FiHardDrive className="w-4 h-4 shrink-0" style={{ color: data ? color : '#6b7280' }} />
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">{displayLabel}</p>
            {label && label !== mountPath && (
              <p className="text-[11px] text-gray-400 truncate font-mono">{mountPath}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {data && (
            <span
              className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
              style={{ background: `${color}22`, color }}
            >
              {data.percent.toFixed(0)}% used
            </span>
          )}
          {isFetching && !data && (
            <span className="text-[11px] text-gray-400 animate-pulse">Loading…</span>
          )}
          {isEditMode && (
            <button
              title="Change mount point"
              onClick={() => setReconfiguring(true)}
              className="p-1 rounded text-gray-400 hover:text-[#FF1493] transition-colors"
            >
              <FiSettings className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      {data ? (
        <div className="flex flex-col gap-2 flex-1 justify-center">
          {/* Usage bar */}
          <UsageBar percent={data.percent} />

          {/* Size breakdown */}
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-gray-500 dark:text-gray-400">
              {data.used_human} used
            </span>
            <span className="text-[11px] text-gray-500 dark:text-gray-400">
              {data.free_human} free
            </span>
          </div>

          {/* Total */}
          <div className="pt-2 border-t border-gray-100 dark:border-[#1e2a3a]">
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-gray-500 dark:text-gray-400">Total</span>
              <span className="text-[11px] font-mono font-semibold text-gray-700 dark:text-gray-300">
                {data.total_human}
              </span>
            </div>
          </div>
        </div>
      ) : isError ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-xs text-red-400">Failed to read disk usage</p>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-xs text-gray-400 animate-pulse">Loading…</p>
        </div>
      )}
    </div>
  )
}
