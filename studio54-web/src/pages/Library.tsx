import React, { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useSearchParamState } from '../hooks/useSearchParamState'
import { FiSearch, FiPlus, FiRefreshCw, FiX, FiMusic, FiDownload, FiCheck, FiPlay, FiHeadphones, FiLoader, FiFileText, FiChevronUp, FiChevronDown, FiEdit2, FiLink, FiSave, FiCrosshair, FiTrash2, FiMoreVertical } from 'react-icons/fi'
import Pagination from '../components/Pagination'
import toast, { Toaster } from 'react-hot-toast'
import { searchPreview } from '../api/itunes'
import ImportArtistsModal from '../components/ImportArtistsModal'
import LinkFileModal from '../components/LinkFileModal'
import LibraryScanner from './LibraryScanner'
import StatusBar from '../components/StatusBar'
import AddToPlaylistDropdown from '../components/AddToPlaylistDropdown'
import StarRating from '../components/StarRating'
import { usePlayer } from '../contexts/PlayerContext'
import { S54 } from '../assets/graphics'
import { useAuth } from '../contexts/AuthContext'
import { artistsApi, tracksApi, fileOrganizationApi, authFetch } from '../api/client'
import type { TrackListItem } from '../api/client'
import type { Artist, Album, UnlinkedFile, UnorganizedFile } from '../types'

type TabMode = 'browse' | 'scanner' | 'import' | 'unlinked' | 'unorganized'
type SortMode = 'artist' | 'album' | 'track'
type FilterMode = 'all' | 'monitored' | 'unmonitored'
type TrackFilter = 'all' | 'has_file' | 'missing'
type ArtistSortBy = 'name' | 'files_desc' | 'files_asc' | 'added_at'
type AlbumSortBy = 'release_date' | 'title' | 'files_desc' | 'files_asc' | 'added_at'

function Library() {
  const { isDirector, isDjOrAbove } = useAuth()
  const [activeTab, setActiveTab] = useSearchParamState('tab', 'browse') as [TabMode, (v: string) => void]
  const [sortMode, setSortMode] = useSearchParamState('sort', 'artist') as [SortMode, (v: string) => void]
  const [searchQuery, setSearchQuery] = useSearchParamState('q', '')
  const [filterMode, setFilterMode] = useSearchParamState('filter', 'all') as [FilterMode, (v: string) => void]
  const [pageStr, setPageStr] = useSearchParamState('page', '1')
  const page = parseInt(pageStr, 10) || 1
  const setPage = useCallback((p: number) => setPageStr(String(p)), [setPageStr])
  const [itemsPerPage, setItemsPerPage] = useState(100)
  const [showImportModal, setShowImportModal] = useState(false)
  const [bulkMode, setBulkMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showAddArtistModal, setShowAddArtistModal] = useState(false)
  const [actionsMenuOpen, setActionsMenuOpen] = useState(false)
  const [trackFilter, setTrackFilter] = useSearchParamState('trackFilter', 'all') as [TrackFilter, (v: string) => void]
  const [genreFilter, setGenreFilter] = useSearchParamState('genre', '')
  const [artistSortBy, setArtistSortBy] = useSearchParamState('artistSort', 'name') as [ArtistSortBy, (v: string) => void]
  const [albumSortBy, setAlbumSortBy] = useSearchParamState('albumSort', 'release_date') as [AlbumSortBy, (v: string) => void]
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false)
  const [bulkDeleteFiles, setBulkDeleteFiles] = useState(false)
  const [previewLoading, setPreviewLoading] = useState<Map<string, boolean>>(new Map())
  const [mbSearchQuery, setMbSearchQuery] = useState('')
  const [mbResults, setMbResults] = useState<any[]>([])
  const [mbSearching, setMbSearching] = useState(false)
  const [cleanupOrphanedDialogOpen, setCleanupOrphanedDialogOpen] = useState(false)
  const [orphanedCount, setOrphanedCount] = useState<number | null>(null)
  const [orphanedLoading, setOrphanedLoading] = useState(false)
  const [unlinkedReasonFilter, setUnlinkedReasonFilter] = useState<string>('')
  const [unlinkedSearch, setUnlinkedSearch] = useState('')
  const [unlinkedPage, setUnlinkedPage] = useState(1)
  const [unlinkedSortBy, setUnlinkedSortBy] = useState<string>('')
  const [unlinkedSortDir, setUnlinkedSortDir] = useState<'asc' | 'desc'>('asc')
  const [editingUnlinkedId, setEditingUnlinkedId] = useState<string | null>(null)
  const [editFields, setEditFields] = useState<{ artist: string; album: string; title: string }>({ artist: '', album: '', title: '' })
  const [linkModalFile, setLinkModalFile] = useState<{ id: string; file_path: string; artist?: string | null; album?: string | null; title?: string | null } | null>(null)
  const [acoustidResults, setAcoustidResults] = useState<{ fileId: string; matches: any[] } | null>(null)
  const [acoustidLoading, setAcoustidLoading] = useState<string | null>(null)
  const [unorganizedSearch, setUnorganizedSearch] = useState('')
  const [unorganizedFormatFilter, setUnorganizedFormatFilter] = useState('')
  const [unorganizedPage, setUnorganizedPage] = useState(1)
  const [unorganizedSortBy, setUnorganizedSortBy] = useState<string>('')
  const [unorganizedSortDir, setUnorganizedSortDir] = useState<'asc' | 'desc'>('asc')

  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const player = usePlayer()

  // Fetch genre list for filter dropdown
  const { data: genresData } = useQuery({
    queryKey: ['artist-genres'],
    queryFn: async () => {
      const response = await authFetch('/api/v1/artists/genres')
      if (!response.ok) throw new Error('Failed to fetch genres')
      return response.json()
    },
  })

  // Fetch artists when sort mode is 'artist'
  const { data: artistsData, isLoading: artistsLoading } = useQuery({
    queryKey: ['library-artists', filterMode, artistSortBy, genreFilter, searchQuery, page, itemsPerPage],
    queryFn: async () => {
      const params: Record<string, string> = {
        monitored_only: filterMode === 'monitored' ? 'true' : 'false',
        unmonitored_only: filterMode === 'unmonitored' ? 'true' : 'false',
        search_query: searchQuery,
        limit: String(itemsPerPage),
        offset: String((page - 1) * itemsPerPage),
      }
      if (artistSortBy !== 'name') params.sort_by = artistSortBy
      if (genreFilter) params.genre = genreFilter
      const response = await authFetch(`/api/v1/artists?${new URLSearchParams(params)}`)
      if (!response.ok) throw new Error('Failed to fetch artists')
      return response.json()
    },
    enabled: activeTab === 'browse' && sortMode === 'artist',
  })

  // Fetch albums when sort mode is 'album'
  const { data: albumsData, isLoading: albumsLoading } = useQuery({
    queryKey: ['library-albums', filterMode, albumSortBy, searchQuery, page, itemsPerPage],
    queryFn: async () => {
      const params: Record<string, string> = {
        monitored_only: filterMode === 'monitored' ? 'true' : 'false',
        limit: String(itemsPerPage),
        offset: String((page - 1) * itemsPerPage),
      }
      if (searchQuery) params.search_query = searchQuery
      if (albumSortBy !== 'release_date') params.sort_by = albumSortBy
      const response = await authFetch(`/api/v1/albums?${new URLSearchParams(params)}`)
      if (!response.ok) throw new Error('Failed to fetch albums')
      return response.json()
    },
    enabled: activeTab === 'browse' && sortMode === 'album',
  })

  // Fetch tracks when sort mode is 'track'
  const { data: tracksData, isLoading: tracksLoading } = useQuery({
    queryKey: ['library-tracks', searchQuery, trackFilter, page, itemsPerPage],
    queryFn: async () => {
      const params: Record<string, any> = {
        limit: itemsPerPage,
        offset: (page - 1) * itemsPerPage,
      }
      if (searchQuery) params.search_query = searchQuery
      if (trackFilter === 'has_file') params.has_file = true
      if (trackFilter === 'missing') params.has_file = false
      return tracksApi.list(params)
    },
    enabled: activeTab === 'browse' && sortMode === 'track',
  })

  const artists = artistsData?.artists || []
  const albums = albumsData?.albums || []
  const tracks: TrackListItem[] = tracksData?.tracks || []

  const totalCount = sortMode === 'artist'
    ? (artistsData?.total_count || 0)
    : sortMode === 'album'
    ? (albumsData?.total_count || 0)
    : sortMode === 'track'
    ? (tracksData?.total_count || 0)
    : 0

  const isLoading = sortMode === 'artist' ? artistsLoading : sortMode === 'album' ? albumsLoading : tracksLoading

  // Fetch unlinked files when on unlinked tab
  const { data: unlinkedData, isLoading: unlinkedLoading, refetch: refetchUnlinked } = useQuery({
    queryKey: ['unlinked-files', 'music', unlinkedReasonFilter, unlinkedSearch, unlinkedPage, unlinkedSortBy, unlinkedSortDir],
    queryFn: () => fileOrganizationApi.getUnlinkedFiles({
      reason: unlinkedReasonFilter || undefined,
      search: unlinkedSearch || undefined,
      library_type: 'music',
      page: unlinkedPage,
      per_page: 50,
      sort_by: unlinkedSortBy || undefined,
      sort_dir: unlinkedSortDir,
    }),
    enabled: activeTab === 'unlinked',
  })

  const { data: unlinkedSummary } = useQuery({
    queryKey: ['unlinked-summary', 'music'],
    queryFn: () => fileOrganizationApi.getUnlinkedSummary({ library_type: 'music' }),
    enabled: activeTab === 'unlinked',
  })

  // Mutation for editing unlinked file metadata
  const editMetadataMutation = useMutation({
    mutationFn: ({ id, fields }: { id: string; fields: { artist?: string; album?: string; title?: string } }) =>
      fileOrganizationApi.updateUnlinkedMetadata(id, fields),
    onSuccess: () => {
      toast.success('Metadata updated')
      setEditingUnlinkedId(null)
      refetchUnlinked()
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to update metadata')
    },
  })

  // Fetch unorganized files when on unorganized tab
  const { data: unorganizedData, isLoading: unorganizedLoading, refetch: refetchUnorganized } = useQuery({
    queryKey: ['unorganized-files', 'music', unorganizedSearch, unorganizedFormatFilter, unorganizedPage, unorganizedSortBy, unorganizedSortDir],
    queryFn: () => fileOrganizationApi.getUnorganizedFiles({
      search: unorganizedSearch || undefined,
      format: unorganizedFormatFilter || undefined,
      library_type: 'music',
      page: unorganizedPage,
      per_page: 50,
      sort_by: unorganizedSortBy || undefined,
      sort_dir: unorganizedSortDir,
    }),
    enabled: activeTab === 'unorganized',
  })

  const { data: unorganizedSummary } = useQuery({
    queryKey: ['unorganized-summary', 'music'],
    queryFn: () => fileOrganizationApi.getUnorganizedSummary({ library_type: 'music' }),
    enabled: activeTab === 'unorganized',
  })

  // Search MusicBrainz for adding artists
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

  // Add artist mutation
  const addArtistMutation = useMutation({
    mutationFn: async (mbid: string) => {
      const response = await authFetch('/api/v1/artists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ musicbrainz_id: mbid, is_monitored: true })
      })
      if (!response.ok) throw new Error('Failed to add artist')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-artists'] })
      setShowAddArtistModal(false)
      setMbSearchQuery('')
      setMbResults([])
    }
  })

  // Bulk update mutation
  const bulkUpdateMutation = useMutation({
    mutationFn: async (monitored: boolean) => {
      if (sortMode !== 'artist') return
      const response = await authFetch('/api/v1/artists/bulk-update', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          artist_ids: Array.from(selectedIds),
          is_monitored: monitored,
        }),
      })
      if (!response.ok) throw new Error('Bulk update failed')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-artists'] })
      setSelectedIds(new Set())
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
      queryClient.invalidateQueries({ queryKey: ['library-artists'] })
      setSelectedIds(new Set())
      setBulkMode(false)
      setBulkDeleteDialogOpen(false)
      setBulkDeleteFiles(false)
    },
    onError: (error: Error) => {
      alert(`Error deleting artists: ${error.message}`)
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

  const syncAllAlbumsMutation = useMutation({
    mutationFn: async () => {
      return artistsApi.syncAllAlbums()
    },
    onSuccess: (data) => {
      alert(`Syncing albums for ${data.total_artists} artists. This will backfill missing tracks. Check Activity page to monitor progress.`)
    },
    onError: (error: Error) => {
      alert(`Failed to queue album sync: ${error.message}`)
    }
  })

  const handleShowCleanupOrphaned = async () => {
    setOrphanedLoading(true)
    try {
      const data = await artistsApi.getOrphaned()
      setOrphanedCount(data.count)
      setCleanupOrphanedDialogOpen(true)
    } catch (err: any) {
      toast.error(`Failed to check orphaned artists: ${err.message}`)
    } finally {
      setOrphanedLoading(false)
    }
  }

  const cleanupOrphanedMutation = useMutation({
    mutationFn: async () => {
      return artistsApi.cleanupOrphaned()
    },
    onSuccess: (data) => {
      toast.success(`Removed ${data.deleted_count} orphaned artists`)
      setCleanupOrphanedDialogOpen(false)
      queryClient.invalidateQueries({ queryKey: ['library-artists'] })
    },
    onError: (error: Error) => {
      toast.error(`Failed to cleanup: ${error.message}`)
    }
  })

  const toggleSelection = (id: string) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }
    setSelectedIds(newSelected)
  }

  const toggleSelectAll = () => {
    const items: any[] = sortMode === 'artist' ? artists : sortMode === 'album' ? albums : tracks
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set())
    } else {
      const allIds = new Set<string>(items.map((item: any) => item.id as string))
      setSelectedIds(allIds)
    }
  }

  // Render artist card (smaller - 1/3 size)
  const renderArtistCard = (artist: Artist) => (
    <div
      key={artist.id}
      className={`card p-0 hover:shadow-lg transition-shadow group ${
        bulkMode ? 'cursor-pointer' : ''
      } ${selectedIds.has(artist.id) ? 'ring-2 ring-[#FF1493]' : ''}`}
      onClick={() => {
        if (bulkMode) {
          toggleSelection(artist.id)
        } else {
          navigate(`/disco-lounge/artists/${artist.id}`)
        }
      }}
    >
      {/* Artist Image - 1/3 size */}
      <div className="relative bg-gradient-to-br from-[#FF1493] to-[#FF8C00] h-32 flex items-center justify-center overflow-hidden">
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
          <FiMusic className="w-12 h-12 text-white/30" />
        )}
        {bulkMode && (
          <div className="absolute top-2 left-2">
            <input
              type="checkbox"
              checked={selectedIds.has(artist.id)}
              onChange={() => toggleSelection(artist.id)}
              className="w-5 h-5"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        )}
      </div>

      {/* Artist Info */}
      <div className="p-3">
        <h3 className="font-semibold text-gray-900 dark:text-white truncate text-sm">
          {artist.name}
        </h3>
        <div className="flex items-center justify-between mt-1">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {artist.album_count || 0} albums
          </span>
          {artist.is_monitored && (
            <span className="badge badge-sm badge-primary">
              <FiCheck className="w-3 h-3" />
            </span>
          )}
        </div>
        {artist.rating_override != null && (
          <div className="mt-1">
            <StarRating rating={artist.rating_override} size="sm" />
          </div>
        )}
        <div className="mt-2">
          <StatusBar
            isMonitored={artist.is_monitored}
            linkedFiles={artist.linked_files_count || 0}
            totalTracks={artist.total_track_files || artist.track_count || 0}
            albumCount={artist.album_count || 0}
          />
        </div>
      </div>
    </div>
  )

  // Render album card (with album art)
  const renderAlbumCard = (album: Album) => (
    <div
      key={album.id}
      className="card p-0 hover:shadow-lg transition-shadow cursor-pointer"
      onClick={() => navigate(`/disco-lounge/albums/${album.id}`)}
    >
      {/* Album Cover - square aspect ratio, centered, no crop */}
      <div className="relative bg-gradient-to-br from-purple-600 to-purple-800 aspect-square flex items-center justify-center">
        <img
          src={album.cover_art_url || S54.defaultAlbumArt}
          alt={album.title}
          loading="lazy"
          className="w-full h-full object-contain"
        />
      </div>

      {/* Album Info */}
      <div className="p-3">
        <h3 className="font-semibold text-gray-900 dark:text-white truncate text-sm">
          {album.title}
        </h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-1">
          {album.artist_name}
        </p>
        <div className="flex items-center justify-between mt-1">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {album.track_count || 0} tracks
          </span>
          {album.monitored && (
            <span className="badge badge-sm badge-primary">
              <FiCheck className="w-3 h-3" />
            </span>
          )}
        </div>
        <div className="mt-2">
          <StatusBar
            isMonitored={album.monitored}
            linkedFiles={album.linked_files_count || 0}
            totalTracks={album.track_count || 0}
          />
        </div>
      </div>
    </div>
  )

  const formatDuration = (ms: number | null): string => {
    if (!ms) return '--:--'
    const minutes = Math.floor(ms / 60000)
    const seconds = Math.floor((ms % 60000) / 1000)
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }

  const items: any[] = sortMode === 'artist' ? artists : sortMode === 'album' ? albums : tracks

  const toggleUnlinkedSort = (col: string) => {
    if (unlinkedSortBy === col) {
      setUnlinkedSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setUnlinkedSortBy(col)
      setUnlinkedSortDir('asc')
    }
    setUnlinkedPage(1)
  }

  const toggleUnorganizedSort = (col: string) => {
    if (unorganizedSortBy === col) {
      setUnorganizedSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setUnorganizedSortBy(col)
      setUnorganizedSortDir('asc')
    }
    setUnorganizedPage(1)
  }

  const SortIcon = ({ column, activeCol, activeDir }: { column: string; activeCol: string; activeDir: 'asc' | 'desc' }) => {
    if (column !== activeCol) return <FiChevronDown className="w-3 h-3 opacity-0 group-hover:opacity-40 ml-1 inline" />
    return activeDir === 'asc'
      ? <FiChevronUp className="w-3 h-3 ml-1 inline text-[#FF1493]" />
      : <FiChevronDown className="w-3 h-3 ml-1 inline text-[#FF1493]" />
  }

  return (
    <div className="space-y-6 overflow-x-hidden">
      <Toaster position="top-right" />
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">
            Library {activeTab === 'browse' && totalCount > 0 && (
              <span className="text-gray-500 dark:text-gray-400">({totalCount.toLocaleString()})</span>
            )}
          </h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            {activeTab === 'browse' && 'Browse and manage your music collection'}
            {activeTab === 'scanner' && 'Index and search your music files'}
            {activeTab === 'import' && 'Import artists from MUSE or MusicBrainz'}
            {activeTab === 'unlinked' && 'Files that could not be linked to album tracks'}
            {activeTab === 'unorganized' && 'Files that have not been organized into the standard folder structure'}
          </p>
        </div>
        {activeTab === 'browse' && (
          <div className="flex items-center gap-2">
            {/* Desktop buttons */}
            <div className="hidden lg:flex flex-wrap gap-2">
              <button className="btn btn-secondary" onClick={() => queryClient.invalidateQueries({ queryKey: ['library-artists', 'library-albums', 'library-tracks'] })} title="Refresh library data">
                <FiRefreshCw className="w-4 h-4 mr-2" />
                Refresh
              </button>
              {sortMode === 'artist' && isDirector && (
                <>
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
                    {refreshAllMetadataMutation.isPending ? 'Queueing...' : 'Get Metadata'}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      if (confirm(`Sync albums and tracks for all ${totalCount} artists? This will backfill missing tracks from MusicBrainz.`)) {
                        syncAllAlbumsMutation.mutate()
                      }
                    }}
                    disabled={syncAllAlbumsMutation.isPending}
                    title="Sync albums and tracks for all artists from MusicBrainz"
                  >
                    <FiRefreshCw className="w-4 h-4 mr-2" />
                    {syncAllAlbumsMutation.isPending ? 'Queueing...' : 'Sync All Albums'}
                  </button>
                  <button
                    className="btn btn-secondary text-red-600 dark:text-red-400 border-red-300 dark:border-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                    onClick={handleShowCleanupOrphaned}
                    disabled={orphanedLoading}
                    title="Remove unmonitored artists with no linked files"
                  >
                    <FiX className="w-4 h-4 mr-2" />
                    {orphanedLoading ? 'Checking...' : 'Cleanup Orphaned'}
                  </button>
                </>
              )}
              {isDjOrAbove && (
                <button className="btn btn-primary" onClick={() => setShowAddArtistModal(true)} title="Add a new artist from MusicBrainz">
                  <FiPlus className="w-4 h-4 mr-2" />
                  Add Artist
                </button>
              )}
            </div>

            {/* Mobile/Tablet: Add Artist button + actions menu */}
            <div className="flex lg:hidden items-center gap-2">
              {isDjOrAbove && (
                <button className="btn btn-primary" onClick={() => setShowAddArtistModal(true)} title="Add a new artist from MusicBrainz">
                  <FiPlus className="w-4 h-4 mr-2" />
                  Add Artist
                </button>
              )}
              <div className="relative">
                <button
                  onClick={() => setActionsMenuOpen(!actionsMenuOpen)}
                  className="p-2 rounded-lg bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D] transition-colors"
                  title="More actions"
                >
                  <FiMoreVertical className="w-5 h-5" />
                </button>
                {actionsMenuOpen && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setActionsMenuOpen(false)} />
                    <div className="absolute left-0 md:right-0 md:left-auto top-full mt-1 w-56 bg-white dark:bg-[#161B22] rounded-lg shadow-xl border border-gray-200 dark:border-[#30363D] z-40 py-1">
                      <button
                        className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                        onClick={() => { queryClient.invalidateQueries({ queryKey: ['library-artists', 'library-albums', 'library-tracks'] }); setActionsMenuOpen(false) }}
                      >
                        <FiRefreshCw className="w-4 h-4 mr-3 text-gray-500" />
                        Refresh
                      </button>
                      {sortMode === 'artist' && isDirector && (
                        <>
                          <button
                            className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                            onClick={() => {
                              if (confirm(`Queue metadata refresh for all ${totalCount} artists?`)) {
                                refreshAllMetadataMutation.mutate()
                              }
                              setActionsMenuOpen(false)
                            }}
                            disabled={refreshAllMetadataMutation.isPending}
                          >
                            <FiRefreshCw className="w-4 h-4 mr-3 text-gray-500" />
                            Get Metadata
                          </button>
                          <button
                            className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                            onClick={() => {
                              if (confirm(`Sync albums and tracks for all ${totalCount} artists?`)) {
                                syncAllAlbumsMutation.mutate()
                              }
                              setActionsMenuOpen(false)
                            }}
                            disabled={syncAllAlbumsMutation.isPending}
                          >
                            <FiRefreshCw className="w-4 h-4 mr-3 text-gray-500" />
                            Sync All Albums
                          </button>
                          <div className="border-t border-gray-200 dark:border-[#30363D] my-1" />
                          <button
                            className="w-full flex items-center px-4 py-2.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                            onClick={() => { handleShowCleanupOrphaned(); setActionsMenuOpen(false) }}
                            disabled={orphanedLoading}
                          >
                            <FiX className="w-4 h-4 mr-3" />
                            Cleanup Orphaned
                          </button>
                        </>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-[#30363D] overflow-x-auto">
        <nav className="-mb-px flex flex-nowrap space-x-8">
          <button
            onClick={() => setActiveTab('browse')}
            className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap transition-colors ${
              activeTab === 'browse'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Browse Library
          </button>
          {isDirector && (
          <button
            onClick={() => setActiveTab('scanner')}
            className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap transition-colors ${
              activeTab === 'scanner'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Scanner
          </button>
          )}
          {isDirector && (
          <button
            onClick={() => setActiveTab('import')}
            className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap transition-colors ${
              activeTab === 'import'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Import Music
          </button>
          )}
          {isDirector && (
          <button
            onClick={() => setActiveTab('unlinked')}
            className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap transition-colors flex items-center gap-2 ${
              activeTab === 'unlinked'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Unlinked Files
            {unlinkedSummary?.total > 0 && (
              <span className="bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 text-xs px-1.5 py-0.5 rounded-full">
                {unlinkedSummary.total.toLocaleString()}
              </span>
            )}
          </button>
          )}
          {isDirector && (
          <button
            onClick={() => setActiveTab('unorganized')}
            className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap transition-colors flex items-center gap-2 ${
              activeTab === 'unorganized'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Unorganized Files
            {unorganizedSummary?.total_unorganized > 0 && (
              <span className="bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300 text-xs px-1.5 py-0.5 rounded-full">
                {unorganizedSummary.total_unorganized.toLocaleString()}
              </span>
            )}
          </button>
          )}
        </nav>
      </div>

      {/* Tab Content */}
      {activeTab === 'browse' && (
        <>
          {/* Controls */}
          <div className="card p-4 space-y-4">
            {/* Sort Mode and Filters */}
            <div className="flex flex-wrap items-end gap-3">
              {/* Sort Dropdown */}
              <div className="relative">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Sort by
                </label>
                <select
                  value={sortMode}
                  onChange={(e) => {
                    setSortMode(e.target.value as SortMode)
                    setPage(1)
                    setSelectedIds(new Set())
                    setBulkMode(false)
                  }}
                  className="px-4 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#161B22] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                >
                  <option value="artist">Artists</option>
                  <option value="album">Albums</option>
                  <option value="track">Tracks</option>
                </select>
              </div>

              {/* Order By Dropdown */}
              {sortMode === 'artist' && (
                <>
                  <div className="relative">
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Order by
                    </label>
                    <select
                      value={artistSortBy}
                      onChange={(e) => { setArtistSortBy(e.target.value as ArtistSortBy); setPage(1) }}
                      className="px-4 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#161B22] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                      title="Sort artists"
                    >
                      <option value="name">Name</option>
                      <option value="files_desc">Most Files</option>
                      <option value="files_asc">Least Files</option>
                      <option value="added_at">Recently Added</option>
                    </select>
                  </div>
                  {genresData?.genres?.length > 0 && (
                    <div className="relative">
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                        Genre
                      </label>
                      <select
                        value={genreFilter}
                        onChange={(e) => { setGenreFilter(e.target.value); setPage(1) }}
                        className="px-4 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#161B22] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                        title="Filter by genre"
                      >
                        <option value="">All Genres</option>
                        {genresData.genres.map((g: string) => (
                          <option key={g} value={g}>{g}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </>
              )}
              {sortMode === 'album' && (
                <div className="relative">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Order by
                  </label>
                  <select
                    value={albumSortBy}
                    onChange={(e) => { setAlbumSortBy(e.target.value as AlbumSortBy); setPage(1) }}
                    className="px-4 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#161B22] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                    title="Sort albums"
                  >
                    <option value="release_date">Release Date</option>
                    <option value="title">Title</option>
                    <option value="files_desc">Most Files</option>
                    <option value="files_asc">Least Files</option>
                    <option value="added_at">Recently Added</option>
                  </select>
                </div>
              )}

              {/* Filter Toggles */}
              <div className="flex flex-wrap items-end gap-2">
                {sortMode === 'track' ? (
                  <>
                    {(['all', 'has_file', 'missing'] as const).map((tf) => (
                      <button
                        key={tf}
                        className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                          trackFilter === tf
                            ? 'bg-[#FF1493] text-white'
                            : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                        }`}
                        onClick={() => { setTrackFilter(tf); setPage(1) }}
                      >
                        {tf === 'all' ? 'All' : tf === 'has_file' ? 'Has File' : 'Missing'}
                      </button>
                    ))}
                  </>
                ) : (
                  <>
                    <button
                      className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                        filterMode === 'all'
                          ? 'bg-[#FF1493] text-white'
                          : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                      }`}
                      onClick={() => { setFilterMode('all'); setPage(1) }}
                    >
                      All
                    </button>
                    <button
                      className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                        filterMode === 'monitored'
                          ? 'bg-[#FF1493] text-white'
                          : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                      }`}
                      onClick={() => { setFilterMode('monitored'); setPage(1) }}
                    >
                      Monitored
                    </button>
                    <button
                      className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                        filterMode === 'unmonitored'
                          ? 'bg-[#FF1493] text-white'
                          : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                      }`}
                      onClick={() => { setFilterMode('unmonitored'); setPage(1) }}
                    >
                      Unmonitored
                    </button>
                  </>
                )}
              </div>

              {/* Bulk Mode (Artists only, DJ+ for monitor, Director for delete) */}
              {sortMode === 'artist' && isDjOrAbove && (
                <button
                  className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                    bulkMode
                      ? 'bg-orange-600 text-white hover:bg-orange-700'
                      : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                  }`}
                  onClick={() => {
                    setBulkMode(!bulkMode)
                    if (bulkMode) setSelectedIds(new Set())
                  }}
                  title={bulkMode ? 'Exit selection mode' : 'Enable bulk selection'}
                >
                  {bulkMode ? 'Cancel Selection' : 'Select Mode'}
                </button>
              )}
            </div>

            {/* Search */}
            <div className="flex items-center">
              <FiSearch className="w-5 h-5 text-gray-400 mr-3" />
              <input
                type="text"
                placeholder={`Search ${sortMode === 'artist' ? 'artists' : sortMode === 'album' ? 'albums' : 'tracks'}...`}
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value)
                  setPage(1)
                }}
                className="flex-1 bg-transparent border-none focus:outline-none text-gray-900 dark:text-white placeholder-gray-400"
              />
              {searchQuery && (
                <button
                  onClick={() => {
                    setSearchQuery('')
                    setPage(1)
                  }}
                  className="ml-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                  title="Clear search"
                >
                  <FiX className="w-5 h-5" />
                </button>
              )}
            </div>
          </div>

          {/* Bulk Actions Bar */}
          {bulkMode && selectedIds.size > 0 && sortMode === 'artist' && (
            <div className="card p-4 bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {selectedIds.size} artist{selectedIds.size !== 1 ? 's' : ''} selected
                </span>
                <div className="flex space-x-2">
                  <button
                    className="btn btn-sm btn-primary"
                    onClick={() => bulkUpdateMutation.mutate(true)}
                    disabled={bulkUpdateMutation.isPending}
                    title="Monitor all selected artists"
                  >
                    Monitor Selected
                  </button>
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={() => bulkUpdateMutation.mutate(false)}
                    disabled={bulkUpdateMutation.isPending}
                    title="Unmonitor all selected artists"
                  >
                    Unmonitor Selected
                  </button>
                  {isDirector && (
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => {
                      setBulkDeleteFiles(false)
                      setBulkDeleteDialogOpen(true)
                    }}
                    disabled={bulkDeleteMutation.isPending}
                    title="Delete all selected artists"
                  >
                    Delete Selected
                  </button>
                  )}
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={toggleSelectAll}
                    title={selectedIds.size === items.length ? 'Deselect all' : 'Select all on this page'}
                  >
                    {selectedIds.size === items.length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Content */}
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
            </div>
          ) : items.length === 0 ? (
            <div className="text-center py-12">
              <FiMusic className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <p className="text-gray-500 dark:text-gray-400">
                No {sortMode === 'artist' ? 'artists' : sortMode === 'album' ? 'albums' : 'tracks'} found
              </p>
            </div>
          ) : sortMode === 'track' ? (
            /* Tracks Table */
            <div className="card overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 dark:bg-[#161B22]">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-12"></th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Title</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Artist</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Album</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-20">Duration</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-24">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-28">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-[#0D1117] divide-y divide-gray-200 dark:divide-[#30363D]">
                    {tracks.map((track: TrackListItem) => (
                      <tr key={track.id} className="hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors">
                        <td className="px-4 py-2 text-sm text-gray-400">
                          {track.track_number}
                        </td>
                        <td className="px-4 py-2">
                          <div className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-xs">
                            {track.title}
                          </div>
                        </td>
                        <td className="px-4 py-2">
                          <button
                            className="text-sm text-[#FF1493] hover:text-[#d10f7a] truncate max-w-[150px] block"
                            onClick={(e) => { e.stopPropagation(); if (track.artist_id) navigate(`/disco-lounge/artists/${track.artist_id}`) }}
                          >
                            {track.artist_name}
                          </button>
                        </td>
                        <td className="px-4 py-2">
                          <button
                            className="text-sm text-[#FF1493] hover:text-[#d10f7a] truncate max-w-[200px] block"
                            onClick={(e) => { e.stopPropagation(); navigate(`/albums/${track.album_id}`) }}
                          >
                            {track.album_title}
                          </button>
                        </td>
                        <td className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400">
                          {formatDuration(track.duration_ms)}
                        </td>
                        <td className="px-4 py-2">
                          {track.has_file ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
                              <FiCheck className="w-3 h-3 mr-1" />
                              {track.file_format?.toUpperCase() || 'File'}
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600 dark:bg-[#0D1117] dark:text-gray-400">
                              <FiX className="w-3 h-3 mr-1" />
                              Missing
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2">
                          <div className="flex items-center space-x-2">
                            {track.has_file ? (
                              <>
                                <button
                                  className="text-[#FF1493] hover:text-[#d10f7a] transition-colors"
                                  title="Play this track from your library"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    player.play({
                                      id: track.id,
                                      title: track.title,
                                      track_number: track.track_number,
                                      duration_ms: track.duration_ms,
                                      has_file: track.has_file,
                                      file_path: track.file_path,
                                      artist_name: track.artist_name,
                                      artist_id: track.artist_id,
                                      album_id: track.album_id,
                                      album_title: track.album_title,
                                      album_cover_art_url: track.album_cover_art_url,
                                    })
                                  }}
                                >
                                  <FiPlay className="w-4 h-4" />
                                </button>
                                <button
                                  className="text-gray-500 dark:text-gray-400 hover:text-[#FF1493] transition-colors"
                                  title="Add to the play queue"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    player.addToQueue({
                                      id: track.id,
                                      title: track.title,
                                      track_number: track.track_number,
                                      duration_ms: track.duration_ms,
                                      has_file: track.has_file,
                                      file_path: track.file_path,
                                      artist_name: track.artist_name,
                                      artist_id: track.artist_id,
                                      album_id: track.album_id,
                                      album_title: track.album_title,
                                      album_cover_art_url: track.album_cover_art_url,
                                    })
                                  }}
                                >
                                  <FiPlus className="w-4 h-4" />
                                </button>
                              </>
                            ) : (
                              <button
                                className="text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300 transition-colors"
                                title="Listen to a 30-second preview from iTunes"
                                disabled={previewLoading.get(track.id)}
                                onClick={async (e) => {
                                  e.stopPropagation()
                                  setPreviewLoading(prev => new Map(prev).set(track.id, true))
                                  try {
                                    const result = await searchPreview(track.artist_name || '', track.title)
                                    if (result) {
                                      player.play({
                                        id: track.id,
                                        title: track.title,
                                        track_number: track.track_number,
                                        duration_ms: track.duration_ms,
                                        has_file: false,
                                        preview_url: result.preview_url,
                                        artist_name: track.artist_name,
                                        artist_id: track.artist_id,
                                        album_id: track.album_id,
                                        album_title: track.album_title,
                                        album_cover_art_url: track.album_cover_art_url,
                                      })
                                    } else {
                                      toast.error(`No preview found for "${track.title}"`)
                                    }
                                  } catch {
                                    toast.error('Failed to fetch preview')
                                  } finally {
                                    setPreviewLoading(prev => new Map(prev).set(track.id, false))
                                  }
                                }}
                              >
                                {previewLoading.get(track.id) ? (
                                  <FiLoader className="w-4 h-4 animate-spin" />
                                ) : (
                                  <FiHeadphones className="w-4 h-4" />
                                )}
                              </button>
                            )}
                            <AddToPlaylistDropdown trackId={track.id} />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            /* Artist/Album Grid */
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 2xl:grid-cols-10 gap-3">
              {sortMode === 'artist' && artists.map((artist: Artist) => renderArtistCard(artist))}
              {sortMode === 'album' && albums.map((album: Album) => renderAlbumCard(album))}
            </div>
          )}

          {/* Pagination */}
          <Pagination
            page={page}
            totalPages={Math.ceil(totalCount / itemsPerPage)}
            totalCount={totalCount}
            itemsPerPage={itemsPerPage}
            onPageChange={setPage}
            onItemsPerPageChange={(perPage) => { setItemsPerPage(perPage); setPage(1) }}
          />
        </>
      )}

      {activeTab === 'scanner' && (
        <LibraryScanner libraryType="music" />
      )}

      {activeTab === 'import' && (
        <div className="card p-6">
          <div className="text-center py-12">
            <FiDownload className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
              Import Music
            </h2>
            <p className="text-gray-600 dark:text-gray-400 mb-6">
              Import artists from MUSE libraries or add manually from MusicBrainz
            </p>
            <button
              className="btn btn-primary"
              onClick={() => setShowImportModal(true)}
            >
              <FiDownload className="w-4 h-4 mr-2" />
              Import from MUSE
            </button>
          </div>
        </div>
      )}

      {activeTab === 'unlinked' && (
        <div className="space-y-4">
          {/* Summary Bar */}
          {unlinkedSummary && unlinkedSummary.total > 0 && (
            <div className="card p-4">
              <div className="flex flex-wrap gap-3 items-center">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {unlinkedSummary.total.toLocaleString()} unlinked files:
                </span>
                {Object.entries(unlinkedSummary.by_reason).map(([reason, count]) => {
                  const badges: Record<string, { color: string; label: string }> = {
                    no_mbid: { color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300', label: 'No MBID' },
                    no_matching_track: { color: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300', label: 'No Matching Track' },
                    artist_not_in_db: { color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300', label: 'Artist Not Imported' },
                    album_not_in_db: { color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300', label: 'Album Not Imported' },
                  }
                  const badge = badges[reason] || { color: 'bg-gray-100 text-gray-800', label: reason }
                  return (
                    <button
                      key={reason}
                      onClick={() => {
                        setUnlinkedReasonFilter(unlinkedReasonFilter === reason ? '' : reason)
                        setUnlinkedPage(1)
                      }}
                      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium transition-all ${badge.color} ${
                        unlinkedReasonFilter === reason ? 'ring-2 ring-offset-1 ring-[#FF1493]' : 'hover:opacity-80'
                      }`}
                    >
                      {badge.label}: {(count as number).toLocaleString()}
                    </button>
                  )
                })}
                {unlinkedSummary.last_scan && (
                  <span className="text-xs text-gray-500 dark:text-gray-400 ml-auto">
                    Last scan: {new Date(unlinkedSummary.last_scan).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Controls */}
          <div className="card p-4">
            <div className="flex flex-wrap gap-3 items-center">
              <div className="relative flex-1 min-w-[200px] max-w-md">
                <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
                <input
                  type="text"
                  placeholder="Search files, artists, albums..."
                  className="input pl-10 w-full"
                  value={unlinkedSearch}
                  onChange={e => {
                    setUnlinkedSearch(e.target.value)
                    setUnlinkedPage(1)
                  }}
                />
              </div>
              <select
                className="input w-auto"
                value={unlinkedReasonFilter}
                onChange={e => {
                  setUnlinkedReasonFilter(e.target.value)
                  setUnlinkedPage(1)
                }}
              >
                <option value="">All Reasons</option>
                <option value="no_mbid">No MBID</option>
                <option value="no_matching_track">No Matching Track</option>
                <option value="artist_not_in_db">Artist Not Imported</option>
                <option value="album_not_in_db">Album Not Imported</option>
              </select>
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  refetchUnlinked()
                  queryClient.invalidateQueries({ queryKey: ['unlinked-summary'] })
                }}
                title="Refresh"
              >
                <FiRefreshCw className="w-4 h-4" />
              </button>
              <button
                className="btn btn-sm btn-secondary"
                onClick={async () => {
                  try {
                    const blob = await fileOrganizationApi.exportUnlinkedCsv(unlinkedReasonFilter || undefined)
                    const url = window.URL.createObjectURL(new Blob([blob]))
                    const a = document.createElement('a')
                    a.href = url
                    a.download = 'unlinked_files.csv'
                    a.click()
                    window.URL.revokeObjectURL(url)
                    toast.success('CSV exported')
                  } catch {
                    toast.error('Failed to export CSV')
                  }
                }}
                title="Export CSV"
              >
                <FiFileText className="w-4 h-4 mr-1" />
                Export CSV
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="card overflow-hidden">
            {unlinkedLoading ? (
              <div className="flex items-center justify-center py-12">
                <FiLoader className="w-6 h-6 animate-spin text-gray-400" />
              </div>
            ) : !unlinkedData?.items?.length ? (
              <div className="text-center py-12">
                <FiCheck className="w-12 h-12 text-green-400 mx-auto mb-3" />
                <p className="text-gray-600 dark:text-gray-400">
                  {unlinkedReasonFilter || unlinkedSearch
                    ? 'No unlinked files match your filters'
                    : 'All files are linked! Run "Link Files" from File Management to populate this list.'}
                </p>
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-[#161B22]/50">
                      <tr>
                        {[
                          { key: 'file', label: 'File' },
                          { key: 'artist', label: 'Artist' },
                          { key: 'album', label: 'Album' },
                          { key: 'title', label: 'Title' },
                          { key: 'mbid', label: 'MBID' },
                          { key: 'quality', label: 'Quality' },
                          { key: 'duration', label: 'Duration' },
                          { key: 'reason', label: 'Reason' },
                          { key: 'detected_at', label: 'Detected' },
                        ].map(col => (
                          <th
                            key={col.key}
                            className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 cursor-pointer select-none hover:text-gray-900 dark:hover:text-gray-200 group"
                            onClick={() => toggleUnlinkedSort(col.key)}
                          >
                            {col.label}
                            <SortIcon column={col.key} activeCol={unlinkedSortBy} activeDir={unlinkedSortDir} />
                          </th>
                        ))}
                        <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-[#30363D]">
                      {unlinkedData.items.map((file: UnlinkedFile) => {
                        const reasonBadges: Record<string, { color: string; label: string }> = {
                          no_mbid: { color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300', label: 'No MBID' },
                          no_matching_track: { color: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300', label: 'No Match' },
                          artist_not_in_db: { color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300', label: 'No Artist' },
                          album_not_in_db: { color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300', label: 'No Album' },
                        }
                        const badge = reasonBadges[file.reason] || { color: 'bg-gray-100 text-gray-800', label: file.reason }
                        const fileName = file.file_path.split('/').pop() || file.file_path
                        const isEditing = editingUnlinkedId === file.id
                        return (
                          <React.Fragment key={file.id}>
                          <tr className="hover:bg-gray-50 dark:hover:bg-[#1C2128]/30">
                            <td className="px-4 py-2.5 max-w-[250px]">
                              <span className="truncate block text-gray-900 dark:text-white font-medium text-xs" title={file.file_path}>
                                {fileName}
                              </span>
                              <span className="truncate block text-gray-500 dark:text-gray-500 text-[10px] font-mono" title={file.filesystem_path || file.file_path}>
                                {file.filesystem_path || file.file_path}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 max-w-[160px]">
                              {isEditing ? (
                                <input
                                  type="text"
                                  value={editFields.artist}
                                  onChange={(e) => setEditFields(f => ({ ...f, artist: e.target.value }))}
                                  className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white"
                                />
                              ) : (
                                <span className="truncate block">{file.artist || '-'}</span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 max-w-[160px]">
                              {isEditing ? (
                                <input
                                  type="text"
                                  value={editFields.album}
                                  onChange={(e) => setEditFields(f => ({ ...f, album: e.target.value }))}
                                  className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white"
                                />
                              ) : (
                                <span className="truncate block">{file.album || '-'}</span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 max-w-[160px]">
                              {isEditing ? (
                                <input
                                  type="text"
                                  value={editFields.title}
                                  onChange={(e) => setEditFields(f => ({ ...f, title: e.target.value }))}
                                  className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white"
                                />
                              ) : (
                                <span className="truncate block">{file.title || '-'}</span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 text-xs font-mono max-w-[120px]">
                              {file.musicbrainz_trackid ? (
                                <span className="truncate block" title={file.musicbrainz_trackid}>
                                  {file.musicbrainz_trackid.slice(0, 8)}...
                                </span>
                              ) : (
                                <span className="text-gray-400 dark:text-gray-600">-</span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-xs whitespace-nowrap">
                              {file.format ? (
                                <div className="flex flex-col gap-0.5">
                                  <span className="font-medium text-gray-700 dark:text-gray-300">{file.format.toUpperCase()}</span>
                                  <span className="text-gray-500 dark:text-gray-500">
                                    {file.bitrate_kbps ? `${file.bitrate_kbps}k` : ''}{file.bitrate_kbps && file.sample_rate_hz ? ' / ' : ''}{file.sample_rate_hz ? `${(file.sample_rate_hz / 1000).toFixed(1)}kHz` : ''}
                                  </span>
                                </div>
                              ) : (
                                <span className="text-gray-400 dark:text-gray-600">-</span>
                              )}
                            </td>
                            <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 text-xs whitespace-nowrap">
                              {file.duration_seconds ? (
                                `${Math.floor(file.duration_seconds / 60)}:${(file.duration_seconds % 60).toString().padStart(2, '0')}`
                              ) : '-'}
                            </td>
                            <td className="px-4 py-2.5">
                              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${badge.color}`} title={file.reason_detail || ''}>
                                {badge.label}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 text-xs whitespace-nowrap">
                              {file.detected_at ? new Date(file.detected_at).toLocaleDateString() : '-'}
                            </td>
                            <td className="px-4 py-2.5">
                              <div className="flex items-center gap-1">
                                {isEditing ? (
                                  <>
                                    <button
                                      onClick={() => {
                                        const changes: { artist?: string; album?: string; title?: string } = {}
                                        if (editFields.artist !== (file.artist || '')) changes.artist = editFields.artist
                                        if (editFields.album !== (file.album || '')) changes.album = editFields.album
                                        if (editFields.title !== (file.title || '')) changes.title = editFields.title
                                        if (Object.keys(changes).length > 0) {
                                          editMetadataMutation.mutate({ id: file.id, fields: changes })
                                        } else {
                                          setEditingUnlinkedId(null)
                                        }
                                      }}
                                      disabled={editMetadataMutation.isPending}
                                      className="p-1.5 rounded text-green-400 hover:bg-green-500/20 transition-colors"
                                      title="Save"
                                    >
                                      <FiSave size={14} />
                                    </button>
                                    <button
                                      onClick={() => setEditingUnlinkedId(null)}
                                      className="p-1.5 rounded text-gray-400 hover:bg-gray-600/50 transition-colors"
                                      title="Cancel"
                                    >
                                      <FiX size={14} />
                                    </button>
                                  </>
                                ) : (
                                  <>
                                    <button
                                      onClick={() => {
                                        const baseUrl = (import.meta as any).env?.VITE_API_URL || '/api/v1'
                                        const streamUrl = `${baseUrl}/file-organization/unlinked-files/${file.id}/stream`
                                        player.play({
                                          id: `unlinked-file-${file.id}`,
                                          title: file.title || fileName,
                                          has_file: false,
                                          preview_url: streamUrl,
                                          artist_name: file.artist || 'Unknown Artist',
                                          album_title: file.album || undefined,
                                        })
                                      }}
                                      className="p-1.5 rounded text-gray-400 hover:text-green-400 hover:bg-green-500/20 transition-colors"
                                      title="Play file"
                                    >
                                      <FiPlay size={14} />
                                    </button>
                                    {(file.artist || file.title) && (
                                      <button
                                        disabled={previewLoading.get(file.id)}
                                        onClick={async () => {
                                          setPreviewLoading(prev => new Map(prev).set(file.id, true))
                                          try {
                                            const result = await searchPreview(file.artist || '', file.title || file.album || '')
                                            if (result) {
                                              player.play({
                                                id: `unlinked-itunes-${file.id}`,
                                                title: result.itunes_track_name || file.title || 'Unknown',
                                                has_file: false,
                                                preview_url: result.preview_url,
                                                artist_name: result.itunes_artist_name || file.artist || 'Unknown',
                                                album_title: file.album || undefined,
                                                album_cover_art_url: result.artwork_url || null,
                                              })
                                            } else {
                                              toast.error(`No iTunes preview found for "${file.title || file.artist}"`)
                                            }
                                          } catch {
                                            toast.error('Failed to fetch preview')
                                          } finally {
                                            setPreviewLoading(prev => new Map(prev).set(file.id, false))
                                          }
                                        }}
                                        className="p-1.5 rounded text-gray-400 hover:text-amber-400 hover:bg-amber-500/20 transition-colors"
                                        title="30-second iTunes preview"
                                      >
                                        {previewLoading.get(file.id) ? (
                                          <FiLoader size={14} className="animate-spin" />
                                        ) : (
                                          <FiHeadphones size={14} />
                                        )}
                                      </button>
                                    )}
                                    <button
                                      onClick={() => {
                                        setEditingUnlinkedId(file.id)
                                        setEditFields({
                                          artist: file.artist || '',
                                          album: file.album || '',
                                          title: file.title || '',
                                        })
                                      }}
                                      className="p-1.5 rounded text-gray-400 hover:text-yellow-400 hover:bg-yellow-500/20 transition-colors"
                                      title="Edit metadata"
                                    >
                                      <FiEdit2 size={14} />
                                    </button>
                                    <button
                                      onClick={() => setLinkModalFile({
                                        id: file.id,
                                        file_path: file.file_path,
                                        artist: file.artist,
                                        album: file.album,
                                        title: file.title,
                                      })}
                                      className="p-1.5 rounded text-gray-400 hover:text-blue-400 hover:bg-blue-500/20 transition-colors"
                                      title="Link to track"
                                    >
                                      <FiLink size={14} />
                                    </button>
                                    <button
                                      onClick={async () => {
                                        const filename = file.file_path.split('/').pop() || file.file_path
                                        if (!window.confirm(`Delete "${filename}" from disk? This cannot be undone.`)) return
                                        try {
                                          await fileOrganizationApi.deleteUnlinkedFile(file.id)
                                          toast.success(`Deleted ${filename}`)
                                          queryClient.invalidateQueries({ queryKey: ['unlinked-files'] })
                                          queryClient.invalidateQueries({ queryKey: ['unlinked-summary'] })
                                        } catch (err: any) {
                                          toast.error(err?.response?.data?.detail || 'Failed to delete file')
                                        }
                                      }}
                                      className="p-1.5 rounded text-gray-400 hover:text-red-400 hover:bg-red-500/20 transition-colors"
                                      title="Delete file from disk"
                                    >
                                      <FiTrash2 size={14} />
                                    </button>
                                    <button
                                      disabled={acoustidLoading === file.id}
                                      onClick={async () => {
                                        if (acoustidResults?.fileId === file.id) {
                                          setAcoustidResults(null)
                                          return
                                        }
                                        setAcoustidLoading(file.id)
                                        try {
                                          const data = await fileOrganizationApi.acoustidLookup(file.id)
                                          if (data.matches.length > 0) {
                                            setAcoustidResults({ fileId: file.id, matches: data.matches })
                                          } else {
                                            toast.error('No AcoustID matches found for this file')
                                          }
                                        } catch (err: any) {
                                          toast.error(err?.response?.data?.detail || 'AcoustID lookup failed')
                                        } finally {
                                          setAcoustidLoading(null)
                                        }
                                      }}
                                      className={`p-1.5 rounded transition-colors ${
                                        acoustidResults?.fileId === file.id
                                          ? 'text-purple-400 bg-purple-500/20'
                                          : 'text-gray-400 hover:text-purple-400 hover:bg-purple-500/20'
                                      }`}
                                      title="AcoustID fingerprint lookup"
                                    >
                                      {acoustidLoading === file.id ? (
                                        <FiLoader size={14} className="animate-spin" />
                                      ) : (
                                        <FiCrosshair size={14} />
                                      )}
                                    </button>
                                  </>
                                )}
                              </div>
                            </td>
                          </tr>
                          {/* AcoustID results row */}
                          {acoustidResults?.fileId === file.id && (
                            <tr className="bg-purple-900/10 border-b border-purple-500/20">
                              <td colSpan={8} className="px-4 py-3">
                                <div className="flex items-center justify-between mb-2">
                                  <span className="text-xs font-medium text-purple-400">AcoustID Results ({acoustidResults.matches.length} matches)</span>
                                  <button onClick={() => setAcoustidResults(null)} className="text-gray-500 hover:text-white p-0.5"><FiX size={12} /></button>
                                </div>
                                <div className="space-y-1.5">
                                  {acoustidResults.matches.map((m: any, i: number) => (
                                    <div key={i} className="flex items-center gap-3 text-sm bg-gray-800/50 rounded-lg px-3 py-2">
                                      <span className={`text-xs font-mono w-12 shrink-0 ${
                                        m.score >= 0.9 ? 'text-green-400' : m.score >= 0.7 ? 'text-yellow-400' : 'text-orange-400'
                                      }`}>{Math.round(m.score * 100)}%</span>
                                      <div className="flex-1 min-w-0">
                                        <span className="text-white font-medium">{m.title || 'Unknown'}</span>
                                        {m.artist && <span className="text-gray-400"> — {m.artist}</span>}
                                        {m.album && <span className="text-gray-500 text-xs ml-2">({m.album}{m.album_type ? ` · ${m.album_type}` : ''})</span>}
                                      </div>
                                      <button
                                        onClick={() => {
                                          setEditingUnlinkedId(file.id)
                                          setEditFields({
                                            artist: m.artist || file.artist || '',
                                            album: m.album || file.album || '',
                                            title: m.title || file.title || '',
                                          })
                                          setAcoustidResults(null)
                                        }}
                                        className="text-xs px-2 py-1 rounded bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 transition-colors shrink-0"
                                        title="Apply this metadata"
                                      >
                                        Apply
                                      </button>
                                    </div>
                                  ))}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-800">
                  <Pagination
                    page={unlinkedPage}
                    totalPages={Math.ceil(unlinkedData.total / 50)}
                    totalCount={unlinkedData.total}
                    itemsPerPage={50}
                    onPageChange={setUnlinkedPage}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {activeTab === 'unorganized' && (
        <div className="space-y-4">
          {/* Summary Bar */}
          {unorganizedSummary && (
            <div className="card p-4">
              <div className="flex flex-wrap gap-4 items-center">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                  {(unorganizedSummary.total_unorganized || 0).toLocaleString()} unorganized
                </span>
                <span className="text-sm text-green-600 dark:text-green-400">
                  {(unorganizedSummary.total_organized || 0).toLocaleString()} organized
                </span>
                {unorganizedSummary.by_format && Object.entries(unorganizedSummary.by_format).map(([fmt, count]) => (
                  <button
                    key={fmt}
                    onClick={() => {
                      setUnorganizedFormatFilter(unorganizedFormatFilter === fmt ? '' : fmt)
                      setUnorganizedPage(1)
                    }}
                    className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium transition-all bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300 ${
                      unorganizedFormatFilter === fmt ? 'ring-2 ring-offset-1 ring-[#FF1493]' : 'hover:opacity-80'
                    }`}
                  >
                    {fmt}: {(count as number).toLocaleString()}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Controls */}
          <div className="card p-4">
            <div className="flex flex-wrap gap-3 items-center">
              <div className="relative flex-1 min-w-[200px] max-w-md">
                <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 w-4 h-4" />
                <input
                  type="text"
                  placeholder="Search files, artists, albums..."
                  className="input pl-10 w-full"
                  value={unorganizedSearch}
                  onChange={e => {
                    setUnorganizedSearch(e.target.value)
                    setUnorganizedPage(1)
                  }}
                />
              </div>
              {unorganizedFormatFilter && (
                <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300">
                  Format: {unorganizedFormatFilter}
                  <button onClick={() => { setUnorganizedFormatFilter(''); setUnorganizedPage(1) }} className="ml-1 hover:text-purple-600">
                    <FiX className="w-3 h-3" />
                  </button>
                </span>
              )}
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  refetchUnorganized()
                  queryClient.invalidateQueries({ queryKey: ['unorganized-summary'] })
                }}
                title="Refresh"
              >
                <FiRefreshCw className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="card overflow-hidden">
            {unorganizedLoading ? (
              <div className="flex items-center justify-center py-12">
                <FiLoader className="w-6 h-6 animate-spin text-gray-400" />
              </div>
            ) : !unorganizedData?.items?.length ? (
              <div className="text-center py-12">
                <FiCheck className="w-12 h-12 text-green-400 mx-auto mb-3" />
                <p className="text-gray-600 dark:text-gray-400">
                  {unorganizedSearch || unorganizedFormatFilter
                    ? 'No unorganized files match your filters'
                    : 'All files are organized!'}
                </p>
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 dark:bg-[#161B22]/50">
                      <tr>
                        {[
                          { key: 'file', label: 'File', width: '' },
                          { key: 'file_path', label: 'File Path', width: '' },
                          { key: 'artist', label: 'Artist', width: '' },
                          { key: 'album', label: 'Album', width: '' },
                          { key: 'title', label: 'Title', width: '' },
                          { key: 'track_number', label: '#', width: 'w-16' },
                          { key: 'year', label: 'Year', width: 'w-16' },
                          { key: 'format', label: 'Format', width: 'w-20' },
                          { key: 'mbid', label: 'MBID', width: 'w-20' },
                        ].map(col => (
                          <th
                            key={col.key}
                            className={`text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 cursor-pointer select-none hover:text-gray-900 dark:hover:text-gray-200 group ${col.width}`}
                            onClick={() => toggleUnorganizedSort(col.key)}
                          >
                            {col.label}
                            <SortIcon column={col.key} activeCol={unorganizedSortBy} activeDir={unorganizedSortDir} />
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-[#30363D]">
                      {unorganizedData.items.map((file: UnorganizedFile) => (
                        <tr key={file.id} className="hover:bg-gray-50 dark:hover:bg-[#1C2128]/30">
                          <td className="px-4 py-2.5 max-w-[200px]">
                            <span className="truncate block text-gray-900 dark:text-white font-medium text-xs" title={file.file_name}>
                              {file.file_name}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 max-w-[300px]">
                            <span className="truncate block text-gray-500 dark:text-gray-400 text-xs font-mono" title={file.file_path}>
                              {file.file_path}
                            </span>
                          </td>
                          <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 max-w-[150px]">
                            <span className="truncate block">{file.album_artist || file.artist || '-'}</span>
                          </td>
                          <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 max-w-[200px]">
                            <span className="truncate block">{file.album || '-'}</span>
                          </td>
                          <td className="px-4 py-2.5 text-gray-700 dark:text-gray-300 max-w-[200px]">
                            <span className="truncate block">{file.title || '-'}</span>
                          </td>
                          <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 text-xs">
                            {file.track_number || '-'}
                          </td>
                          <td className="px-4 py-2.5 text-gray-500 dark:text-gray-400 text-xs">
                            {file.year || '-'}
                          </td>
                          <td className="px-4 py-2.5">
                            {file.format && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700 dark:bg-[#0D1117] dark:text-gray-300">
                                {file.format.toUpperCase()}
                                {file.bitrate_kbps ? ` ${file.bitrate_kbps}k` : ''}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2.5">
                            {file.musicbrainz_trackid ? (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
                                <FiCheck className="w-3 h-3" />
                              </span>
                            ) : (
                              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">
                                <FiX className="w-3 h-3" />
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-800">
                  <Pagination
                    page={unorganizedPage}
                    totalPages={Math.ceil(unorganizedData.total / 50)}
                    totalCount={unorganizedData.total}
                    itemsPerPage={50}
                    onPageChange={setUnorganizedPage}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Bulk Delete Dialog */}
      {bulkDeleteDialogOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setBulkDeleteDialogOpen(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="p-6">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                Remove {selectedIds.size} Artist{selectedIds.size !== 1 ? 's' : ''}
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                This will delete all associated albums, tracks, and download history for the selected artists.
              </p>

              {(() => {
                const totalLinked = artists
                  .filter((a: Artist) => selectedIds.has(a.id))
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
                          <strong>Warning:</strong> This will permanently delete {totalLinked} music file{totalLinked !== 1 ? 's' : ''} from disk.
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
                onClick={() => bulkDeleteMutation.mutate({ artistIds: Array.from(selectedIds), deleteFiles: bulkDeleteFiles })}
                disabled={bulkDeleteMutation.isPending}
              >
                {bulkDeleteMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Removing...
                  </>
                ) : (
                  bulkDeleteFiles ? 'Remove & Delete Files' : `Remove ${selectedIds.size} Artist${selectedIds.size !== 1 ? 's' : ''}`
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Cleanup Orphaned Artists Dialog */}
      {cleanupOrphanedDialogOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setCleanupOrphanedDialogOpen(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="p-6">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                Cleanup Orphaned Artists
              </h3>
              {orphanedCount === 0 ? (
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                  No orphaned artists found. All unmonitored artists have linked files.
                </p>
              ) : (
                <>
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                    Found <strong>{orphanedCount}</strong> unmonitored artist{orphanedCount !== 1 ? 's' : ''} with no linked files.
                    These artists have no music files associated and are not being monitored.
                  </p>
                  <div className="mb-4 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                    <p className="text-sm text-amber-800 dark:text-amber-200">
                      This will delete these artists and all their associated albums, tracks, and download history.
                      No files on disk will be affected.
                    </p>
                  </div>
                </>
              )}
            </div>
            <div className="flex justify-end space-x-3 p-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-lg">
              <button className="btn btn-secondary" onClick={() => setCleanupOrphanedDialogOpen(false)}>
                {orphanedCount === 0 ? 'Close' : 'Cancel'}
              </button>
              {orphanedCount !== null && orphanedCount > 0 && (
                <button
                  className="btn btn-danger"
                  onClick={() => cleanupOrphanedMutation.mutate()}
                  disabled={cleanupOrphanedMutation.isPending}
                >
                  {cleanupOrphanedMutation.isPending ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                      Removing...
                    </>
                  ) : (
                    `Remove ${orphanedCount} Artist${orphanedCount !== 1 ? 's' : ''}`
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Import Artists Modal */}
      {showImportModal && (
        <ImportArtistsModal
          isOpen={showImportModal}
          onClose={() => setShowImportModal(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ['library-artists'] })
            setShowImportModal(false)
          }}
        />
      )}

      {/* Link File Modal */}
      <LinkFileModal
        isOpen={!!linkModalFile}
        onClose={() => setLinkModalFile(null)}
        onSuccess={() => {
          refetchUnlinked()
          queryClient.invalidateQueries({ queryKey: ['unlinked-summary'] })
        }}
        file={linkModalFile}
      />

      {/* Add Artist Modal */}
      {showAddArtistModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Add Artist</h2>
                <button
                  onClick={() => {
                    setShowAddArtistModal(false)
                    setMbSearchQuery('')
                    setMbResults([])
                  }}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                  title="Close"
                >
                  <FiX className="w-6 h-6" />
                </button>
              </div>

              <div className="space-y-4">
                <div className="flex space-x-2">
                  <input
                    type="text"
                    placeholder="Search MusicBrainz for artist..."
                    value={mbSearchQuery}
                    onChange={(e) => setMbSearchQuery(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && searchMusicBrainz()}
                    className="flex-1 px-4 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                  />
                  <button
                    onClick={searchMusicBrainz}
                    disabled={mbSearching}
                    className="btn btn-primary"
                  >
                    {mbSearching ? <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div> : 'Search'}
                  </button>
                </div>

                {mbResults.length > 0 && (
                  <div className="space-y-2 max-h-96 overflow-y-auto">
                    {mbResults.map((result: any) => (
                      <div
                        key={result.id}
                        className="p-4 border border-gray-200 dark:border-[#30363D] rounded-lg hover:bg-gray-50 dark:hover:bg-[#1C2128] flex items-center justify-between"
                      >
                        <div>
                          <h3 className="font-medium text-gray-900 dark:text-white">{result.name}</h3>
                          {result.disambiguation && (
                            <p className="text-sm text-gray-500 dark:text-gray-400">{result.disambiguation}</p>
                          )}
                          <p className="text-xs text-gray-400">{result.country} • {result.type}</p>
                        </div>
                        <button
                          onClick={() => addArtistMutation.mutate(result.id)}
                          disabled={addArtistMutation.isPending}
                          className="btn btn-sm btn-primary"
                        >
                          Add
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Library
