import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FiClock, FiStopCircle, FiPlay, FiSearch, FiSlash } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { albumsApi, queueApi } from '../api/client'
import type { AlbumDownloadEvent, RetryControlRequest } from '../types'

const EVENT_BADGE: Record<string, { label: string; className: string }> = {
  grabbed:          { label: 'Grabbed',       className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
  download_failed:  { label: 'Failed',        className: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' },
  retry_scheduled:  { label: 'Retry',         className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400' },
  imported:         { label: 'Imported',      className: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400' },
  import_failed:    { label: 'Import Failed', className: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-400' },
}

function EventBadge({ type }: { type: string }) {
  const cfg = EVENT_BADGE[type] ?? {
    label: type,
    className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap shrink-0 ${cfg.className}`}>
      {cfg.label}
    </span>
  )
}

function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function DownloadTimeline({ albumId }: { albumId: string }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['album-download-history', albumId],
    queryFn: () => albumsApi.getDownloadHistory(albumId),
    refetchInterval: 30000,
    enabled: open,
  })

  const retryControlMutation = useMutation({
    mutationFn: (req: RetryControlRequest) => albumsApi.retryControl(albumId, req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['album-download-history', albumId] })
    },
    onError: () => toast.error('Failed to update retry settings'),
  })

  const blacklistMutation = useMutation({
    mutationFn: ({ guid, title }: { guid: string; title?: string }) =>
      queueApi.addToBlacklist(guid, title, albumId),
    onSuccess: () => toast.success('NZB blacklisted'),
    onError: () => toast.error('Failed to blacklist NZB'),
  })

  const retryEnabled = data?.retry_enabled ?? true
  const nextRetry = data?.next_retry_at
  const retryCount = data?.download_retry_count ?? 0
  const events = data?.events ?? []

  return (
    <div className="mt-6 border-t border-gray-200 dark:border-[#30363D] pt-4">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 text-sm font-semibold text-gray-700 dark:text-[#E6EDF3] hover:text-[#FF1493] dark:hover:text-[#FF1493] transition-colors w-full text-left"
      >
        <FiClock size={14} />
        Download Timeline
        <span className="ml-auto text-gray-400 dark:text-gray-500 font-normal text-xs">
          {open ? '▲' : '▼'}
        </span>
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          {/* Retry status bar */}
          {data && (
            <div className="flex items-center gap-3 flex-wrap">
              {/* Status badge */}
              {!retryEnabled
                ? <span className="px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">Stopped</span>
                : nextRetry
                ? <span className="px-2 py-1 rounded text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">Retrying</span>
                : <span className="px-2 py-1 rounded text-xs font-medium bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400">Active</span>
              }
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {retryCount} attempt{retryCount !== 1 ? 's' : ''}
              </span>
              {nextRetry && (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  · Next search at {new Date(nextRetry).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
                </span>
              )}

              <div className="flex gap-2 ml-auto">
                {retryEnabled ? (
                  <button
                    onClick={() => retryControlMutation.mutate({ retry_enabled: false })}
                    disabled={retryControlMutation.isPending}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-gray-200 dark:border-[#30363D] text-gray-600 dark:text-gray-400 hover:text-red-600 hover:border-red-300 dark:hover:text-red-400 dark:hover:border-red-800 transition-colors disabled:opacity-50"
                  >
                    <FiStopCircle size={11} />
                    Stop Retrying
                  </button>
                ) : (
                  <button
                    onClick={() => retryControlMutation.mutate({ retry_enabled: true })}
                    disabled={retryControlMutation.isPending}
                    className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-gray-200 dark:border-[#30363D] text-gray-600 dark:text-gray-400 hover:text-green-600 hover:border-green-300 dark:hover:text-green-400 dark:hover:border-green-800 transition-colors disabled:opacity-50"
                  >
                    <FiPlay size={11} />
                    Resume
                  </button>
                )}
                <button
                  onClick={() => retryControlMutation.mutate({ retry_enabled: true, search_now: true })}
                  disabled={retryControlMutation.isPending}
                  className="flex items-center gap-1 px-2.5 py-1 text-xs rounded border border-gray-200 dark:border-[#30363D] text-gray-600 dark:text-gray-400 hover:text-blue-600 hover:border-blue-300 dark:hover:text-blue-400 dark:hover:border-blue-800 transition-colors disabled:opacity-50"
                >
                  <FiSearch size={11} />
                  Search Now
                </button>
              </div>
            </div>
          )}

          {/* Event list */}
          {isLoading && (
            <div className="flex justify-center py-6">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-[#FF1493]" />
            </div>
          )}

          {!isLoading && events.length === 0 && (
            <p className="text-sm text-gray-500 dark:text-gray-400 py-2">No download attempts yet</p>
          )}

          {events.length > 0 && (
            <div className="card overflow-hidden">
              <div className="divide-y divide-gray-200 dark:divide-[#30363D]">
                {events.map((event: AlbumDownloadEvent) => (
                  <div
                    key={event.id}
                    className="px-4 py-3 flex items-start gap-3 hover:bg-gray-50 dark:hover:bg-[#161B22]/50"
                  >
                    <EventBadge type={event.event_type} />
                    <div className="flex-1 min-w-0">
                      {event.release_title && (
                        <p
                          className="text-xs font-mono text-gray-800 dark:text-[#E6EDF3] truncate"
                          title={event.release_title}
                        >
                          {event.release_title}
                        </p>
                      )}
                      {event.message && (
                        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                          {event.message}
                        </p>
                      )}
                    </div>
                    <span className="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap shrink-0">
                      {formatTime(event.created_at)}
                    </span>
                    {event.event_type === 'download_failed' && event.release_guid && (
                      <button
                        onClick={() => {
                          if (confirm(`Blacklist this NZB?\n"${event.release_title}"`)) {
                            blacklistMutation.mutate({
                              guid: event.release_guid!,
                              title: event.release_title ?? undefined,
                            })
                          }
                        }}
                        disabled={blacklistMutation.isPending}
                        title="Blacklist this NZB"
                        className="shrink-0 p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
                      >
                        <FiSlash size={12} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
