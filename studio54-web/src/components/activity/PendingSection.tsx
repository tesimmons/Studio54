import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FiRefreshCw, FiTrash2, FiClock } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { searchApi } from '../../api/client'

export default function PendingSection() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['pending-releases'] })

  const { data, isLoading, isError } = useQuery({
    queryKey: ['pending-releases'],
    queryFn: () => searchApi.getPending(),
    refetchInterval: 30000,
  })

  const retryMutation = useMutation({
    mutationFn: (id: string) => searchApi.retryPending(id),
    onSuccess: () => { toast.success('Queued for retry'); invalidate() },
    onError: () => toast.error('Failed to retry'),
  })

  const removeMutation = useMutation({
    mutationFn: (id: string) => searchApi.removePending(id),
    onSuccess: () => { toast.success('Removed'); invalidate() },
    onError: () => toast.error('Failed to remove'),
  })

  const items = data?.items ?? []

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <FiClock size={16} className="text-yellow-500" />
        <h3 className="text-sm font-semibold text-gray-700 dark:text-[#E6EDF3]">
          Pending Releases
        </h3>
        {data && (
          <span className="text-xs text-gray-500 dark:text-gray-400">({data.count})</span>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-6">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-[#FF1493]" />
        </div>
      )}

      {isError && (
        <p className="text-sm text-red-500 dark:text-red-400 py-3">Failed to load pending releases</p>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400 py-3">No pending releases</p>
      )}

      {items.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#161B22]/50">
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Release</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Album</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Reason</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Retries</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Retry After</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
              {items.map(item => (
                <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                  <td className="px-4 py-3">
                    <span className="text-xs font-mono text-gray-800 dark:text-[#E6EDF3] truncate block max-w-xs" title={item.release_title}>
                      {item.release_title.length > 60 ? item.release_title.slice(0, 60) + '…' : item.release_title}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {item.album_id && item.album_title ? (
                      <Link to={`/disco-lounge/albums/${item.album_id}`} className="text-[#FF1493] hover:underline">
                        {item.album_title}
                      </Link>
                    ) : (
                      <span className="text-gray-500 dark:text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="space-y-0.5">
                      {item.rejection_reasons.slice(0, 2).map((r, i) => (
                        <span key={i} className="block text-xs text-yellow-600 dark:text-yellow-400">{r}</span>
                      ))}
                      {item.rejection_reasons.length > 2 && (
                        <span className="text-xs text-gray-500">+{item.rejection_reasons.length - 2} more</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                    {item.retry_count}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                    {item.retry_after
                      ? new Date(item.retry_after).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => retryMutation.mutate(item.id)}
                        disabled={retryMutation.isPending}
                        title="Retry now"
                        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-blue-500 transition-colors"
                      >
                        <FiRefreshCw size={13} />
                      </button>
                      <button
                        onClick={() => removeMutation.mutate(item.id)}
                        disabled={removeMutation.isPending}
                        title="Remove"
                        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-red-500 transition-colors"
                      >
                        <FiTrash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
