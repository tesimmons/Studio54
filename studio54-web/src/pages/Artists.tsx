import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { artistsApi, rootFoldersApi, qualityProfilesApi, searchApi, authFetch } from '../api/client'
import { FiSearch, FiPlus, FiRefreshCw, FiX, FiTrash2, FiMusic, FiDownload, FiCheck, FiGrid, FiList, FiDatabase, FiAlertCircle, FiLoader } from 'react-icons/fi'
import ImportArtistsModal from '../components/ImportArtistsModal'
import Pagination from '../components/Pagination'
import type { Artist, RootFolder, QualityProfile } from '../types'

interface MusicBrainzArtist {
  id: string
  name: string
  disambiguation?: string
  country?: string
  type?: string
  score?: number
}

type FilterMode = 'all' | 'monitored' | 'unmonitored'
type ViewMode = 'grid' | 'list'
type SortBy = 'name' | 'files_desc' | 'files_asc' | 'added_at'

// Helper to get file linking bar colors and text
function getFileLinkingStatus(linked: number, total: number) {
  const percentage = total > 0 ? Math.round((linked / total) * 100) : 0

  if (total === 0) {
    return { barColor: '#9CA3AF', textColor: '#6B7280', statusText: 'No Tracks', percentage }
  }
  if (percentage === 0) {
    return { barColor: '#EF4444', textColor: '#DC2626', statusText: 'No Files', percentage }
  }
  if (percentage === 100) {
    return { barColor: '#22C55E', textColor: '#16A34A', statusText: 'Complete', percentage }
  }
  return { barColor: '#F59E0B', textColor: '#D97706', statusText: `${percentage}%`, percentage }
}

function Artists() {
  const [searchQuery, setSearchQuery] = useState('')
  const [filterMode, setFilterMode] = useState<FilterMode>('all')
  const [genreFilter, setGenreFilter] = useState('')
  const [sortBy, setSortBy] = useState<SortBy>('name')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [page, setPage] = useState(1)
  const [itemsPerPage, setItemsPerPage] = useState(50)
  const [showAddModal, setShowAddModal] = useState(false)
  const [showImportModal, setShowImportModal] = useState(false)
  const [bulkMode, setBulkMode] = useState(false)
  const [selectedArtistIds, setSelectedArtistIds] = useState<Set<string>>(new Set())
  const [mbSearchQuery, setMbSearchQuery] = useState('')
  const [mbResults, setMbResults] = useState<MusicBrainzArtist[]>([])
  const [mbSearching, setMbSearching] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [deleteDialogArtist, setDeleteDialogArtist] = useState<{ id: string; name: string; linkedFiles: number } | null>(null)
  const [deleteDialogFiles, setDeleteDialogFiles] = useState(false)
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false)
  const [bulkDeleteFiles, setBulkDeleteFiles] = useState(false)

  // Resolve MBIDs modal state
  const [showResolveModal, setShowResolveModal] = useState(false)
  const [resolveLoading, setResolveLoading] = useState(false)
  const [resolveResults, setResolveResults] = useState<{
    resolved: Array<{ id: string; name: string; mbid: string; score: number; matched_name: string }>
    unresolved: Array<{ id: string; name: string; top_match: { name: string; mbid: string; score: number } | null }>
    stats: { total: number; resolved: number; unresolved: number }
  } | null>(null)
  const [remoteResolveTaskId, setRemoteResolveTaskId] = useState<string | null>(null)
  const [remoteResolveLoading, setRemoteResolveLoading] = useState(false)

  // Two-step Add Artist modal state
  const [selectedMbArtist, setSelectedMbArtist] = useState<MusicBrainzArtist | null>(null)
  const [addRootFolder, setAddRootFolder] = useState('')
  const [addQualityProfile, setAddQualityProfile] = useState('')
  const [addMonitorType, setAddMonitorType] = useState('all_albums')
  const [addSearchForMissing, setAddSearchForMissing] = useState(true)

  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Fetch root folders for Add Artist modal
  const { data: rootFolders } = useQuery<RootFolder[]>({
    queryKey: ['rootFolders'],
    queryFn: () => rootFoldersApi.list(),
    enabled: showAddModal,
  })

  // Fetch quality profiles for Add Artist modal
  const { data: qualityProfiles } = useQuery<QualityProfile[]>({
    queryKey: ['qualityProfiles'],
    queryFn: () => qualityProfilesApi.list(),
    enabled: showAddModal,
  })

  // Fetch genre list for filter dropdown
  const { data: genresData } = useQuery({
    queryKey: ['artist-genres'],
    queryFn: async () => {
      const response = await authFetch('/api/v1/artists/genres')
      if (!response.ok) throw new Error('Failed to fetch genres')
      return response.json()
    },
  })

  // Fetch artists with filters
  const { data: artistsData, isLoading, refetch } = useQuery({
    queryKey: ['artists', filterMode, sortBy, searchQuery, genreFilter, page, itemsPerPage],
    queryFn: async () => {
      const params: Record<string, string> = {
        monitored_only: filterMode === 'monitored' ? 'true' : 'false',
        unmonitored_only: filterMode === 'unmonitored' ? 'true' : 'false',
        search_query: searchQuery,
        limit: String(itemsPerPage),
        offset: String((page - 1) * itemsPerPage),
      }
      if (sortBy !== 'name') params.sort_by = sortBy
      if (genreFilter) params.genre = genreFilter
      const response = await authFetch(`/api/v1/artists?${new URLSearchParams(params)}`)
      if (!response.ok) throw new Error('Failed to fetch artists')
      return response.json()
    },
  })

  const artists = artistsData?.artists || []
  const totalCount = artistsData?.total_count || artistsData?.total || 0
  const totalPages = Math.ceil(totalCount / itemsPerPage)

  // Reset page when filters change
  const handleFilterChange = (newFilter: FilterMode) => {
    setFilterMode(newFilter)
    setPage(1)
  }

  const handleSearchChange = (query: string) => {
    setSearchQuery(query)
    setPage(1)
  }

  const handleItemsPerPageChange = (newItemsPerPage: number) => {
    setItemsPerPage(newItemsPerPage)
    setPage(1)
  }

  // Search MusicBrainz
  const searchMusicBrainz = async () => {
    if (!mbSearchQuery.trim()) return

    setMbSearching(true)
    try {
      const response = await authFetch(`/api/v1/musicbrainz/search/artists?query=${encodeURIComponent(mbSearchQuery)}`)
      const data = await response.json()
      setMbResults(data.artists || [])
    } catch (error) {
      console.error('MusicBrainz search failed:', error)
      setMbResults([])
    } finally {
      setMbSearching(false)
    }
  }

  // Add artist mutation (two-step: select from MB, then configure)
  const addArtistMutation = useMutation({
    mutationFn: async (mbid: string) => {
      return artistsApi.add({
        musicbrainz_id: mbid,
        monitored: true,
        root_folder_path: addRootFolder || undefined,
        quality_profile_id: addQualityProfile || undefined,
        monitor_type: addMonitorType,
        search_for_missing: addSearchForMissing,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      setShowAddModal(false)
      setMbSearchQuery('')
      setMbResults([])
      setSelectedMbArtist(null)
      setAddRootFolder('')
      setAddQualityProfile('')
      setAddMonitorType('all_albums')
      setAddSearchForMissing(true)
    }
  })

  // Search missing albums mutation
  const searchMissingMutation = useMutation({
    mutationFn: async () => {
      return searchApi.searchMissing()
    },
    onSuccess: (data) => {
      alert(`${data.message}. Check Activity page to monitor progress.`)
    },
    onError: (error: Error) => {
      alert(`Failed to start search: ${error.message}`)
    }
  })

  // Bulk update mutation
  const bulkUpdateMutation = useMutation({
    mutationFn: async (isMonitored: boolean) => {
      return artistsApi.bulkUpdate(Array.from(selectedArtistIds), { is_monitored: isMonitored })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      setSelectedArtistIds(new Set())
      setBulkMode(false)
    },
  })

  // Bulk delete mutation
  const bulkDeleteMutation = useMutation({
    mutationFn: async ({ artistIds, deleteFiles }: { artistIds: string[]; deleteFiles: boolean }) => {
      const deletePromises = artistIds.map(id =>
        authFetch(`/api/v1/artists/${id}?delete_files=${deleteFiles}`, { method: 'DELETE' })
          .then(async res => {
            if (!res.ok) {
              const error = await res.json().catch(() => ({ detail: 'Unknown error' }))
              throw new Error(error.detail || `Failed to delete artist ${id}`)
            }
            return res.json()
          })
      )
      return Promise.all(deletePromises)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      setSelectedArtistIds(new Set())
      setBulkMode(false)
      setBulkDeleteDialogOpen(false)
      setBulkDeleteFiles(false)
    },
    onError: (error: Error) => {
      alert(`Error deleting artists: ${error.message}`)
    }
  })

  // Delete artist mutation
  const deleteArtistMutation = useMutation({
    mutationFn: async ({ artistId, deleteFiles }: { artistId: string; deleteFiles: boolean }) => {
      const response = await authFetch(`/api/v1/artists/${artistId}?delete_files=${deleteFiles}`, {
        method: 'DELETE'
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Failed to delete artist' }))
        throw new Error(error.detail || 'Failed to delete artist')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      setDeletingId(null)
      setDeleteDialogArtist(null)
      setDeleteDialogFiles(false)
    },
    onError: (error: Error) => {
      alert(`Error deleting artist: ${error.message}`)
      setDeletingId(null)
    }
  })

  // Refresh all metadata mutation
  const refreshAllMetadataMutation = useMutation({
    mutationFn: async () => {
      return artistsApi.refreshAllMetadata()
    },
    onSuccess: (data) => {
      alert(`Queued metadata refresh for ${data.total_artists} artists. Check Activity page to monitor progress.`)
    },
    onError: (error: Error) => {
      alert(`Failed to queue metadata refresh: ${error.message}`)
    }
  })

  const handleDeleteArtist = (e: React.MouseEvent, artist: Artist) => {
    e.stopPropagation()
    setDeleteDialogFiles(false)
    setDeleteDialogArtist({
      id: artist.id,
      name: artist.name,
      linkedFiles: artist.linked_files_count || 0
    })
  }

  const toggleArtistSelection = (artistId: string) => {
    const newSelected = new Set(selectedArtistIds)
    if (newSelected.has(artistId)) {
      newSelected.delete(artistId)
    } else {
      newSelected.add(artistId)
    }
    setSelectedArtistIds(newSelected)
  }

  const handleSelectAll = () => {
    if (selectedArtistIds.size === artists.length) {
      setSelectedArtistIds(new Set())
    } else {
      setSelectedArtistIds(new Set(artists.map((a: Artist) => a.id)))
    }
  }

  const handleBulkMonitor = () => {
    bulkUpdateMutation.mutate(true)
  }

  const handleBulkUnmonitor = () => {
    bulkUpdateMutation.mutate(false)
  }

  const handleBulkDelete = () => {
    const count = selectedArtistIds.size
    if (count === 0) {
      alert('No artists selected')
      return
    }
    setBulkDeleteFiles(false)
    setBulkDeleteDialogOpen(true)
  }

  // Bulk resolve MBIDs via local DB
  const handleBulkResolveMbid = async () => {
    setResolveLoading(true)
    setResolveResults(null)
    setRemoteResolveTaskId(null)
    setShowResolveModal(true)
    try {
      const result = await artistsApi.bulkResolveMbid()
      setResolveResults(result)
      if (result.stats.resolved > 0) {
        queryClient.invalidateQueries({ queryKey: ['artists'] })
      }
    } catch (error: any) {
      alert(`Bulk MBID resolution failed: ${error?.response?.data?.detail || error.message}`)
      setShowResolveModal(false)
    } finally {
      setResolveLoading(false)
    }
  }

  // Start remote resolution for unresolved artists
  const handleRemoteResolve = async () => {
    if (!resolveResults?.unresolved?.length) return
    setRemoteResolveLoading(true)
    try {
      const unresolvedIds = resolveResults.unresolved.map(a => a.id)
      const result = await artistsApi.bulkResolveMbidRemote(unresolvedIds)
      setRemoteResolveTaskId(result.task_id)
      alert(`Remote resolution started for ${result.artist_count} artists. Check Activity page for progress.`)
    } catch (error: any) {
      alert(`Failed to start remote resolution: ${error?.response?.data?.detail || error.message}`)
    } finally {
      setRemoteResolveLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">
            Artists {totalCount > 0 && <span className="text-gray-500 dark:text-gray-400">({totalCount.toLocaleString()})</span>}
          </h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Manage your music artists
            {totalCount > 0 && ` • Showing ${((page - 1) * itemsPerPage) + 1}-${Math.min(page * itemsPerPage, totalCount)} of ${totalCount.toLocaleString()}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {/* View Toggle */}
          <div className="flex border border-gray-300 dark:border-[#30363D] rounded-lg overflow-hidden">
            <button
              className={`px-3 py-2 transition-colors ${
                viewMode === 'grid'
                  ? 'bg-[#FF1493] text-white'
                  : 'bg-white dark:bg-[#161B22] text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-[#1C2128]'
              }`}
              onClick={() => setViewMode('grid')}
              title="Grid View"
            >
              <FiGrid className="w-5 h-5" />
            </button>
            <button
              className={`px-3 py-2 transition-colors ${
                viewMode === 'list'
                  ? 'bg-[#FF1493] text-white'
                  : 'bg-white dark:bg-[#161B22] text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-[#1C2128]'
              }`}
              onClick={() => setViewMode('list')}
              title="List View"
            >
              <FiList className="w-5 h-5" />
            </button>
          </div>
          <button className="btn btn-secondary" onClick={() => refetch()} title="Refresh artist list">
            <FiRefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </button>
          <button className="btn btn-secondary" onClick={() => setShowImportModal(true)} title="Import artists from MUSE or file">
            <FiDownload className="w-4 h-4 mr-2" />
            Import Artists
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => {
              if (confirm(`Queue metadata refresh for all ${totalCount} artists? This will fetch missing images.`)) {
                refreshAllMetadataMutation.mutate()
              }
            }}
            disabled={refreshAllMetadataMutation.isPending}
            title="Fetch missing images and metadata for all artists"
          >
            <FiRefreshCw className="w-4 h-4 mr-2" />
            {refreshAllMetadataMutation.isPending ? 'Queueing...' : 'Refresh All Metadata'}
          </button>
          <button
            className="btn btn-secondary"
            onClick={handleBulkResolveMbid}
            disabled={resolveLoading}
            title="Resolve missing MusicBrainz IDs using local database"
          >
            <FiDatabase className="w-4 h-4 mr-2" />
            {resolveLoading ? 'Resolving...' : 'Resolve MBIDs'}
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => {
              if (confirm('Search for missing albums across all monitored artists?')) {
                searchMissingMutation.mutate()
              }
            }}
            disabled={searchMissingMutation.isPending}
            title="Search Usenet for all missing monitored albums"
          >
            <FiSearch className="w-4 h-4 mr-2" />
            {searchMissingMutation.isPending ? 'Starting...' : 'Search Missing'}
          </button>
          <button className="btn btn-primary" onClick={() => setShowAddModal(true)} title="Add a new artist from MusicBrainz">
            <FiPlus className="w-4 h-4 mr-2" />
            Add Artist
          </button>
        </div>
      </div>

      {/* Filters and Search */}
      <div className="card p-4 space-y-4">
        {/* Filter Toggles */}
        <div className="flex items-center space-x-2">
          <button
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              filterMode === 'all'
                ? 'bg-[#FF1493] text-white'
                : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
            }`}
            onClick={() => handleFilterChange('all')}
            title="Show all artists"
          >
            All
          </button>
          <button
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              filterMode === 'monitored'
                ? 'bg-[#FF1493] text-white'
                : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
            }`}
            onClick={() => handleFilterChange('monitored')}
            title="Show only monitored artists"
          >
            Monitored
          </button>
          <button
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              filterMode === 'unmonitored'
                ? 'bg-[#FF1493] text-white'
                : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
            }`}
            onClick={() => handleFilterChange('unmonitored')}
            title="Show only unmonitored artists"
          >
            Unmonitored
          </button>

          {/* Sort Dropdown */}
          <select
            value={sortBy}
            onChange={(e) => { setSortBy(e.target.value as SortBy); setPage(1) }}
            className="px-3 py-2 rounded-lg border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#161B22] text-gray-700 dark:text-gray-300 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
            title="Sort artists"
          >
            <option value="name">Sort: Name</option>
            <option value="files_desc">Sort: Most Files</option>
            <option value="files_asc">Sort: Least Files</option>
            <option value="added_at">Sort: Recently Added</option>
          </select>

          {/* Genre Filter */}
          {genresData?.genres?.length > 0 && (
            <select
              value={genreFilter}
              onChange={(e) => { setGenreFilter(e.target.value); setPage(1) }}
              className="px-3 py-2 rounded-lg border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#161B22] text-gray-700 dark:text-gray-300 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
              title="Filter by genre"
            >
              <option value="">All Genres</option>
              {genresData.genres.map((g: string) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          )}

          <div className="flex-1"></div>

          {/* Bulk Selection Toggle */}
          <button
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              bulkMode
                ? 'bg-orange-600 text-white hover:bg-orange-700'
                : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
            }`}
            onClick={() => {
              setBulkMode(!bulkMode)
              if (bulkMode) setSelectedArtistIds(new Set())
            }}
            title={bulkMode ? 'Exit selection mode' : 'Enable bulk selection to monitor/unmonitor/delete multiple artists'}
          >
            <FiCheck className={`w-4 h-4 mr-2 inline ${bulkMode ? '' : 'opacity-0'}`} />
            {bulkMode ? 'Cancel Selection' : 'Select Mode'}
          </button>
        </div>

        {/* Hint text for bulk mode */}
        {!bulkMode && artists.length > 0 && (
          <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 -mt-2">
            <span className="mr-2">💡</span>
            <span>Click "Select Mode" to enable bulk operations (monitor/unmonitor multiple artists at once)</span>
          </div>
        )}

        {/* Search */}
        <div className="flex items-center">
          <FiSearch className="w-5 h-5 text-gray-400 mr-3" />
          <input
            type="text"
            placeholder="Search artists..."
            className="input flex-1"
            value={searchQuery}
            onChange={(e) => handleSearchChange(e.target.value)}
          />
        </div>
      </div>

      {/* Bulk Actions Bar */}
      {bulkMode && selectedArtistIds.size > 0 && (
        <div className="card p-4 bg-[#FF1493]/5 dark:bg-[#FF1493]/10 border-2 border-[#FF1493]">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-gray-900 dark:text-white">
              {selectedArtistIds.size} artist{selectedArtistIds.size !== 1 ? 's' : ''} selected
            </span>
            <div className="flex space-x-3">
              <button className="btn btn-secondary btn-sm" onClick={handleSelectAll} title={selectedArtistIds.size === artists.length ? 'Deselect all artists' : 'Select all artists on this page'}>
                {selectedArtistIds.size === artists.length ? 'Deselect All' : 'Select All'}
              </button>
              <button className="btn btn-success btn-sm" onClick={handleBulkMonitor} title="Monitor all selected artists">
                <FiCheck className="w-4 h-4 mr-2" />
                Monitor Selected
              </button>
              <button className="btn btn-secondary btn-sm" onClick={handleBulkUnmonitor} title="Unmonitor all selected artists">
                Unmonitor Selected
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={handleBulkDelete}
                disabled={bulkDeleteMutation.isPending}
                title="Delete all selected artists and their albums"
              >
                {bulkDeleteMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Deleting...
                  </>
                ) : (
                  <>
                    <FiTrash2 className="w-4 h-4 mr-2" />
                    Delete Selected
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Artists Grid/List */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
        </div>
      ) : artists && artists.length > 0 ? (
        <>
          {viewMode === 'grid' ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
              {artists.map((artist: Artist) => (
            <div
              key={artist.id}
              className={`card p-0 hover:shadow-lg transition-shadow group ${
                bulkMode ? 'cursor-pointer' : ''
              } ${
                selectedArtistIds.has(artist.id)
                  ? 'ring-4 ring-[#FF1493]'
                  : ''
              }`}
              onClick={() => {
                if (bulkMode) {
                  toggleArtistSelection(artist.id)
                } else {
                  navigate(`/artists/${artist.id}`)
                }
              }}
            >
              {/* Artist Image */}
              <div className="relative bg-gradient-to-br from-[#FF1493] to-[#FF8C00] aspect-square flex items-center justify-center overflow-hidden">
                {artist.image_url ? (
                  <img
                    src={artist.image_url?.startsWith('http') ? artist.image_url : `/api/v1/${artist.id}/cover-art`}
                    alt={artist.name}
                    loading="lazy"
                    className="w-full h-full object-cover"
                    onError={(e) => {
                      e.currentTarget.style.display = 'none'
                    }}
                  />
                ) : (
                  <FiMusic className="w-24 h-24 text-white/30" />
                )}

                {/* Checkboxes for bulk mode */}
                {bulkMode && (
                  <div className="absolute top-2 left-2">
                    <div className={`w-6 h-6 rounded border-2 flex items-center justify-center ${
                      selectedArtistIds.has(artist.id)
                        ? 'bg-[#FF1493] border-[#FF1493]'
                        : 'bg-white border-gray-300'
                    }`}>
                      {selectedArtistIds.has(artist.id) && (
                        <FiCheck className="w-4 h-4 text-white" />
                      )}
                    </div>
                  </div>
                )}

                {/* Monitored badge */}
                {artist.is_monitored && (
                  <div className="absolute top-2 right-2">
                    <span className="badge badge-success">Monitored</span>
                  </div>
                )}

                {/* Import source badge */}
                {artist.import_source && (
                  <div className="absolute bottom-2 right-2">
                    <span className="badge badge-info text-xs capitalize">
                      {artist.import_source}
                    </span>
                  </div>
                )}
              </div>

              {/* Artist Info */}
              <div className="p-4">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white truncate group-hover:text-[#FF1493] transition-colors">
                  {artist.name}
                </h3>
                <div className="mt-3 space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-600 dark:text-gray-400">Albums</span>
                    <span className="font-medium text-gray-900 dark:text-white">{artist.album_count || 0}</span>
                  </div>
                  {artist.track_count !== undefined && (
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-600 dark:text-gray-400">Tracks</span>
                      <span className="font-medium text-gray-900 dark:text-white">{artist.track_count || 0}</span>
                    </div>
                  )}
                </div>

                {/* File Linking Status Bar */}
                {(() => {
                  const linked = artist.linked_files_count || 0
                  const total = artist.total_track_files || artist.track_count || 0
                  const status = getFileLinkingStatus(linked, total)
                  return (
                    <div className="mt-3 pt-3 border-t border-gray-200 dark:border-[#30363D]">
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="font-medium" style={{ color: status.textColor }}>{status.statusText}</span>
                        <span className="text-gray-500 dark:text-gray-400">{linked}/{total}</span>
                      </div>
                      <div className="w-full h-2 bg-gray-200 dark:bg-[#0D1117] rounded-full overflow-hidden">
                        <div
                          className="h-full transition-all duration-300"
                          style={{
                            backgroundColor: status.barColor,
                            width: `${Math.max(status.percentage, total > 0 ? 2 : 0)}%`
                          }}
                        />
                      </div>
                    </div>
                  )
                })()}

                {/* Delete Button (only show when not in bulk mode) */}
                {!bulkMode && (
                  <button
                    className="mt-4 w-full btn btn-danger btn-sm"
                    onClick={(e) => handleDeleteArtist(e, artist)}
                    disabled={deletingId === artist.id}
                    title={`Remove ${artist.name} and all associated albums`}
                  >
                    {deletingId === artist.id ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                        Deleting...
                      </>
                    ) : (
                      <>
                        <FiTrash2 className="w-4 h-4 mr-2" />
                        Remove Artist
                      </>
                    )}
                  </button>
                )}
              </div>
            </div>
              ))}
            </div>
          ) : (
            /* List View */
            <div className="card overflow-hidden">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-[#161B22] border-b border-gray-200 dark:border-[#30363D]">
                  <tr>
                    {bulkMode && <th className="px-4 py-3 text-left w-12"></th>}
                    <th className="px-4 py-3 text-left font-semibold text-gray-700 dark:text-gray-300">Artist</th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-700 dark:text-gray-300">Status</th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-700 dark:text-gray-300">Albums</th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-700 dark:text-gray-300 w-40">Files Linked</th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-700 dark:text-gray-300">Source</th>
                    {!bulkMode && <th className="px-4 py-3 text-right font-semibold text-gray-700 dark:text-gray-300">Actions</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
                  {artists.map((artist: Artist) => (
                    <tr
                      key={artist.id}
                      className={`hover:bg-gray-50 dark:hover:bg-[#161B22]/50 transition-colors ${
                        bulkMode ? 'cursor-pointer' : ''
                      } ${selectedArtistIds.has(artist.id) ? 'bg-[#FF1493]/5 dark:bg-[#FF1493]/10' : ''}`}
                      onClick={() => {
                        if (bulkMode) {
                          toggleArtistSelection(artist.id)
                        } else {
                          navigate(`/artists/${artist.id}`)
                        }
                      }}
                    >
                      {bulkMode && (
                        <td className="px-4 py-3">
                          <div className={`w-5 h-5 rounded border-2 flex items-center justify-center ${
                            selectedArtistIds.has(artist.id)
                              ? 'bg-[#FF1493] border-[#FF1493]'
                              : 'bg-white dark:bg-[#161B22] border-gray-300 dark:border-[#30363D]'
                          }`}>
                            {selectedArtistIds.has(artist.id) && (
                              <FiCheck className="w-3 h-3 text-white" />
                            )}
                          </div>
                        </td>
                      )}
                      <td className="px-4 py-3">
                        <div className="flex items-center space-x-3">
                          {artist.image_url ? (
                            <img
                              src={artist.image_url?.startsWith('http') ? artist.image_url : `/api/v1/${artist.id}/cover-art`}
                              alt={artist.name}
                              className="w-10 h-10 rounded object-cover"
                              loading="lazy"
                              onError={(e) => {
                                e.currentTarget.style.display = 'none'
                              }}
                            />
                          ) : (
                            <div className="w-10 h-10 rounded bg-gradient-to-br from-[#FF1493] to-[#FF8C00] flex items-center justify-center">
                              <FiMusic className="w-5 h-5 text-white/50" />
                            </div>
                          )}
                          <div>
                            <div className="font-medium text-gray-900 dark:text-white">{artist.name}</div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {artist.is_monitored ? (
                          <span className="badge badge-success">Monitored</span>
                        ) : (
                          <span className="badge badge-secondary">Unmonitored</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                        {artist.album_count || 0}
                      </td>
                      <td className="px-4 py-3">
                        {(() => {
                          const linked = artist.linked_files_count || 0
                          const total = artist.total_track_files || artist.track_count || 0
                          const status = getFileLinkingStatus(linked, total)
                          return (
                            <div className="w-full">
                              <div className="flex items-center justify-between text-xs mb-1">
                                <span className="font-medium" style={{ color: status.textColor }}>{status.statusText}</span>
                                <span className="text-gray-500 dark:text-gray-400">{linked}/{total}</span>
                              </div>
                              <div className="w-full h-2 bg-gray-200 dark:bg-[#0D1117] rounded-full overflow-hidden">
                                <div
                                  className="h-full transition-all duration-300"
                                  style={{
                                    backgroundColor: status.barColor,
                                    width: `${Math.max(status.percentage, total > 0 ? 2 : 0)}%`
                                  }}
                                />
                              </div>
                            </div>
                          )
                        })()}
                      </td>
                      <td className="px-4 py-3">
                        {artist.import_source ? (
                          <span className="badge badge-info text-xs capitalize">{artist.import_source}</span>
                        ) : (
                          <span className="text-gray-400 dark:text-gray-600">—</span>
                        )}
                      </td>
                      {!bulkMode && (
                        <td className="px-4 py-3 text-right">
                          <button
                            className="btn btn-danger btn-sm"
                            onClick={(e) => handleDeleteArtist(e, artist)}
                            disabled={deletingId === artist.id}
                            title={`Remove ${artist.name}`}
                          >
                            {deletingId === artist.id ? (
                              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                            ) : (
                              <FiTrash2 className="w-4 h-4" />
                            )}
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <Pagination
            page={page}
            totalPages={totalPages}
            totalCount={totalCount}
            itemsPerPage={itemsPerPage}
            onPageChange={(p) => { setPage(p); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
            onItemsPerPageChange={handleItemsPerPageChange}
            perPageOptions={[25, 50, 100, 200, 500]}
          />
        </>
      ) : (
        <div className="card p-12 text-center">
          <p className="text-gray-500 dark:text-gray-400">
            {filterMode === 'all'
              ? 'No artists found. Add or import artists to get started!'
              : `No ${filterMode} artists found.`
            }
          </p>
        </div>
      )}

      {/* Add Artist Modal (Two-Step) */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => { setShowAddModal(false); setSelectedMbArtist(null); setMbResults([]); setMbSearchQuery('') }}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            {/* Modal Header */}
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
                {selectedMbArtist ? 'Configure Artist' : 'Add Artist'}
              </h2>
              <button onClick={() => { setShowAddModal(false); setSelectedMbArtist(null); setMbResults([]); setMbSearchQuery('') }} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" title="Close">
                <FiX className="w-6 h-6" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
              {!selectedMbArtist ? (
                /* Step 1: Search MusicBrainz */
                <>
                  <div className="flex space-x-2">
                    <input
                      type="text"
                      placeholder="Search MusicBrainz for artist..."
                      className="input flex-1"
                      value={mbSearchQuery}
                      onChange={(e) => setMbSearchQuery(e.target.value)}
                      onKeyPress={(e) => e.key === 'Enter' && searchMusicBrainz()}
                    />
                    <button
                      className="btn btn-primary"
                      onClick={searchMusicBrainz}
                      disabled={mbSearching || !mbSearchQuery.trim()}
                      title="Search MusicBrainz for matching artists"
                    >
                      {mbSearching ? (
                        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                      ) : (
                        <>
                          <FiSearch className="w-4 h-4 mr-2" />
                          Search
                        </>
                      )}
                    </button>
                  </div>

                  <div className="overflow-y-auto max-h-96 space-y-2">
                    {mbSearching ? (
                      <div className="flex justify-center py-8">
                        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]"></div>
                      </div>
                    ) : mbResults.length > 0 ? (
                      mbResults.map((result) => (
                        <div key={result.id} className="border border-gray-200 dark:border-[#30363D] rounded-lg p-4 hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors">
                          <div className="flex items-start justify-between">
                            <div className="flex-1">
                              <h3 className="font-semibold text-gray-900 dark:text-white">{result.name}</h3>
                              {result.disambiguation && (
                                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">({result.disambiguation})</p>
                              )}
                              <div className="flex items-center space-x-4 mt-2 text-sm text-gray-500 dark:text-gray-400">
                                {result.type && <span>{result.type}</span>}
                                {result.country && <span>{result.country}</span>}
                                {result.score && <span className="text-[#FF1493]">Match: {result.score}%</span>}
                              </div>
                            </div>
                            <button
                              className="btn btn-primary btn-sm"
                              onClick={() => {
                                setSelectedMbArtist(result)
                                // Pre-select defaults
                                if (rootFolders && rootFolders.length > 0) {
                                  setAddRootFolder(rootFolders[0].path)
                                }
                                if (qualityProfiles) {
                                  const defaultProfile = qualityProfiles.find(p => p.is_default)
                                  if (defaultProfile) {
                                    setAddQualityProfile(defaultProfile.id)
                                  } else if (qualityProfiles.length > 0) {
                                    setAddQualityProfile(qualityProfiles[0].id)
                                  }
                                }
                              }}
                            >
                              Select
                            </button>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-center text-gray-500 dark:text-gray-400 py-8">
                        Search for an artist to add to your library
                      </p>
                    )}
                  </div>
                </>
              ) : (
                /* Step 2: Configure artist settings */
                <>
                  {/* Selected artist info */}
                  <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-4 flex items-center justify-between">
                    <div>
                      <h3 className="font-semibold text-gray-900 dark:text-white text-lg">{selectedMbArtist.name}</h3>
                      {selectedMbArtist.disambiguation && (
                        <p className="text-sm text-gray-600 dark:text-gray-400">({selectedMbArtist.disambiguation})</p>
                      )}
                      <div className="flex items-center space-x-3 mt-1 text-sm text-gray-500 dark:text-gray-400">
                        {selectedMbArtist.type && <span>{selectedMbArtist.type}</span>}
                        {selectedMbArtist.country && <span>{selectedMbArtist.country}</span>}
                      </div>
                    </div>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => setSelectedMbArtist(null)}
                    >
                      Change
                    </button>
                  </div>

                  {/* Root Folder */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Root Folder
                    </label>
                    <select
                      className="input w-full"
                      value={addRootFolder}
                      onChange={(e) => setAddRootFolder(e.target.value)}
                    >
                      <option value="">-- Select Root Folder --</option>
                      {rootFolders?.map((folder) => (
                        <option key={folder.id} value={folder.path}>
                          {folder.path} {folder.free_space_gb != null ? `(${folder.free_space_gb} GB free)` : ''}
                        </option>
                      ))}
                    </select>
                    {(!rootFolders || rootFolders.length === 0) && (
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        No root folders configured. Add one in Settings &gt; Root Folders.
                      </p>
                    )}
                  </div>

                  {/* Quality Profile */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Quality Profile
                    </label>
                    <select
                      className="input w-full"
                      value={addQualityProfile}
                      onChange={(e) => setAddQualityProfile(e.target.value)}
                    >
                      <option value="">-- Select Quality Profile --</option>
                      {qualityProfiles?.map((profile) => (
                        <option key={profile.id} value={profile.id}>
                          {profile.name} {profile.is_default ? '(Default)' : ''}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Monitor Type */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                      Monitor
                    </label>
                    <select
                      className="input w-full"
                      value={addMonitorType}
                      onChange={(e) => setAddMonitorType(e.target.value)}
                    >
                      <option value="all_albums">All Albums</option>
                      <option value="future_only">Future Albums Only</option>
                      <option value="existing_only">Existing Albums Only</option>
                      <option value="first_album">First Album</option>
                      <option value="latest_album">Latest Album</option>
                      <option value="none">None</option>
                    </select>
                  </div>

                  {/* Search for Missing */}
                  <div className="flex items-center">
                    <input
                      type="checkbox"
                      id="add-search-missing"
                      className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4"
                      checked={addSearchForMissing}
                      onChange={(e) => setAddSearchForMissing(e.target.checked)}
                    />
                    <label htmlFor="add-search-missing" className="ml-2 block text-sm text-gray-700 dark:text-gray-300">
                      Search for missing albums after adding
                    </label>
                  </div>
                </>
              )}
            </div>

            {/* Modal Footer - only show in Step 2 */}
            {selectedMbArtist && (
              <div className="flex items-center justify-end p-6 border-t border-gray-200 dark:border-[#30363D] space-x-3">
                <button
                  onClick={() => { setShowAddModal(false); setSelectedMbArtist(null); setMbResults([]); setMbSearchQuery('') }}
                  className="btn btn-secondary"
                  title="Cancel adding artist"
                >
                  Cancel
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => addArtistMutation.mutate(selectedMbArtist.id)}
                  disabled={addArtistMutation.isPending}
                  title="Add this artist to your library"
                >
                  {addArtistMutation.isPending ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                      Adding...
                    </>
                  ) : (
                    <>
                      <FiPlus className="w-4 h-4 mr-2" />
                      Add Artist
                    </>
                  )}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Single Artist Delete Dialog */}
      {deleteDialogArtist && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setDeleteDialogArtist(null)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="p-6">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                Remove Artist
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Are you sure you want to remove <strong>{deleteDialogArtist.name}</strong>? This will delete all associated albums, tracks, and download history.
              </p>

              {deleteDialogArtist.linkedFiles > 0 && (
                <div className="mb-4 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                  <p className="text-sm text-amber-800 dark:text-amber-200 mb-3">
                    This artist has <strong>{deleteDialogArtist.linkedFiles}</strong> linked file{deleteDialogArtist.linkedFiles !== 1 ? 's' : ''} on disk.
                  </p>
                  <label className="flex items-center space-x-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={deleteDialogFiles}
                      onChange={(e) => setDeleteDialogFiles(e.target.checked)}
                      className="rounded border-gray-300 text-red-600 focus:ring-red-500"
                    />
                    <span className="text-sm font-medium text-amber-900 dark:text-amber-100">
                      Also delete music files from disk
                    </span>
                  </label>
                </div>
              )}

              {deleteDialogFiles && (
                <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                  <p className="text-sm text-red-800 dark:text-red-200">
                    <strong>Warning:</strong> This will permanently delete {deleteDialogArtist.linkedFiles} music file{deleteDialogArtist.linkedFiles !== 1 ? 's' : ''} from disk. This cannot be undone.
                  </p>
                </div>
              )}
            </div>

            <div className="flex justify-end space-x-3 p-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-lg">
              <button className="btn btn-secondary" onClick={() => setDeleteDialogArtist(null)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() => {
                  setDeletingId(deleteDialogArtist.id)
                  deleteArtistMutation.mutate({ artistId: deleteDialogArtist.id, deleteFiles: deleteDialogFiles })
                }}
                disabled={deleteArtistMutation.isPending}
              >
                {deleteArtistMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Removing...
                  </>
                ) : (
                  <>
                    <FiTrash2 className="w-4 h-4 mr-2" />
                    {deleteDialogFiles ? 'Remove & Delete Files' : 'Remove Artist'}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Delete Dialog */}
      {bulkDeleteDialogOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setBulkDeleteDialogOpen(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="p-6">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                Remove {selectedArtistIds.size} Artist{selectedArtistIds.size !== 1 ? 's' : ''}
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                This will delete all associated albums, tracks, and download history for the selected artists.
              </p>

              {(() => {
                const totalLinked = artists
                  .filter((a: Artist) => selectedArtistIds.has(a.id))
                  .reduce((sum: number, a: Artist) => sum + (a.linked_files_count || 0), 0)
                return totalLinked > 0 ? (
                  <>
                    <div className="mb-4 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                      <p className="text-sm text-amber-800 dark:text-amber-200 mb-3">
                        The selected artists have <strong>{totalLinked}</strong> linked file{totalLinked !== 1 ? 's' : ''} on disk.
                      </p>
                      <label className="flex items-center space-x-3 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={bulkDeleteFiles}
                          onChange={(e) => setBulkDeleteFiles(e.target.checked)}
                          className="rounded border-gray-300 text-red-600 focus:ring-red-500"
                        />
                        <span className="text-sm font-medium text-amber-900 dark:text-amber-100">
                          Also delete music files from disk
                        </span>
                      </label>
                    </div>
                    {bulkDeleteFiles && (
                      <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                        <p className="text-sm text-red-800 dark:text-red-200">
                          <strong>Warning:</strong> This will permanently delete {totalLinked} music file{totalLinked !== 1 ? 's' : ''} from disk. This cannot be undone.
                        </p>
                      </div>
                    )}
                  </>
                ) : null
              })()}
            </div>

            <div className="flex justify-end space-x-3 p-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-lg">
              <button className="btn btn-secondary" onClick={() => setBulkDeleteDialogOpen(false)}>
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() => bulkDeleteMutation.mutate({ artistIds: Array.from(selectedArtistIds), deleteFiles: bulkDeleteFiles })}
                disabled={bulkDeleteMutation.isPending}
              >
                {bulkDeleteMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Removing...
                  </>
                ) : (
                  <>
                    <FiTrash2 className="w-4 h-4 mr-2" />
                    {bulkDeleteFiles ? 'Remove & Delete Files' : `Remove ${selectedArtistIds.size} Artist${selectedArtistIds.size !== 1 ? 's' : ''}`}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Import Artists Modal */}
      <ImportArtistsModal
        isOpen={showImportModal}
        onClose={() => setShowImportModal(false)}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ['artists'] })}
      />

      {/* Resolve MBIDs Modal */}
      {showResolveModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowResolveModal(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-3xl w-full mx-4 max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-[#30363D]">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Resolve MusicBrainz IDs</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Auto-matching artists without MBIDs using local database
                </p>
              </div>
              <button onClick={() => setShowResolveModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <FiX className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 overflow-y-auto flex-1">
              {resolveLoading ? (
                <div className="flex items-center justify-center py-12">
                  <FiLoader className="w-8 h-8 text-[#FF1493] animate-spin mr-3" />
                  <span className="text-gray-600 dark:text-gray-400">Searching local MusicBrainz database...</span>
                </div>
              ) : resolveResults ? (
                <div className="space-y-4">
                  {/* Stats Summary */}
                  <div className="grid grid-cols-3 gap-4">
                    <div className="text-center p-3 bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg">
                      <div className="text-2xl font-bold text-gray-900 dark:text-white">{resolveResults.stats.total}</div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">Artists Without MBID</div>
                    </div>
                    <div className="text-center p-3 bg-green-50 dark:bg-green-900/20 rounded-lg">
                      <div className="text-2xl font-bold text-green-700 dark:text-green-400">{resolveResults.stats.resolved}</div>
                      <div className="text-xs text-green-600 dark:text-green-500">Auto-Resolved</div>
                    </div>
                    <div className="text-center p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                      <div className="text-2xl font-bold text-yellow-700 dark:text-yellow-400">{resolveResults.stats.unresolved}</div>
                      <div className="text-xs text-yellow-600 dark:text-yellow-500">Unresolved</div>
                    </div>
                  </div>

                  {/* Resolved List */}
                  {resolveResults.resolved.length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold text-green-700 dark:text-green-400 mb-2 flex items-center">
                        <FiCheck className="w-4 h-4 mr-1" />
                        Auto-Resolved ({resolveResults.resolved.length})
                      </h4>
                      <div className="max-h-40 overflow-y-auto space-y-1">
                        {resolveResults.resolved.map(a => (
                          <div key={a.id} className="flex items-center justify-between text-sm px-3 py-1.5 bg-green-50 dark:bg-green-900/10 rounded">
                            <span className="text-gray-900 dark:text-white truncate">{a.name}</span>
                            <span className="text-xs text-green-600 dark:text-green-400 flex-shrink-0 ml-2">
                              {a.score}% → {a.matched_name}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Unresolved List */}
                  {resolveResults.unresolved.length > 0 && (
                    <div>
                      <h4 className="text-sm font-semibold text-yellow-700 dark:text-yellow-400 mb-2 flex items-center">
                        <FiAlertCircle className="w-4 h-4 mr-1" />
                        Unresolved ({resolveResults.unresolved.length})
                      </h4>
                      <div className="max-h-40 overflow-y-auto space-y-1">
                        {resolveResults.unresolved.map(a => (
                          <div key={a.id} className="flex items-center justify-between text-sm px-3 py-1.5 bg-yellow-50 dark:bg-yellow-900/10 rounded">
                            <span className="text-gray-900 dark:text-white truncate">{a.name}</span>
                            {a.top_match && (
                              <span className="text-xs text-yellow-600 dark:text-yellow-400 flex-shrink-0 ml-2">
                                Best: {a.top_match.name} ({a.top_match.score}%)
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {resolveResults.stats.total === 0 && (
                    <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                      <FiCheck className="w-8 h-8 mx-auto mb-2 text-green-500" />
                      <p>All artists already have MusicBrainz IDs!</p>
                    </div>
                  )}
                </div>
              ) : null}
            </div>

            <div className="flex justify-between items-center p-4 border-t border-gray-200 dark:border-[#30363D]">
              <div>
                {resolveResults && resolveResults.unresolved.length > 0 && !remoteResolveTaskId && (
                  <button
                    className="btn btn-primary"
                    onClick={handleRemoteResolve}
                    disabled={remoteResolveLoading}
                  >
                    {remoteResolveLoading ? (
                      <>
                        <FiLoader className="w-4 h-4 mr-2 animate-spin" />
                        Starting...
                      </>
                    ) : (
                      <>
                        <FiSearch className="w-4 h-4 mr-2" />
                        Search Remote API ({resolveResults.unresolved.length} artists)
                      </>
                    )}
                  </button>
                )}
                {remoteResolveTaskId && (
                  <span className="text-sm text-green-600 dark:text-green-400 flex items-center">
                    <FiCheck className="w-4 h-4 mr-1" />
                    Remote resolution queued. Check Activity page.
                  </span>
                )}
              </div>
              <button className="btn btn-secondary" onClick={() => setShowResolveModal(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Artists
