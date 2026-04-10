import { useState, useEffect } from 'react'
import { useSearchParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { FiDownload, FiChevronLeft, FiChevronRight } from 'react-icons/fi'
import { downloadHistoryApi } from '../api/client'

const STATUS_BADGES: Record<string, { label: string; className: string }> = {
  GRABBED: { label: 'Grabbed', className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  IMPORTED: { label: 'Imported', className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
  DOWNLOAD_FAILED: { label: 'Download Failed', className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
  IMPORT_FAILED: { label: 'Import Failed', className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
  DELETED: { label: 'Deleted', className: 'bg-gray-100 text-gray-700 dark:bg-[#0D1117] dark:text-gray-300' },
  BLACKLISTED: { label: 'Blacklisted', className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' },
}

const PAGE_SIZE = 50

function DownloadHistory() {
  const [searchParams, setSearchParams] = useSearchParams()

  const [statusFilter, setStatusFilter] = useState(searchParams.get('status_filter') || '')
  const [dateFrom, setDateFrom] = useState(searchParams.get('date_from') || '')
  const [dateTo, setDateTo] = useState(searchParams.get('date_to') || '')
  const [page, setPage] = useState(0)

  // Sync URL params on mount
  useEffect(() => {
    const sf = searchParams.get('status_filter')
    const df = searchParams.get('date_from')
    const dt = searchParams.get('date_to')
    if (sf) setStatusFilter(sf)
    if (df) setDateFrom(df)
    if (dt) setDateTo(dt)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['download-history', statusFilter, dateFrom, dateTo, page],
    queryFn: () =>
      downloadHistoryApi.getHistory({
        status_filter: statusFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    refetchInterval: 30000,
  })

  const handleFilterChange = (newStatus: string, newFrom: string, newTo: string) => {
    setStatusFilter(newStatus)
    setDateFrom(newFrom)
    setDateTo(newTo)
    setPage(0)
    const params: Record<string, string> = {}
    if (newStatus) params.status_filter = newStatus
    if (newFrom) params.date_from = newFrom
    if (newTo) params.date_to = newTo
    setSearchParams(params)
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <FiDownload className="w-6 h-6 md:w-8 md:h-8" />
          Download History
        </h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">
          Complete history of all download events with artist/album links
        </p>
      </div>

      {/* Filters */}
      <div className="card p-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Status</label>
            <select
              value={statusFilter}
              onChange={(e) => handleFilterChange(e.target.value, dateFrom, dateTo)}
              className="input text-sm py-1.5"
            >
              <option value="">All</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">From</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => handleFilterChange(statusFilter, e.target.value, dateTo)}
              className="input text-sm py-1.5"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">To</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => handleFilterChange(statusFilter, dateFrom, e.target.value)}
              className="input text-sm py-1.5"
            />
          </div>
          {(statusFilter || dateFrom || dateTo) && (
            <div className="flex flex-col justify-end">
              <label className="block text-xs mb-1">&nbsp;</label>
              <button
                onClick={() => handleFilterChange('', '', '')}
                className="text-sm text-[#FF1493] dark:text-[#ff4da6] hover:underline whitespace-nowrap"
              >
                Clear filters
              </button>
            </div>
          )}
          {data && (
            <div className="flex flex-col justify-end ml-auto">
              <label className="block text-xs mb-1">&nbsp;</label>
              <span className="text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
                {data.total.toLocaleString()} result{data.total !== 1 ? 's' : ''}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]" />
          </div>
        ) : isError ? (
          <div className="text-center py-12 text-red-500 dark:text-red-400">
            Failed to load download history{error instanceof Error ? `: ${error.message}` : ''}
          </div>
        ) : !data || data.items.length === 0 ? (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            No download history found
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#161B22]/50">
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Date</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Artist</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Album</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Release</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Quality</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Source</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Status</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
                {data.items.map((item) => {
                  const badge = STATUS_BADGES[item.event_type] || {
                    label: item.event_type,
                    className: 'bg-gray-100 text-gray-700 dark:bg-[#0D1117] dark:text-gray-300',
                  }
                  const isFailed = item.event_type === 'DOWNLOAD_FAILED' || item.event_type === 'IMPORT_FAILED'
                  return (
                    <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                      <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                        {item.occurred_at
                          ? new Date(item.occurred_at).toLocaleDateString(undefined, {
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit',
                            })
                          : '—'}
                      </td>
                      <td className="px-4 py-3">
                        {item.artist_id && item.artist_name ? (
                          <Link
                            to={`/disco-lounge/artists/${item.artist_id}`}
                            className="text-[#FF1493] dark:text-[#ff4da6] hover:underline"
                          >
                            {item.artist_name}
                          </Link>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {item.album_id && item.album_title ? (
                          <Link
                            to={`/disco-lounge/albums/${item.album_id}`}
                            className="text-[#FF1493] dark:text-[#ff4da6] hover:underline"
                          >
                            {item.album_title}
                          </Link>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 max-w-[200px] truncate text-gray-700 dark:text-gray-300" title={item.release_title || ''}>
                        {item.release_title || '—'}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{item.quality || '—'}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{item.source || '—'}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${badge.className}`}>
                          {badge.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 max-w-[250px]">
                        {item.message ? (
                          <span
                            className={`text-xs truncate block ${isFailed ? 'text-red-600 dark:text-red-400' : 'text-gray-600 dark:text-gray-400'}`}
                            title={item.message}
                          >
                            {item.message}
                          </span>
                        ) : item.download_path ? (
                          <span className="text-xs text-gray-500 dark:text-gray-400 truncate block" title={item.download_path}>
                            {item.download_path}
                          </span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-[#30363D]">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <FiChevronLeft className="w-4 h-4" /> Previous
            </button>
            <span className="text-sm text-gray-600 dark:text-gray-400">
              Page {page + 1} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next <FiChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default DownloadHistory
