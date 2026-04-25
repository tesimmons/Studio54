import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FiX, FiDownload, FiSearch, FiCheck, FiAlertCircle, FiClock } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { searchApi } from '../api/client'
import type { ManualSearchDecision } from '../types'

interface Props {
  albumId: string
  albumTitle: string
  onClose: () => void
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '—'
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(0)} MB`
}

function QualityBadge({ quality, format, bitrate }: { quality: string; format: string | null; bitrate: number | null }) {
  const isLossless = quality?.includes('FLAC') || quality?.includes('ALAC') || quality?.includes('WAV')
  const bg = isLossless
    ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300'
    : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'

  const label = bitrate ? `${format || quality} ${bitrate}kbps` : (format || quality || '?')
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${bg}`}>{label}</span>
}

function DecisionBadge({ decision }: { decision: ManualSearchDecision }) {
  if (decision.approved) {
    return (
      <span className="flex items-center gap-1 text-green-600 dark:text-green-400 text-xs font-medium">
        <FiCheck size={12} /> Approved
      </span>
    )
  }
  if (decision.temporarily_rejected) {
    return (
      <span
        className="flex items-center gap-1 text-yellow-600 dark:text-yellow-400 text-xs font-medium cursor-help"
        title={decision.rejections.map(r => r.reason).join('\n')}
      >
        <FiClock size={12} /> Pending
      </span>
    )
  }
  return (
    <span
      className="flex items-center gap-1 text-red-600 dark:text-red-400 text-xs font-medium cursor-help"
      title={decision.rejections.map(r => r.reason).join('\n')}
    >
      <FiAlertCircle size={12} /> Rejected
    </span>
  )
}

export default function ManualSearchModal({ albumId, albumTitle, onClose }: Props) {
  const queryClient = useQueryClient()
  const [grabbingGuid, setGrabbingGuid] = useState<string | null>(null)
  const [showRejected, setShowRejected] = useState(false)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['manual-search', albumId],
    queryFn: () => searchApi.searchAlbum(albumId),
    staleTime: 0,
    gcTime: 0,
  })

  const grabMutation = useMutation({
    mutationFn: (guid: string) => searchApi.grabRelease(albumId, guid),
    onMutate: (guid) => setGrabbingGuid(guid),
    onSuccess: () => {
      toast.success('Grabbed — download queued in SABnzbd')
      queryClient.invalidateQueries({ queryKey: ['album', albumId] })
      queryClient.invalidateQueries({ queryKey: ['download-queue'] })
      onClose()
    },
    onError: (err: Error) => {
      toast.error(err.message || 'Failed to grab release')
    },
    onSettled: () => setGrabbingGuid(null),
  })

  const decisions = data?.decisions ?? []
  const visible = showRejected ? decisions : decisions.filter(d => d.approved || d.temporarily_rejected)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#161B22] border border-gray-200 dark:border-[#30363D] rounded-lg shadow-xl w-full max-w-5xl max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-[#30363D]">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-[#E6EDF3] flex items-center gap-2">
              <FiSearch size={18} className="text-[#FF1493]" />
              Manual Search
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{albumTitle}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400"
          >
            <FiX size={18} />
          </button>
        </div>

        {/* Summary bar */}
        {data && (
          <div className="flex items-center gap-4 px-5 py-2.5 bg-gray-50 dark:bg-[#0D1117] border-b border-gray-200 dark:border-[#30363D] text-sm">
            <span className="text-gray-600 dark:text-gray-400">
              <strong className="text-gray-900 dark:text-[#E6EDF3]">{data.total_results}</strong> results
            </span>
            <span className="text-green-600 dark:text-green-400">
              <strong>{data.approved_count}</strong> approved
            </span>
            <span className="text-red-500 dark:text-red-400">
              <strong>{data.rejected_count}</strong> rejected
            </span>
            <label className="ml-auto flex items-center gap-2 cursor-pointer text-gray-500 dark:text-gray-400">
              <input
                type="checkbox"
                checked={showRejected}
                onChange={e => setShowRejected(e.target.checked)}
                className="rounded"
              />
              Show rejected
            </label>
            <button
              onClick={() => refetch()}
              className="flex items-center gap-1.5 text-[#FF1493] hover:text-[#FF1493]/80"
            >
              <FiSearch size={13} /> Re-search
            </button>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <div className="flex flex-col items-center justify-center py-16 gap-3">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]" />
              <p className="text-sm text-gray-500 dark:text-gray-400">Searching indexers…</p>
            </div>
          )}

          {isError && (
            <div className="text-center py-16 text-red-500 dark:text-red-400">
              Search failed. Check that at least one indexer is configured and enabled.
            </div>
          )}

          {!isLoading && !isError && visible.length === 0 && (
            <div className="text-center py-16 text-gray-500 dark:text-gray-400">
              {data?.total_results === 0
                ? 'No results found on any configured indexer.'
                : 'No approved results. Enable "Show rejected" to see why results were filtered.'}
            </div>
          )}

          {!isLoading && !isError && visible.length > 0 && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-50 dark:bg-[#161B22] border-b border-gray-200 dark:border-[#30363D]">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 w-8"></th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Release</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">Quality</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">Size</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">Age</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Indexer</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Decision</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-[#21262D]">
                {visible.map(decision => (
                  <tr
                    key={decision.guid}
                    className={`hover:bg-gray-50 dark:hover:bg-[#1C2128] ${
                      decision.permanently_rejected ? 'opacity-50' : ''
                    }`}
                  >
                    <td className="px-4 py-3 text-gray-400">
                      {decision.protocol === 'usenet' ? '📡' : '🌊'}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className="text-gray-800 dark:text-[#E6EDF3] font-mono text-xs leading-tight break-all"
                        title={decision.title}
                      >
                        {decision.title.length > 80 ? decision.title.slice(0, 80) + '…' : decision.title}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <QualityBadge quality={decision.quality} format={decision.format} bitrate={decision.bitrate} />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                      {formatBytes(decision.size)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                      {decision.age_days != null ? `${decision.age_days}d` : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-400 whitespace-nowrap">
                      {decision.indexer}
                    </td>
                    <td className="px-4 py-3">
                      <DecisionBadge decision={decision} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => grabMutation.mutate(decision.guid)}
                        disabled={grabbingGuid === decision.guid}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium
                          bg-[#FF1493]/10 text-[#FF1493] hover:bg-[#FF1493]/20
                          disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {grabbingGuid === decision.guid
                          ? <div className="animate-spin rounded-full h-3 w-3 border-b border-[#FF1493]" />
                          : <FiDownload size={12} />
                        }
                        Grab
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
