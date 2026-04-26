import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FiPause, FiPlay, FiTrash2, FiRefreshCw, FiAlertCircle } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { queueApi } from '../../api/client'
import type { TrackedDownloadItem, TrackedDownloadState } from '../../types'

// ── helpers ──────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (!bytes) return '—'
  const gb = bytes / 1073741824
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  return `${(bytes / 1048576).toFixed(0)} MB`
}

function formatEta(seconds: number | null): string {
  if (!seconds) return '—'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

const STATE_CONFIG: Record<TrackedDownloadState, { label: string; className: string }> = {
  queued:          { label: 'Queued',          className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  downloading:     { label: 'Downloading',     className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
  paused:          { label: 'Paused',          className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300' },
  import_pending:  { label: 'Import Pending',  className: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300' },
  import_blocked:  { label: 'Import Blocked',  className: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300' },
  importing:       { label: 'Importing',       className: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300' },
  imported:        { label: 'Imported',        className: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' },
  ignored:         { label: 'Ignored',         className: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500' },
  failed:          { label: 'Failed',          className: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' },
}

function StateBadge({ state }: { state: TrackedDownloadState }) {
  const cfg = STATE_CONFIG[state] ?? { label: state, className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' }
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${cfg.className}`}>{cfg.label}</span>
}

function ProgressBar({ progress, state }: { progress: number; state: TrackedDownloadState }) {
  const color =
    state === 'failed' ? 'bg-red-500' :
    state === 'paused' ? 'bg-yellow-400' :
    state === 'imported' ? 'bg-green-500' :
    'bg-[#FF1493]'

  return (
    <div className="w-full bg-gray-200 dark:bg-[#30363D] rounded-full h-1.5">
      <div
        className={`${color} h-1.5 rounded-full transition-all duration-500`}
        style={{ width: `${Math.min(progress, 100)}%` }}
      />
    </div>
  )
}

// ── row actions ───────────────────────────────────────────────────────────────

function RowActions({ item }: { item: TrackedDownloadItem }) {
  const queryClient = useQueryClient()

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['download-queue'] })

  const pauseMutation = useMutation({
    mutationFn: () => queueApi.pause(item.id),
    onSuccess: () => { toast.success('Paused'); invalidate() },
    onError: () => toast.error('Failed to pause'),
  })

  const resumeMutation = useMutation({
    mutationFn: () => queueApi.resume(item.id),
    onSuccess: () => { toast.success('Resumed'); invalidate() },
    onError: () => toast.error('Failed to resume'),
  })

  const removeMutation = useMutation({
    mutationFn: (blacklist: boolean) => queueApi.remove(item.id, blacklist),
    onSuccess: () => { toast.success('Removed from queue'); invalidate() },
    onError: () => toast.error('Failed to remove'),
  })

  const retryImportMutation = useMutation({
    mutationFn: () => queueApi.retryImport(item.id),
    onSuccess: () => { toast.success('Retrying import'); invalidate() },
    onError: () => toast.error('Failed to retry import'),
  })

  const canPause = item.state === 'downloading' || item.state === 'queued'
  const canResume = item.state === 'paused'
  const canRetryImport = item.state === 'import_blocked'
  const isActive = ['queued', 'downloading', 'paused', 'import_pending', 'import_blocked', 'importing'].includes(item.state)

  return (
    <div className="flex items-center gap-1">
      {canPause && (
        <button
          onClick={() => pauseMutation.mutate()}
          disabled={pauseMutation.isPending}
          title="Pause"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-[#FF1493] transition-colors"
        >
          <FiPause size={14} />
        </button>
      )}
      {canResume && (
        <button
          onClick={() => resumeMutation.mutate()}
          disabled={resumeMutation.isPending}
          title="Resume"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-green-500 transition-colors"
        >
          <FiPlay size={14} />
        </button>
      )}
      {canRetryImport && (
        <button
          onClick={() => retryImportMutation.mutate()}
          disabled={retryImportMutation.isPending}
          title="Retry Import"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-blue-500 transition-colors"
        >
          <FiRefreshCw size={14} />
        </button>
      )}
      {isActive && (
        <button
          onClick={() => {
            if (confirm(`Remove "${item.title}" from queue?`)) {
              removeMutation.mutate(false)
            }
          }}
          disabled={removeMutation.isPending}
          title="Remove from queue"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-red-500 transition-colors"
        >
          <FiTrash2 size={14} />
        </button>
      )}
      {item.state === 'failed' && (
        <button
          onClick={() => {
            if (confirm(`Blacklist this release?\n"${item.title}"`)) {
              removeMutation.mutate(true)
            }
          }}
          disabled={removeMutation.isPending}
          title="Blacklist this release"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-red-500 transition-colors"
        >
          <FiTrash2 size={14} />
        </button>
      )}
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export default function DownloadQueueTab() {
  const [includeCompleted, setIncludeCompleted] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['download-queue', includeCompleted],
    queryFn: () => queueApi.getQueue({ include_completed: includeCompleted, limit: 200 }),
    refetchInterval: 5000,
  })

  const items = data?.items ?? []
  const activeCount = items.filter(i =>
    ['queued', 'downloading', 'paused', 'import_pending', 'import_blocked', 'importing'].includes(i.state)
  ).length

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
          {isLoading
            ? <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-[#FF1493]" />
            : <span><strong className="text-gray-900 dark:text-[#E6EDF3]">{activeCount}</strong> active</span>
          }
          {data && data.count !== activeCount && (
            <span>· {data.count} total</span>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={includeCompleted}
            onChange={e => setIncludeCompleted(e.target.checked)}
            className="rounded"
          />
          Show completed
        </label>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {isError && (
          <div className="text-center py-12 text-red-500 dark:text-red-400">
            Failed to load download queue
          </div>
        )}

        {!isLoading && !isError && items.length === 0 && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            {includeCompleted ? 'No downloads found' : 'No active downloads'}
          </div>
        )}

        {!isError && items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#161B22]/50">
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Release</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Album / Artist</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Status</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 w-40">Progress</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Size</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">ETA</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Indexer</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
                {items.map(item => (
                  <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                    <td className="px-4 py-3">
                      <div className="max-w-xs">
                        <span
                          className="text-gray-800 dark:text-[#E6EDF3] text-xs font-mono leading-tight block truncate"
                          title={item.title}
                        >
                          {item.title}
                        </span>
                        {item.quality && (
                          <span className="text-xs text-gray-500 dark:text-gray-500 mt-0.5 block">
                            {item.quality}
                          </span>
                        )}
                        {item.error_message && (
                          <span className="flex items-center gap-1 text-xs text-red-500 dark:text-red-400 mt-0.5" title={item.error_message}>
                            <FiAlertCircle size={10} />
                            {item.error_message.slice(0, 60)}{item.error_message.length > 60 ? '…' : ''}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-xs space-y-0.5">
                        {item.album_id && item.album_title && (
                          <Link
                            to={`/disco-lounge/albums/${item.album_id}`}
                            className="text-[#FF1493] hover:underline block font-medium"
                          >
                            {item.album_title}
                          </Link>
                        )}
                        {item.artist_id && item.artist_name && (
                          <Link
                            to={`/disco-lounge/artists/${item.artist_id}`}
                            className="text-gray-600 dark:text-gray-400 hover:underline block"
                          >
                            {item.artist_name}
                          </Link>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <StateBadge state={item.state} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="space-y-1 min-w-[120px]">
                        <ProgressBar progress={item.progress} state={item.state} />
                        <div className="flex justify-between text-xs text-gray-500 dark:text-gray-500">
                          <span>{item.progress.toFixed(0)}%</span>
                          <span>{formatBytes(item.downloaded_bytes)} / {formatBytes(item.size_bytes)}</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400 text-xs">
                      {formatBytes(item.size_bytes)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400 text-xs">
                      {formatEta(item.eta_seconds)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400 text-xs">
                      {item.indexer || '—'}
                    </td>
                    <td className="px-4 py-3">
                      <RowActions item={item} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
