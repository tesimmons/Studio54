import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FiTrash2, FiSlash } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { queueApi } from '../../api/client'

const PAGE_SIZE = 50

export default function BlacklistSection() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['blacklist', page],
    queryFn: () => queueApi.getBlacklist({ limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
  })

  const removeMutation = useMutation({
    mutationFn: (id: string) => queueApi.removeFromBlacklist(id),
    onSuccess: () => {
      toast.success('Removed from blacklist')
      queryClient.invalidateQueries({ queryKey: ['blacklist'] })
    },
    onError: () => toast.error('Failed to remove from blacklist'),
  })

  const items = data?.items ?? []
  const totalPages = data ? Math.ceil(data.count / PAGE_SIZE) : 0

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <FiSlash size={16} className="text-red-500" />
        <h3 className="text-sm font-semibold text-gray-700 dark:text-[#E6EDF3]">
          Blacklisted Releases
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
        <p className="text-sm text-red-500 dark:text-red-400 py-3">Failed to load blacklist</p>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400 py-3">Blacklist is empty</p>
      )}

      {items.length > 0 && (
        <>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#161B22]/50">
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Release</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Album / Artist</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Reason</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">Date Added</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
                {items.map(item => (
                  <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                    <td className="px-4 py-3">
                      <span
                        className="text-xs font-mono text-gray-800 dark:text-[#E6EDF3] block truncate max-w-xs"
                        title={item.release_title}
                      >
                        {item.release_title}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs space-y-0.5">
                      {item.album_id && item.album_title && (
                        <Link to={`/disco-lounge/albums/${item.album_id}`} className="text-[#FF1493] hover:underline block">
                          {item.album_title}
                        </Link>
                      )}
                      {item.artist_name && (
                        <span className="text-gray-500 dark:text-gray-400 block">{item.artist_name}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 max-w-xs">
                      {item.reason || '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                      {item.added_at
                        ? new Date(item.added_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => {
                          if (confirm(`Remove "${item.release_title}" from blacklist?`)) {
                            removeMutation.mutate(item.id)
                          }
                        }}
                        disabled={removeMutation.isPending}
                        title="Remove from blacklist"
                        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-red-500 transition-colors"
                      >
                        <FiTrash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
              <span>Page {page + 1} of {totalPages}</span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(p => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="px-3 py-1 rounded border border-gray-200 dark:border-[#30363D] disabled:opacity-40 hover:bg-gray-100 dark:hover:bg-[#21262D]"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="px-3 py-1 rounded border border-gray-200 dark:border-[#30363D] disabled:opacity-40 hover:bg-gray-100 dark:hover:bg-[#21262D]"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
