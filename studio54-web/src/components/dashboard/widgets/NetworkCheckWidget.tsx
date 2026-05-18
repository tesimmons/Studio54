import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../../../api/client'
import { FiWifi, FiWifiOff, FiSettings, FiCheck } from 'react-icons/fi'

// ---------------------------------------------------------------------------
// Host configuration overlay — shown when no host is set
// ---------------------------------------------------------------------------
function HostPicker({ onSave }: { onSave: (host: string, label: string) => void }) {
  const [host, setHost] = useState('')
  const [label, setLabel] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const h = host.trim()
    if (!h) return
    onSave(h, label.trim() || h)
  }

  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 p-4">
      <FiWifi className="w-6 h-6 text-gray-400" />
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider text-center">
        Configure Network Check
      </p>
      <form onSubmit={handleSubmit} className="w-full space-y-2">
        <input
          type="text"
          value={host}
          onChange={(e) => setHost(e.target.value)}
          placeholder="Host or IP (e.g. 8.8.8.8)"
          className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:border-[#FF1493]/50"
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
          disabled={!host.trim()}
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
// Helpers
// ---------------------------------------------------------------------------
function RttBar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = Math.min((value / max) * 100, 100)
  return (
    <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-[#1e2a3a] overflow-hidden">
      <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}

function statusColor(reachable: boolean, loss: number): string {
  if (!reachable || loss === 100) return '#ef4444'   // red
  if (loss > 0)                  return '#f59e0b'   // amber
  return '#22c55e'                                  // green
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------
export default function NetworkCheckWidget({
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

  const host  = widgetSettings?.host  as string | undefined
  const label = widgetSettings?.label as string | undefined

  const isConfigured = !!host

  const { data, isFetching, isError } = useQuery({
    queryKey: ['network-ping', widgetId, host],
    queryFn: () => adminApi.pingHost(host!, 4),
    refetchInterval: 30_000,
    enabled: isConfigured && !reconfiguring,
    retry: false,
  })

  // Show picker when not yet configured, or user clicked reconfigure
  if (!isConfigured || reconfiguring) {
    return (
      <HostPicker
        onSave={(h, l) => {
          onSettingsChange?.({ host: h, label: l })
          setReconfiguring(false)
        }}
      />
    )
  }

  const color = data ? statusColor(data.reachable, data.packet_loss_percent) : '#6b7280'
  const rttMax = data?.rtt_max_ms ?? 200

  return (
    <div className="h-full flex flex-col p-4 gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          {data?.reachable === false ? (
            <FiWifiOff className="w-4 h-4 shrink-0" style={{ color }} />
          ) : (
            <FiWifi className="w-4 h-4 shrink-0" style={{ color }} />
          )}
          <div className="min-w-0">
            <p className="text-sm font-semibold text-gray-900 dark:text-white truncate">{label || host}</p>
            {label && label !== host && (
              <p className="text-[11px] text-gray-400 truncate font-mono">{host}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {/* Status pill */}
          {data && (
            <span
              className="text-[11px] font-semibold px-2 py-0.5 rounded-full"
              style={{ background: `${color}22`, color }}
            >
              {data.reachable ? (data.packet_loss_percent > 0 ? 'Degraded' : 'Online') : 'Offline'}
            </span>
          )}
          {isFetching && !data && (
            <span className="text-[11px] text-gray-400 animate-pulse">Checking…</span>
          )}
          {/* Reconfigure (edit mode only) */}
          {isEditMode && (
            <button
              title="Change host"
              onClick={() => setReconfiguring(true)}
              className="p-1 rounded text-gray-400 hover:text-[#FF1493] transition-colors"
            >
              <FiSettings className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Stats */}
      {data ? (
        <div className="flex flex-col gap-2 flex-1 justify-center">
          {/* RTT rows */}
          {([
            { key: 'Min', value: data.rtt_min_ms },
            { key: 'Avg', value: data.rtt_avg_ms },
            { key: 'Max', value: data.rtt_max_ms },
          ] as const).map(({ key, value }) => (
            <div key={key} className="flex items-center gap-2">
              <span className="text-[11px] w-6 text-gray-500 dark:text-gray-400 shrink-0">{key}</span>
              {value != null ? (
                <>
                  <RttBar value={value} max={Math.max(rttMax * 1.1, 1)} color={color} />
                  <span className="text-[11px] font-mono tabular-nums text-gray-700 dark:text-gray-300 w-14 text-right shrink-0">
                    {value.toFixed(1)} ms
                  </span>
                </>
              ) : (
                <>
                  <div className="flex-1 h-1.5 rounded-full bg-gray-200 dark:bg-[#1e2a3a]" />
                  <span className="text-[11px] text-gray-400 w-14 text-right shrink-0">–</span>
                </>
              )}
            </div>
          ))}

          {/* Packet loss */}
          <div className="flex items-center justify-between mt-1 pt-2 border-t border-gray-100 dark:border-[#1e2a3a]">
            <span className="text-[11px] text-gray-500 dark:text-gray-400">
              {data.packets_received}/{data.packets_sent} packets
            </span>
            <span
              className="text-[11px] font-mono tabular-nums font-semibold"
              style={{ color: data.packet_loss_percent > 0 ? '#f59e0b' : '#22c55e' }}
            >
              {data.packet_loss_percent.toFixed(0)}% loss
            </span>
          </div>
        </div>
      ) : isError ? (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-xs text-red-400">Check failed</p>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center">
          <p className="text-xs text-gray-400 animate-pulse">Pinging…</p>
        </div>
      )}
    </div>
  )
}
