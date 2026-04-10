import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { albumsApi, authFetch } from '../api/client'
import { FiFilter, FiRefreshCw, FiSearch, FiX, FiDownload } from 'react-icons/fi'
import { S54 } from '../assets/graphics'
import type { AlbumStatus } from '../types'
import Pagination from '../components/Pagination'

interface SearchResult {
  title: string
  size_mb: number
  age_days: number
  indexer: string
  download_url: string
  guid: string
}

const DEFAULT_PER_PAGE = 50

function Albums() {
  const [statusFilter, setStatusFilter] = useState<AlbumStatus | ''>('')
  const [monitoredFilter, setMonitoredFilter] = useState<'all' | 'monitored' | 'unmonitored'>('all')
  const [showSearchModal, setShowSearchModal] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [itemsPerPage, setItemsPerPage] = useState(DEFAULT_PER_PAGE)

  // Fetch albums
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['albums', statusFilter, monitoredFilter, page, itemsPerPage],
    queryFn: () =>
      albumsApi.list({
        status: statusFilter || undefined,
        monitored_only: monitoredFilter === 'monitored' ? true : undefined,
        limit: itemsPerPage,
        offset: (page - 1) * itemsPerPage,
      }),
  })

  const albums = data?.items || []
  const totalCount = data?.total_count || 0
  const totalPages = Math.ceil(totalCount / itemsPerPage)

  const handlePageChange = (newPage: number) => {
    setPage(newPage)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleItemsPerPageChange = (perPage: number) => {
    setItemsPerPage(perPage)
    setPage(1)
  }

  // Reset page when filters change
  const handleStatusFilter = (val: AlbumStatus | '') => {
    setStatusFilter(val)
    setPage(1)
  }
  const handleMonitoredFilter = (val: 'all' | 'monitored' | 'unmonitored') => {
    setMonitoredFilter(val)
    setPage(1)
  }

  const getStatusBadgeClass = (status: AlbumStatus) => {
    switch (status) {
      case 'downloaded':
        return 'badge-success'
      case 'downloading':
        return 'badge-info'
      case 'wanted':
        return 'badge-warning'
      case 'failed':
        return 'badge-danger'
      default:
        return 'badge-info'
    }
  }

  const handleManualSearch = async () => {
    if (!searchQuery.trim()) return

    setSearching(true)
    setSearchError(null)
    setSearchResults([])

    try {
      const response = await authFetch(
        `/api/v1/indexers/search?query=${encodeURIComponent(searchQuery)}`,
        { method: 'POST' }
      )

      if (!response.ok) {
        throw new Error('Search failed')
      }

      const data = await response.json()
      setSearchResults(data.results || [])
    } catch (error: any) {
      setSearchError(error.message || 'Failed to search indexers')
    } finally {
      setSearching(false)
    }
  }

  const handleDownload = (downloadUrl: string) => {
    window.open(downloadUrl, '_blank')
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Albums</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            {totalCount.toLocaleString()} total albums
          </p>
        </div>
        <div className="flex space-x-3">
          <button className="btn btn-secondary" onClick={() => refetch()}>
            <FiRefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </button>
          <button className="btn btn-primary" onClick={() => setShowSearchModal(true)}>
            <FiSearch className="w-4 h-4 mr-2" />
            Manual Search
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="card p-4">
        <div className="flex items-center space-x-6">
          <FiFilter className="w-5 h-5 text-gray-400" />
          <div className="flex items-center space-x-2">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Status:</label>
            <select
              className="input w-48"
              value={statusFilter}
              onChange={(e) => handleStatusFilter(e.target.value as AlbumStatus | '')}
            >
              <option value="">All</option>
              <option value="wanted">Wanted</option>
              <option value="searching">Searching</option>
              <option value="downloading">Downloading</option>
              <option value="downloaded">Downloaded</option>
              <option value="failed">Failed</option>
            </select>
          </div>
          <div className="flex items-center space-x-2">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Monitoring:</label>
            <select
              className="input w-48"
              value={monitoredFilter}
              onChange={(e) => handleMonitoredFilter(e.target.value as 'all' | 'monitored' | 'unmonitored')}
            >
              <option value="all">All</option>
              <option value="monitored">Monitored</option>
              <option value="unmonitored">Unmonitored</option>
            </select>
          </div>
        </div>
      </div>

      {/* Albums List */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
        </div>
      ) : albums.length > 0 ? (
        <>
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="table">
                <thead className="table-header">
                  <tr>
                    <th className="table-cell font-medium text-gray-900 dark:text-white">Album</th>
                    <th className="table-cell font-medium text-gray-900 dark:text-white">Artist</th>
                    <th className="table-cell font-medium text-gray-900 dark:text-white">Year</th>
                    <th className="table-cell font-medium text-gray-900 dark:text-white">Tracks</th>
                    <th className="table-cell font-medium text-gray-900 dark:text-white">Status</th>
                    <th className="table-cell font-medium text-gray-900 dark:text-white">Type</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
                  {albums.map((album) => (
                    <tr key={album.id} className="hover:bg-gray-50 dark:hover:bg-[#1C2128]">
                      <td className="table-cell">
                        <div className="flex items-center">
                          <img
                            src={album.cover_art_url || S54.defaultAlbumArt}
                            alt={album.title}
                            className="w-10 h-10 rounded mr-3 object-cover"
                          />
                          <div>
                            <p className="font-medium text-gray-900 dark:text-white">{album.title}</p>
                            {album.muse_verified && (
                              <span className="text-xs text-green-600 dark:text-green-400">In MUSE</span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="table-cell text-gray-700 dark:text-gray-300">{album.artist_name}</td>
                      <td className="table-cell text-gray-700 dark:text-gray-300">
                        {album.release_date ? new Date(album.release_date).getFullYear() : '-'}
                      </td>
                      <td className="table-cell text-gray-700 dark:text-gray-300">{album.track_count || '-'}</td>
                      <td className="table-cell">
                        <span className={`badge ${getStatusBadgeClass(album.status)}`}>{album.status}</span>
                      </td>
                      <td className="table-cell text-gray-700 dark:text-gray-300">{album.album_type || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <Pagination
            page={page}
            totalPages={totalPages}
            totalCount={totalCount}
            itemsPerPage={itemsPerPage}
            onPageChange={handlePageChange}
            onItemsPerPageChange={handleItemsPerPageChange}
          />
        </>
      ) : (
        <div className="card p-12 text-center">
          <p className="text-gray-500 dark:text-gray-400">No albums found.</p>
        </div>
      )}

      {/* Manual Search Modal */}
      {showSearchModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
            {/* Modal Header */}
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Manual Album Search</h2>
              <button
                onClick={() => setShowSearchModal(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              >
                <FiX className="w-6 h-6" />
              </button>
            </div>

            {/* Search Input */}
            <div className="p-6 border-b border-gray-200 dark:border-[#30363D]">
              <div className="flex space-x-3">
                <input
                  type="text"
                  placeholder="Search for albums, artists, or releases..."
                  className="input flex-1"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && handleManualSearch()}
                />
                <button
                  className="btn btn-primary"
                  onClick={handleManualSearch}
                  disabled={searching || !searchQuery.trim()}
                >
                  {searching ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                      Searching...
                    </>
                  ) : (
                    <>
                      <FiSearch className="w-4 h-4 mr-2" />
                      Search
                    </>
                  )}
                </button>
              </div>
              {searchError && (
                <p className="mt-2 text-sm text-red-600 dark:text-red-400">{searchError}</p>
              )}
            </div>

            {/* Search Results */}
            <div className="p-6 overflow-y-auto" style={{ maxHeight: 'calc(90vh - 250px)' }}>
              {searchResults.length > 0 ? (
                <div className="space-y-3">
                  {searchResults.map((result, index) => (
                    <div
                      key={index}
                      className="card p-4 flex items-center justify-between hover:shadow-md transition-shadow"
                    >
                      <div className="flex-1">
                        <h3 className="font-medium text-gray-900 dark:text-white">{result.title}</h3>
                        <div className="mt-1 flex items-center space-x-4 text-sm text-gray-600 dark:text-gray-400">
                          <span>Size: {result.size_mb.toFixed(2)} MB</span>
                          <span>Age: {result.age_days} days</span>
                          <span className="badge badge-info">{result.indexer}</span>
                        </div>
                      </div>
                      <button
                        className="btn btn-sm btn-primary ml-4"
                        onClick={() => handleDownload(result.download_url)}
                      >
                        <FiDownload className="w-4 h-4 mr-2" />
                        Download
                      </button>
                    </div>
                  ))}
                </div>
              ) : searching ? (
                <div className="text-center py-12">
                  <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493] mx-auto"></div>
                  <p className="mt-4 text-gray-600 dark:text-gray-400">Searching indexers...</p>
                </div>
              ) : (
                <div className="text-center py-12">
                  <FiSearch className="w-16 h-16 text-gray-400 mx-auto mb-4" />
                  <p className="text-gray-600 dark:text-gray-400">
                    Enter a search query and click Search to find albums from your configured indexers.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Albums
