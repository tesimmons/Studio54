import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { artistsApi, albumsApi, tracksApi, fileOrganizationApi, jobsApi, searchApi, settingsApi, playlistsApi, authFetch } from '../api/client'
import CoverArtUploader from '../components/CoverArtUploader'
import type { Job, TrackListItem, ExternalTopTrack } from '../api/client'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import type { PlayerTrack } from '../contexts/PlayerContext'
import { searchPreview } from '../api/itunes'
import {
  FiArrowLeft,
  FiRefreshCw,
  FiSearch,
  FiCheck,
  FiX,
  FiDisc,
  FiCalendar,
  FiMusic,
  FiFolder,
  FiDownload,
  FiAlertCircle,
  FiCheckCircle,
  FiLoader,
  FiTrash2,
  FiPlay,
  FiPlus,
  FiHeadphones,
  FiDatabase,
  FiMoreVertical
} from 'react-icons/fi'
import StarRating from '../components/StarRating'
import AddToPlaylistDropdown from '../components/AddToPlaylistDropdown'
import { S54 } from '../assets/graphics'

interface Album {
  id: string
  title: string
  musicbrainz_id: string
  release_date: string | null
  album_type: string
  secondary_types: string | null
  status: string
  monitored: boolean
  track_count: number
  linked_files_count: number
  cover_art_url: string | null
}

interface ArtistWithAlbums {
  id: string
  name: string
  musicbrainz_id: string
  is_monitored: boolean
  quality_profile_id: string | null
  root_folder_path: string | null
  overview: string | null
  album_count: number
  single_count: number
  track_count: number
  linked_files_count: number
  rating_override: number | null
  average_rating: number | null
  rated_track_count: number
  added_at: string
  last_sync_at: string | null
  image_url: string | null
  albums: Album[]
}

function ArtistDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')

  // Album type filter state
  const ALL_ALBUM_TYPES = ['Album', 'EP', 'Single', 'Compilation', 'Live', 'Soundtrack', 'Audiobook']
  const [enabledTypes, setEnabledTypes] = useState<Set<string>>(new Set(ALL_ALBUM_TYPES))
  const [filterDropdownOpen, setFilterDropdownOpen] = useState(false)
  const [showAllAlbums, setShowAllAlbums] = useState(false)

  // Fetch default album type filters from settings
  useEffect(() => {
    settingsApi.getAlbumTypeFilters().then(res => {
      setEnabledTypes(new Set(res.enabled_types))
    }).catch(() => {
      // Use all types as default on error
    })
  }, [])

  // Toast notification state
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null)

  // Active job tracking for this artist
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 5000)
  }, [])

  // Mobile actions menu
  const [actionsMenuOpen, setActionsMenuOpen] = useState(false)

  // Delete dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteFiles, setDeleteFiles] = useState(false)

  // Organize dialog state
  const [organizeDialogOpen, setOrganizeDialogOpen] = useState(false)
  const [organizeOptions, setOrganizeOptions] = useState({
    dry_run: true,
    create_metadata_files: true,
    only_with_mbid: true,
    only_unorganized: true,
  })

  // MBDB search modal state
  const [mbdbModalOpen, setMbdbModalOpen] = useState(false)
  const [mbdbMatches, setMbdbMatches] = useState<Array<{
    id: string; name: string; disambiguation: string; type: string | null; score: number
  }>>([])
  const [mbdbLoading, setMbdbLoading] = useState(false)
  const [mbdbSettingId, setMbdbSettingId] = useState<string | null>(null)

  const player = usePlayer()
  const { isDjOrAbove } = useAuth()
  const [previewLoading, setPreviewLoading] = useState<Record<string, boolean>>({})
  const [searchingTrackId, setSearchingTrackId] = useState<string | null>(null)

  // Fetch artist details
  const { data: artist, isLoading, refetch } = useQuery({
    queryKey: ['artist', id],
    queryFn: async (): Promise<ArtistWithAlbums> => {
      const data = await artistsApi.get(id!)
      return data as ArtistWithAlbums
    },
    enabled: !!id,
  })

  // Fetch external top tracks (Last.fm)
  const { data: externalTopTracks } = useQuery({
    queryKey: ['artist-top-tracks-external', id],
    queryFn: () => artistsApi.getTopTracksExternal(id!, 5),
    enabled: !!id,
  })

  // Fetch local top tracks (most played / newest)
  const { data: localTopTracks } = useQuery({
    queryKey: ['artist-top-tracks-local', id],
    queryFn: () => tracksApi.getTopTracks(id!, 5),
    enabled: !!id,
  })

  // Poll for active jobs for this artist
  const { data: activeJobs } = useQuery({
    queryKey: ['artist-jobs', id],
    queryFn: async (): Promise<Job[]> => {
      const result = await jobsApi.list({ entity_id: id!, status: 'running', limit: 5 })
      return result.jobs || []
    },
    enabled: !!id,
    refetchInterval: (query) => {
      // Poll every 3s if there are running jobs, otherwise every 30s
      const jobs = query.state.data
      return jobs && jobs.length > 0 ? 3000 : 30000
    },
  })

  // Track when a specific job completes
  const { data: trackedJob } = useQuery({
    queryKey: ['tracked-job', activeJobId],
    queryFn: async (): Promise<Job> => {
      return jobsApi.get(activeJobId!)
    },
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const job = query.state.data
      if (job && (job.status === 'completed' || job.status === 'failed')) {
        return false // Stop polling when done
      }
      return 2000
    },
  })

  // React to tracked job completion
  useEffect(() => {
    if (!trackedJob) return
    if (trackedJob.status === 'completed') {
      showToast(`Job completed: ${trackedJob.current_step || trackedJob.job_type}`, 'success')
      setActiveJobId(null)
      queryClient.invalidateQueries({ queryKey: ['artist', id] })
      queryClient.invalidateQueries({ queryKey: ['artist-jobs', id] })
    } else if (trackedJob.status === 'failed') {
      showToast(`Job failed: ${trackedJob.error_message || 'Unknown error'}`, 'error')
      setActiveJobId(null)
      queryClient.invalidateQueries({ queryKey: ['artist-jobs', id] })
    }
  }, [trackedJob?.status])

  // Update artist monitoring
  const updateMonitoringMutation = useMutation({
    mutationFn: async (isMonitored: boolean) => {
      const response = await authFetch(`/api/v1/artists/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_monitored: isMonitored })
      })
      if (!response.ok) throw new Error('Failed to update monitoring')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artist', id] })
      queryClient.invalidateQueries({ queryKey: ['artists'] })
    }
  })

  // Sync albums mutation
  const syncAlbumsMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch(`/api/v1/artists/${id}/sync`, {
        method: 'POST'
      })
      if (!response.ok) throw new Error('Failed to sync albums')
      return response.json()
    },
    onSuccess: (data) => {
      showToast(`Album sync started for ${data.artist_name || 'artist'}. Tracking progress...`, 'info')
      if (data.task_id) {
        // Find the job by celery task ID - poll jobs list to find it
        const findJob = async () => {
          const result = await jobsApi.list({ entity_id: id!, status: 'running', limit: 5 })
          const job = result.jobs?.find((j: Job) => j.celery_task_id === data.task_id)
          if (job) {
            setActiveJobId(job.id)
          }
        }
        // Small delay to let the job be created in DB
        setTimeout(findJob, 1000)
      }
      queryClient.invalidateQueries({ queryKey: ['artist-jobs', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to sync albums: ${error.message}`, 'error')
    }
  })

  // Search missing albums mutation
  const searchMissingMutation = useMutation({
    mutationFn: async () => {
      return searchApi.searchMissing(id!)
    },
    onSuccess: (data) => {
      showToast(data.message || 'Search for missing albums started', 'info')
    },
    onError: (error: Error) => {
      showToast(`Failed to search missing: ${error.message}`, 'error')
    }
  })

  // Refresh metadata mutation
  const refreshMetadataMutation = useMutation({
    mutationFn: async () => {
      return artistsApi.refreshMetadata(id!)
    },
    onSuccess: (data) => {
      showToast(`Metadata refresh started for ${data.artist_name}`, 'info')
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['artist', id] })
      }, 3000)
    },
    onError: (error: Error) => {
      showToast(`Failed to refresh metadata: ${error.message}`, 'error')
    }
  })

  // Organize artist files mutation
  const organizeFilesMutation = useMutation({
    mutationFn: async () => {
      return fileOrganizationApi.organizeArtist(id!, organizeOptions)
    },
    onSuccess: (data) => {
      setOrganizeDialogOpen(false)
      const mode = organizeOptions.dry_run ? 'dry run' : 'organization'
      showToast(`File ${mode} job started (Job: ${data.job_id?.slice(0, 8)}...)`, 'info')
    },
    onError: (error: Error) => {
      showToast(`Failed to start organization job: ${error.message}`, 'error')
    }
  })

  // Delete artist mutation
  const deleteArtistMutation = useMutation({
    mutationFn: async (shouldDeleteFiles: boolean) => {
      const response = await authFetch(`/api/v1/artists/${id}?delete_files=${shouldDeleteFiles}`, {
        method: 'DELETE'
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Failed to delete artist' }))
        throw new Error(error.detail || 'Failed to delete artist')
      }
      return response.json()
    },
    onSuccess: () => {
      setDeleteDialogOpen(false)
      queryClient.invalidateQueries({ queryKey: ['artists'] })
      navigate('/disco-lounge')
    },
    onError: (error: Error) => {
      showToast(`Failed to delete artist: ${error.message}`, 'error')
    }
  })

  // Monitor all albums and start downloading
  const monitorAllAndDownloadMutation = useMutation({
    mutationFn: async () => {
      // Step 1: Monitor all albums
      await albumsApi.monitorByType(id!, null, true)
      // Step 2: Trigger search for missing (downloads)
      const result = await searchApi.searchMissing(id!)
      return result
    },
    onSuccess: (data) => {
      showToast(data.message || 'All albums monitored and search started', 'info')
      queryClient.invalidateQueries({ queryKey: ['artist', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to monitor and download: ${error.message}`, 'error')
    }
  })

  // Search local MBDB for artist
  const handleSearchMbdb = async () => {
    if (!id) return
    setMbdbLoading(true)
    setMbdbMatches([])
    setMbdbModalOpen(true)
    try {
      const result = await artistsApi.resolveMbid(id)
      setMbdbMatches(result.matches || [])
    } catch (error: any) {
      showToast(`MBDB search failed: ${error?.response?.data?.detail || error.message}`, 'error')
    } finally {
      setMbdbLoading(false)
    }
  }

  // Set MBID from MBDB search results
  const handleSelectMbid = async (mbid: string) => {
    if (!id) return
    setMbdbSettingId(mbid)
    try {
      const result = await artistsApi.setMusicbrainzId(id, mbid, true)
      showToast(`MBID set for ${result.artist_name}. Album sync started.`, 'success')
      setMbdbModalOpen(false)
      queryClient.invalidateQueries({ queryKey: ['artist', id] })
      queryClient.invalidateQueries({ queryKey: ['artist-jobs', id] })
    } catch (error: any) {
      showToast(`Failed to set MBID: ${error?.response?.data?.detail || error.message}`, 'error')
    } finally {
      setMbdbSettingId(null)
    }
  }

  // Per-track search mutation
  const trackSearchMutation = useMutation({
    mutationFn: async (trackId: string) => {
      return tracksApi.search(trackId)
    },
    onSuccess: (data) => {
      setSearchingTrackId(null)
      if (data.success) {
        showToast(data.message || 'Track search started', 'info')
      } else {
        showToast('Track search failed', 'error')
      }
    },
    onError: (error: Error) => {
      setSearchingTrackId(null)
      showToast(`Track search failed: ${error.message}`, 'error')
    }
  })

  // Toggle album monitoring
  const toggleAlbumMonitoringMutation = useMutation({
    mutationFn: async ({ albumId, monitored }: { albumId: string; monitored: boolean }) => {
      const response = await authFetch(`/api/v1/albums/${albumId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ monitored })
      })
      if (!response.ok) throw new Error('Failed to update album')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artist', id] })
    }
  })

  const artistRatingMutation = useMutation({
    mutationFn: async (rating: number | null) => {
      return artistsApi.setRating(id!, rating)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['artist', id] })
    },
  })

  const createPlaylistMutation = useMutation({
    mutationFn: async () => {
      if (!artist) throw new Error('Artist not loaded')

      // Fetch tracks from all albums that have linked files
      const albumsWithFiles = artist.albums.filter(a => (a.linked_files_count || 0) > 0)
      const allTrackIds: string[] = []
      for (const album of albumsWithFiles) {
        const albumDetail = await albumsApi.get(album.id)
        const playableIds = albumDetail.tracks
          .filter((t: any) => t.has_file)
          .map((t: any) => t.id)
        allTrackIds.push(...playableIds)
      }

      if (allTrackIds.length === 0) throw new Error('No playable tracks found')

      // Find unique name (handle duplicates)
      let name = artist.name
      const existing = await playlistsApi.list(1000, 0)
      const existingNames = new Set(existing.items.map(p => p.name))
      if (existingNames.has(name)) {
        let suffix = 2
        while (existingNames.has(`${artist.name} (${suffix})`)) suffix++
        name = `${artist.name} (${suffix})`
      }

      const playlist = await playlistsApi.create({ name })
      await playlistsApi.addTracksBulk(playlist.id, allTrackIds)
      return playlist
    },
    onSuccess: (playlist) => {
      showToast(`Created playlist "${playlist.name}"`, 'success')
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      navigate(`/playlists/${playlist.id}`)
    },
    onError: (error: any) => {
      showToast(error?.response?.data?.detail || error.message || 'Failed to create playlist', 'error')
    },
  })

  // Search tracks when query has 2+ characters
  const { data: trackSearchResults } = useQuery({
    queryKey: ['artist-track-search', id, searchQuery],
    queryFn: () => tracksApi.list({ search_query: searchQuery, artist_id: id!, limit: 20 }),
    enabled: searchQuery.length >= 2 && !!id,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
      </div>
    )
  }

  if (!artist) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen">
        <p className="text-gray-500 dark:text-gray-400 mb-4">Artist not found</p>
        <button className="btn btn-primary" onClick={() => navigate('/disco-lounge')}>
          Back to Artists
        </button>
      </div>
    )
  }

  // Helper to get secondary types as array
  const getSecondaryTypes = (album: Album): string[] =>
    album.secondary_types ? album.secondary_types.split(',').map(s => s.trim()).filter(Boolean) : []

  // Filter albums by search query and enabled types
  const filteredAlbums = (artist.albums || []).filter(album => {
    if (!showAllAlbums && (album.linked_files_count || 0) === 0) return false
    if (!album.title.toLowerCase().includes(searchQuery.toLowerCase())) return false
    const secondaryTypes = getSecondaryTypes(album)
    // Album matches if its primary type is enabled OR any secondary type is enabled
    const primaryMatch = enabledTypes.has(album.album_type || 'Album')
    const secondaryMatch = secondaryTypes.some(st => enabledTypes.has(st))
    return primaryMatch || secondaryMatch
  })

  // Categorize into sections
  const albumsSection = filteredAlbums.filter(album => {
    const st = getSecondaryTypes(album)
    return album.album_type === 'Album' && !st.some(s => ['Compilation', 'Live', 'Soundtrack', 'Audiobook'].includes(s))
  })
  const epsSection = filteredAlbums.filter(album => album.album_type === 'EP')
  const singlesSection = filteredAlbums.filter(album => album.album_type === 'Single')
  const compilationsSection = filteredAlbums.filter(album => getSecondaryTypes(album).includes('Compilation'))
  const liveSection = filteredAlbums.filter(album => getSecondaryTypes(album).includes('Live'))
  const soundtracksSection = filteredAlbums.filter(album => getSecondaryTypes(album).includes('Soundtrack'))
  const audiobooksSection = filteredAlbums.filter(album => getSecondaryTypes(album).includes('Audiobook'))

  const trackToPlayerTrack = (track: TrackListItem): PlayerTrack => ({
    id: track.id,
    title: track.title,
    track_number: track.track_number,
    duration_ms: track.duration_ms,
    has_file: track.has_file,
    file_path: track.file_path,
    artist_name: track.artist_name,
    artist_id: track.artist_id || id!,
    album_id: track.album_id,
    album_title: track.album_title,
    album_cover_art_url: track.album_cover_art_url,
  })

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'downloaded':
        return 'badge-success'
      case 'wanted':
        return 'badge-warning'
      case 'missing':
        return 'badge-danger'
      default:
        return 'badge-secondary'
    }
  }

  // Helper to render album/single grid
  const renderReleaseGrid = (releases: Album[], _imageScale: 'album' | 'single' = 'album') => {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8 gap-4">
        {releases.map((album) => (
          <div
            key={album.id}
            className="card p-0 hover:shadow-lg transition-shadow cursor-pointer group"
            onClick={() => navigate(`/disco-lounge/albums/${album.id}`)}
          >
            {/* Album Cover - square aspect ratio, centered, no crop */}
            <div className="relative aspect-square bg-gradient-to-br from-gray-600 to-gray-800 flex items-center justify-center">
              <img
                src={album.cover_art_url || S54.defaultAlbumArt}
                alt={album.title}
                className="w-full h-full object-contain"
              />

            {/* Status Badge */}
            <div className="absolute top-2 right-2">
              <span className={`badge ${getStatusColor(album.status)}`}>
                {album.status}
              </span>
            </div>

            {/* Monitoring Badge */}
            {album.monitored && (
              <div className="absolute top-2 left-2">
                <span className="badge badge-primary">
                  <FiCheck className="w-3 h-3" />
                </span>
              </div>
            )}
          </div>

          {/* Album Info */}
          <div className="p-3">
            <h3 className="font-semibold text-gray-900 dark:text-white text-sm line-clamp-2 group-hover:text-[#FF1493] transition-colors min-h-[2.5rem]">
              {album.title}
            </h3>

            <div className="mt-2 space-y-1 text-xs text-gray-600 dark:text-gray-400">
              {album.release_date && (
                <div className="flex items-center space-x-1">
                  <FiCalendar className="w-3 h-3" />
                  <span>{new Date(album.release_date).getFullYear()}</span>
                </div>
              )}

              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-1">
                  <FiMusic className="w-3 h-3" />
                  <span>{album.linked_files_count || 0} / {album.track_count || 0} linked</span>
                </div>
                <span className="text-xs text-gray-500 dark:text-gray-500">
                  {album.secondary_types ? album.secondary_types.split(',').join(', ') : album.album_type}
                </span>
              </div>
              {(album.track_count || 0) > 0 && (
                <div className="w-full bg-gray-200 dark:bg-[#0D1117] rounded-full h-1.5 mt-1">
                  <div
                    className={`h-1.5 rounded-full transition-all ${
                      (album.linked_files_count || 0) >= (album.track_count || 0)
                        ? 'bg-green-500'
                        : (album.linked_files_count || 0) > 0
                          ? 'bg-amber-500'
                          : 'bg-gray-400 dark:bg-gray-600'
                    }`}
                    style={{ width: `${Math.min(100, Math.round(((album.linked_files_count || 0) / (album.track_count || 1)) * 100))}%` }}
                  />
                </div>
              )}
            </div>

            {/* Monitor Toggle Button */}
            {isDjOrAbove && (
            <button
              className={`mt-3 w-full py-1.5 px-3 rounded text-xs font-medium transition-colors ${
                album.monitored
                  ? 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                  : 'bg-[#FF1493] text-white hover:bg-[#d10f7a]'
              }`}
              onClick={(e) => {
                e.stopPropagation()
                toggleAlbumMonitoringMutation.mutate({
                  albumId: album.id,
                  monitored: !album.monitored
                })
              }}
              disabled={toggleAlbumMonitoringMutation.isPending}
              title={album.monitored ? 'Unmonitor this album' : 'Monitor this album'}
            >
              {album.monitored ? (
                <div className="flex items-center justify-center">
                  <FiX className="w-3 h-3 mr-1" />
                  Unmonitor
                </div>
              ) : (
                <div className="flex items-center justify-center">
                  <FiCheck className="w-3 h-3 mr-1" />
                  Monitor
                </div>
              )}
            </button>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col sm:flex-row items-start gap-4 sm:gap-6 min-w-0">
          {/* Artist Image */}
          <CoverArtUploader
            entityType="artist"
            entityId={id!}
            currentUrl={artist.image_url}
            onSuccess={() => queryClient.invalidateQueries({ queryKey: ['artist', id] })}
            uploadFn={artistsApi.uploadCoverArt}
            uploadFromUrlFn={artistsApi.uploadCoverArtFromUrl}
            fallback={
              <div className="w-full h-full bg-gradient-to-br from-[#FF1493] to-[#FF8C00] flex items-center justify-center">
                <FiMusic className="w-24 h-24 text-white/30" />
              </div>
            }
            alt={artist.name}
            className="w-28 h-28 sm:w-48 sm:h-48 rounded-lg overflow-hidden flex-shrink-0"
          />

          {/* Artist Info */}
          <div className="flex-1">
            <div className="flex items-center space-x-3 mb-2">
              <button
                className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                onClick={() => window.history.length > 1 ? navigate(-1) : navigate('/disco-lounge')}
                title="Back to artists"
              >
                <FiArrowLeft className="w-5 h-5" />
              </button>
              <h1 className="text-xl sm:text-4xl font-bold text-gray-900 dark:text-white">{artist.name}</h1>
            </div>

            {/* Stats */}
            <div className="flex flex-wrap items-center gap-3 sm:gap-6 mt-4 text-sm">
              <div className="flex items-center space-x-2">
                <FiDisc className="w-4 h-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">
                  {artist.album_count || 0} Albums
                </span>
              </div>
              <div className="flex items-center space-x-2">
                <FiDisc className="w-4 h-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">
                  {artist.single_count || 0} Singles
                </span>
              </div>
              <div className="flex items-center space-x-2">
                <FiMusic className="w-4 h-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">
                  {artist.track_count || 0} Tracks
                </span>
              </div>
              <div className="flex items-center space-x-2">
                <StarRating
                  rating={artist.rating_override ?? artist.average_rating}
                  size="md"
                  onChange={(rating) => artistRatingMutation.mutate(rating)}
                />
                {artist.rating_override != null && artist.average_rating != null && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    (avg: {artist.average_rating})
                  </span>
                )}
                {artist.rating_override == null && artist.average_rating == null && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    Not rated
                  </span>
                )}
              </div>
              {artist.added_at && (
                <div className="flex items-center space-x-2">
                  <FiCalendar className="w-4 h-4 text-gray-400" />
                  <span className="text-gray-600 dark:text-gray-400">
                    Added {new Date(artist.added_at).toLocaleDateString()}
                  </span>
                </div>
              )}
            </div>

            {/* Biography */}
            {artist.overview && (
              <div className="mt-4 text-sm text-gray-600 dark:text-gray-400 max-w-3xl">
                <p className="line-clamp-4">{artist.overview}</p>
              </div>
            )}

            {/* Monitoring Toggle */}
            <div className="mt-4 flex items-center space-x-4">
              {isDjOrAbove ? (
              <button
                className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                  artist.is_monitored
                    ? 'bg-success-600 text-white hover:bg-success-700'
                    : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                }`}
                onClick={() => updateMonitoringMutation.mutate(!artist.is_monitored)}
                disabled={updateMonitoringMutation.isPending}
                title={artist.is_monitored ? 'Unmonitor this artist' : 'Monitor this artist'}
              >
                {updateMonitoringMutation.isPending ? (
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                ) : (
                  <div className="flex items-center">
                    {artist.is_monitored ? (
                      <>
                        <FiCheck className="w-4 h-4 mr-2" />
                        Monitored
                      </>
                    ) : (
                      <>
                        <FiX className="w-4 h-4 mr-2" />
                        Not Monitored
                      </>
                    )}
                  </div>
                )}
              </button>
              ) : (
              <span className={`px-4 py-2 rounded-lg font-medium ${
                artist.is_monitored
                  ? 'bg-success-600/20 text-success-700 dark:text-success-400'
                  : 'bg-gray-200 dark:bg-[#0D1117] text-gray-500 dark:text-gray-400'
              }`}>
                {artist.is_monitored ? 'Monitored' : 'Not Monitored'}
              </span>
              )}

              {artist.last_sync_at && (
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  Last synced: {new Date(artist.last_sync_at).toLocaleString()}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Action Buttons - Desktop */}
        <div className="hidden lg:flex flex-wrap gap-2">
          {isDjOrAbove && (
          <button
            className="btn btn-primary"
            onClick={() => monitorAllAndDownloadMutation.mutate()}
            disabled={monitorAllAndDownloadMutation.isPending}
            title="Monitor all albums and search for missing downloads"
          >
            {monitorAllAndDownloadMutation.isPending ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                Starting...
              </>
            ) : (
              <>
                <FiDownload className="w-4 h-4 mr-2" />
                Monitor All &amp; Download
              </>
            )}
          </button>
          )}
          {isDjOrAbove && (
          <button
            className="btn btn-secondary"
            onClick={() => setOrganizeDialogOpen(true)}
            title="Organize artist files into standardized folder structure"
          >
            <FiFolder className="w-4 h-4 mr-2" />
            Organize Files
          </button>
          )}
          {isDjOrAbove && (
          <button
            className="btn btn-secondary"
            onClick={() => syncAlbumsMutation.mutate()}
            disabled={syncAlbumsMutation.isPending}
            title="Sync album list from MusicBrainz"
          >
            {syncAlbumsMutation.isPending ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                Syncing...
              </>
            ) : (
              <>
                <FiRefreshCw className="w-4 h-4 mr-2" />
                Sync Albums
              </>
            )}
          </button>
          )}
          {isDjOrAbove && (
          <button
            className="btn btn-secondary"
            onClick={() => searchMissingMutation.mutate()}
            disabled={searchMissingMutation.isPending}
            title="Search Usenet for missing albums"
          >
            {searchMissingMutation.isPending ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                Searching...
              </>
            ) : (
              <>
                <FiDownload className="w-4 h-4 mr-2" />
                Search Missing
              </>
            )}
          </button>
          )}
          {isDjOrAbove && (
          <button
            className="btn btn-secondary"
            onClick={() => refreshMetadataMutation.mutate()}
            disabled={refreshMetadataMutation.isPending}
            title="Refresh artist images and metadata from MusicBrainz"
          >
            {refreshMetadataMutation.isPending ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                Refreshing...
              </>
            ) : (
              <>
                <FiRefreshCw className="w-4 h-4 mr-2" />
                Refresh Metadata
              </>
            )}
          </button>
          )}
          {isDjOrAbove && (
          <button
            className="btn btn-secondary"
            onClick={handleSearchMbdb}
            disabled={mbdbLoading}
            title="Search local MusicBrainz database for this artist's MBID"
          >
            {mbdbLoading ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                Searching...
              </>
            ) : (
              <>
                <FiDatabase className="w-4 h-4 mr-2" />
                Search MBDB
              </>
            )}
          </button>
          )}
          {(artist.linked_files_count || 0) > 0 && (
          <button
            className="btn btn-secondary"
            onClick={() => createPlaylistMutation.mutate()}
            disabled={createPlaylistMutation.isPending}
            title="Create a playlist from all playable tracks"
          >
            {createPlaylistMutation.isPending ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                Creating...
              </>
            ) : (
              <>
                <FiPlus className="w-4 h-4 mr-2" />
                Create Playlist
              </>
            )}
          </button>
          )}
          <button className="btn btn-secondary" onClick={() => refetch()} title="Refresh artist data">
            <FiRefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </button>
          {isDjOrAbove && (
          <button
            className="btn btn-danger"
            onClick={() => {
              setDeleteFiles(false)
              setDeleteDialogOpen(true)
            }}
            title="Remove this artist and all associated albums"
          >
            <FiTrash2 className="w-4 h-4 mr-2" />
            Remove Artist
          </button>
          )}
        </div>

        {/* Action Menu - Mobile/Tablet */}
        <div className="relative lg:hidden flex-shrink-0">
          <button
            onClick={() => setActionsMenuOpen(!actionsMenuOpen)}
            className="p-2 rounded-lg bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D] transition-colors"
            title="Actions"
          >
            <FiMoreVertical className="w-5 h-5" />
          </button>
          {actionsMenuOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setActionsMenuOpen(false)} />
              <div className="absolute right-0 top-full mt-1 w-56 bg-white dark:bg-[#161B22] rounded-lg shadow-xl border border-gray-200 dark:border-[#30363D] z-40 py-1">
                {isDjOrAbove && (
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                  onClick={() => { monitorAllAndDownloadMutation.mutate(); setActionsMenuOpen(false) }}
                  disabled={monitorAllAndDownloadMutation.isPending}
                >
                  <FiDownload className="w-4 h-4 mr-3 text-[#FF1493]" />
                  Monitor All & Download
                </button>
                )}
                {isDjOrAbove && (
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                  onClick={() => { setOrganizeDialogOpen(true); setActionsMenuOpen(false) }}
                >
                  <FiFolder className="w-4 h-4 mr-3 text-gray-500" />
                  Organize Files
                </button>
                )}
                {isDjOrAbove && (
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                  onClick={() => { syncAlbumsMutation.mutate(); setActionsMenuOpen(false) }}
                  disabled={syncAlbumsMutation.isPending}
                >
                  <FiRefreshCw className="w-4 h-4 mr-3 text-gray-500" />
                  Sync Albums
                </button>
                )}
                {isDjOrAbove && (
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                  onClick={() => { searchMissingMutation.mutate(); setActionsMenuOpen(false) }}
                  disabled={searchMissingMutation.isPending}
                >
                  <FiDownload className="w-4 h-4 mr-3 text-gray-500" />
                  Search Missing
                </button>
                )}
                {isDjOrAbove && (
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                  onClick={() => { refreshMetadataMutation.mutate(); setActionsMenuOpen(false) }}
                  disabled={refreshMetadataMutation.isPending}
                >
                  <FiRefreshCw className="w-4 h-4 mr-3 text-gray-500" />
                  Refresh Metadata
                </button>
                )}
                {isDjOrAbove && (
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                  onClick={() => { handleSearchMbdb(); setActionsMenuOpen(false) }}
                  disabled={mbdbLoading}
                >
                  <FiDatabase className="w-4 h-4 mr-3 text-gray-500" />
                  Search MBDB
                </button>
                )}
                {(artist.linked_files_count || 0) > 0 && (
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                  onClick={() => { createPlaylistMutation.mutate(); setActionsMenuOpen(false) }}
                  disabled={createPlaylistMutation.isPending}
                >
                  <FiPlus className="w-4 h-4 mr-3 text-gray-500" />
                  Create Playlist
                </button>
                )}
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                  onClick={() => { refetch(); setActionsMenuOpen(false) }}
                >
                  <FiRefreshCw className="w-4 h-4 mr-3 text-gray-500" />
                  Refresh
                </button>
                {isDjOrAbove && (
                <>
                <div className="border-t border-gray-200 dark:border-[#30363D] my-1" />
                <button
                  className="w-full flex items-center px-4 py-2.5 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                  onClick={() => { setDeleteFiles(false); setDeleteDialogOpen(true); setActionsMenuOpen(false) }}
                >
                  <FiTrash2 className="w-4 h-4 mr-3" />
                  Remove Artist
                </button>
                </>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Active Jobs Banner */}
      {activeJobs && activeJobs.length > 0 && (
        <div className="space-y-2">
          {activeJobs.map((job) => (
            <div
              key={job.id}
              className="flex items-center justify-between bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg px-4 py-3"
            >
              <div className="flex items-center space-x-3">
                <FiLoader className="w-4 h-4 text-blue-600 dark:text-blue-400 animate-spin" />
                <div>
                  <span className="text-sm font-medium text-blue-800 dark:text-blue-200">
                    {job.job_type === 'artist_sync' ? 'Album Sync' : job.job_type.replace(/_/g, ' ')}
                  </span>
                  {job.current_step && (
                    <span className="text-xs text-blue-600 dark:text-blue-400 ml-2">
                      - {job.current_step}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center space-x-3">
                {job.items_total && job.items_total > 0 ? (
                  <span className="text-xs text-blue-600 dark:text-blue-400">
                    {job.items_processed || 0}/{job.items_total} items
                  </span>
                ) : null}
                <div className="w-32 bg-blue-200 dark:bg-blue-800 rounded-full h-2">
                  <div
                    className="bg-blue-600 dark:bg-blue-400 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${Math.min(100, job.progress_percent || 0)}%` }}
                  />
                </div>
                <span className="text-xs font-medium text-blue-800 dark:text-blue-200 w-10 text-right">
                  {Math.round(job.progress_percent || 0)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Toast Notification */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 flex items-center space-x-2 px-4 py-3 rounded-lg shadow-lg transition-all duration-300 ${
            toast.type === 'success'
              ? 'bg-green-600 text-white'
              : toast.type === 'error'
              ? 'bg-red-600 text-white'
              : 'bg-blue-600 text-white'
          }`}
        >
          {toast.type === 'success' ? (
            <FiCheckCircle className="w-4 h-4 flex-shrink-0" />
          ) : toast.type === 'error' ? (
            <FiAlertCircle className="w-4 h-4 flex-shrink-0" />
          ) : (
            <FiLoader className="w-4 h-4 flex-shrink-0 animate-spin" />
          )}
          <span className="text-sm">{toast.message}</span>
          <button
            onClick={() => setToast(null)}
            className="ml-2 text-white/80 hover:text-white"
          >
            <FiX className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Top Hits Section - Two Column Layout */}
      {((externalTopTracks?.tracks?.length ?? 0) > 0 || (localTopTracks?.tracks?.length ?? 0) > 0) && (
        <div className="space-y-3">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Top Hits</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Left Column: Popular (Last.fm) */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                  Popular
                </h3>
                <span className="text-xs text-gray-400">Last.fm</span>
              </div>
              <div className="card p-0 overflow-hidden">
                {externalTopTracks?.error === 'not_configured' ? (
                  <div className="px-4 py-8 text-center">
                    <p className="text-sm text-gray-400">Configure <code className="text-xs bg-gray-100 dark:bg-[#0D1117] px-1.5 py-0.5 rounded">LASTFM_API_KEY</code> in settings for popular tracks</p>
                  </div>
                ) : (externalTopTracks?.tracks?.length ?? 0) === 0 ? (
                  <div className="px-4 py-8 text-center">
                    <p className="text-sm text-gray-400">No popular tracks found</p>
                  </div>
                ) : (
                  externalTopTracks!.tracks.map((track: ExternalTopTrack, index: number) => (
                    <div
                      key={`ext-${index}`}
                      className="flex items-center px-3 py-2 hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors"
                    >
                      <span className="w-6 text-xs text-gray-400 text-right mr-3 flex-shrink-0">
                        {index + 1}
                      </span>
                      <div className="w-8 h-8 rounded overflow-hidden flex-shrink-0 mr-2.5">
                        <img src={track.album_cover_art_url || S54.defaultAlbumArt} alt="" className="w-full h-full object-cover" />
                      </div>
                      <div className="flex-1 min-w-0 mr-2">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{track.track_name}</p>
                        <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
                          {track.album_title || 'Unknown Album'}
                        </p>
                      </div>
                      <span className="w-12 text-xs text-gray-400 text-right mr-3 flex-shrink-0">
                        {track.listeners >= 1_000_000
                          ? `${(track.listeners / 1_000_000).toFixed(1)}M`
                          : track.listeners >= 1_000
                          ? `${(track.listeners / 1_000).toFixed(0)}K`
                          : track.listeners.toLocaleString()
                        }
                      </span>
                      <div className="flex items-center space-x-1 flex-shrink-0 w-24 justify-end">
                        {/* Play from library */}
                        {track.has_file && track.local_track_id && (
                          <>
                            <button
                              className="p-1 rounded-full text-[#FF1493] hover:bg-[#FF1493]/10 dark:hover:bg-[#FF1493]/15 transition-colors"
                              onClick={() => player.play({
                                id: track.local_track_id!,
                                title: track.track_name,
                                track_number: index + 1,
                                duration_ms: track.duration_ms,
                                has_file: true,
                                file_path: track.file_path,
                                artist_name: track.artist_name,
                                artist_id: track.artist_id,
                                album_id: track.album_id || '',
                                album_title: track.album_title || '',
                                album_cover_art_url: track.album_cover_art_url,
                              })}
                              title="Play"
                            >
                              <FiPlay className="w-3.5 h-3.5" />
                            </button>
                            <button
                              className="p-1 rounded-full text-gray-500 hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors"
                              onClick={() => player.addToQueue({
                                id: track.local_track_id!,
                                title: track.track_name,
                                track_number: index + 1,
                                duration_ms: track.duration_ms,
                                has_file: true,
                                file_path: track.file_path,
                                artist_name: track.artist_name,
                                artist_id: track.artist_id,
                                album_id: track.album_id || '',
                                album_title: track.album_title || '',
                                album_cover_art_url: track.album_cover_art_url,
                              })}
                              title="Add to queue"
                            >
                              <FiPlus className="w-3.5 h-3.5" />
                            </button>
                          </>
                        )}
                        {/* Download - search Usenet for tracks with local_track_id but no file */}
                        {isDjOrAbove && track.local_track_id && !track.has_file && (
                          <button
                            className="p-1 rounded-full text-[#FF1493] hover:bg-[#FF1493]/10 dark:hover:bg-[#FF1493]/15 transition-colors"
                            title="Search Usenet for this track"
                            disabled={searchingTrackId === track.local_track_id}
                            onClick={() => {
                              setSearchingTrackId(track.local_track_id!)
                              trackSearchMutation.mutate(track.local_track_id!)
                            }}
                          >
                            {searchingTrackId === track.local_track_id ? (
                              <FiLoader className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <FiDownload className="w-3.5 h-3.5" />
                            )}
                          </button>
                        )}
                        {/* 30-sec preview from iTunes */}
                        <button
                          className="p-1 rounded-full text-amber-600 hover:bg-amber-100 dark:hover:bg-amber-900/30 transition-colors"
                          title="Listen to a 30-second preview"
                          disabled={previewLoading[`ext-${index}`]}
                          onClick={async () => {
                            const key = `ext-${index}`
                            setPreviewLoading(prev => ({ ...prev, [key]: true }))
                            try {
                              const result = await searchPreview(track.artist_name, track.track_name)
                              if (result) {
                                player.play({
                                  id: track.local_track_id || `preview-${index}`,
                                  title: track.track_name,
                                  track_number: index + 1,
                                  duration_ms: track.duration_ms,
                                  has_file: false,
                                  preview_url: result.preview_url,
                                  artist_name: track.artist_name,
                                  artist_id: track.artist_id,
                                  album_id: track.album_id || '',
                                  album_title: track.album_title || '',
                                  album_cover_art_url: track.album_cover_art_url,
                                })
                              } else {
                                showToast(`No preview found for "${track.track_name}"`, 'error')
                              }
                            } catch {
                              showToast('Failed to fetch preview', 'error')
                            } finally {
                              setPreviewLoading(prev => ({ ...prev, [key]: false }))
                            }
                          }}
                        >
                          {previewLoading[`ext-${index}`] ? (
                            <FiLoader className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <FiHeadphones className="w-3.5 h-3.5" />
                          )}
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Right Column: Most Played / Newest */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wider">
                  {localTopTracks?.source === 'play_count' ? 'Most Played' : 'Newest'}
                </h3>
                {(localTopTracks?.tracks?.length ?? 0) > 0 && (
                  <button
                    className="text-xs text-[#FF1493] hover:text-[#d10f7a] dark:text-[#ff4da6]"
                    onClick={() => {
                      const tracks = localTopTracks!.tracks.map(trackToPlayerTrack)
                      player.playAlbum(tracks, 0)
                    }}
                    title="Play all"
                  >
                    <FiPlay className="w-3 h-3 inline mr-1" />
                    Play All
                  </button>
                )}
              </div>
              <div className="card p-0 overflow-hidden">
                {(localTopTracks?.tracks?.length ?? 0) === 0 ? (
                  <div className="px-4 py-8 text-center">
                    <p className="text-sm text-gray-400">No tracks with files available</p>
                  </div>
                ) : (
                  localTopTracks!.tracks.map((track, index) => (
                    <div
                      key={track.id}
                      className="flex items-center px-3 py-2 hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors"
                    >
                      <span className="w-6 text-xs text-gray-400 text-right mr-3 flex-shrink-0">
                        {index + 1}
                      </span>
                      <div className="w-8 h-8 rounded overflow-hidden flex-shrink-0 mr-2.5">
                        <img src={track.album_cover_art_url || S54.defaultAlbumArt} alt="" className="w-full h-full object-cover" />
                      </div>
                      <div className="flex-1 min-w-0 mr-2">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{track.title}</p>
                        <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{track.album_title}</p>
                      </div>
                      <span className="w-16 text-xs text-gray-400 text-right mr-3 flex-shrink-0 truncate">
                        {localTopTracks?.source === 'play_count'
                          ? `${track.play_count} plays`
                          : ''
                        }
                      </span>
                      <div className="flex items-center space-x-1 flex-shrink-0 justify-end">
                        <button
                          className="p-1 rounded-full text-[#FF1493] hover:bg-[#FF1493]/10 dark:hover:bg-[#FF1493]/15 transition-colors"
                          onClick={() => player.play(trackToPlayerTrack(track))}
                          title="Play"
                        >
                          <FiPlay className="w-3.5 h-3.5" />
                        </button>
                        <button
                          className="p-1 rounded-full text-gray-500 hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors"
                          onClick={() => player.addToQueue(trackToPlayerTrack(track))}
                          title="Add to queue"
                        >
                          <FiPlus className="w-3.5 h-3.5" />
                        </button>
                        <AddToPlaylistDropdown trackId={track.id} />
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Search Bar + Filter Dropdown */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
        {/* Show All Albums Toggle */}
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showAllAlbums}
            onChange={(e) => setShowAllAlbums(e.target.checked)}
            className="checkbox"
          />
          <span className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">Show all albums</span>
        </label>

        {/* Album Type Filter */}
        <div className="relative">
          <button
            onClick={() => setFilterDropdownOpen(!filterDropdownOpen)}
            className="btn btn-secondary text-sm flex items-center gap-2"
          >
            <FiDisc className="w-4 h-4" />
            Filter Types
            {enabledTypes.size < ALL_ALBUM_TYPES.length && (
              <span className="bg-[#FF1493] text-white text-xs rounded-full px-1.5 py-0.5 ml-1">
                {enabledTypes.size}
              </span>
            )}
          </button>
          {filterDropdownOpen && (
            <div className="absolute z-50 mt-1 w-56 bg-white dark:bg-[#161B22] border border-gray-200 dark:border-[#30363D] rounded-lg shadow-lg p-2">
              {ALL_ALBUM_TYPES.map(type => (
                <label key={type} className="flex items-center px-2 py-1.5 hover:bg-gray-100 dark:hover:bg-[#1C2128] rounded cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enabledTypes.has(type)}
                    onChange={() => {
                      const next = new Set(enabledTypes)
                      if (next.has(type)) next.delete(type)
                      else next.add(type)
                      setEnabledTypes(next)
                    }}
                    className="checkbox mr-2"
                  />
                  <span className="text-sm text-gray-900 dark:text-white">{type}</span>
                </label>
              ))}
              <div className="border-t border-gray-200 dark:border-[#30363D] mt-1 pt-1 flex gap-2 px-2">
                <button
                  onClick={() => setEnabledTypes(new Set(ALL_ALBUM_TYPES))}
                  className="text-xs text-[#FF1493] hover:text-[#d10f7a]"
                >All</button>
                <button
                  onClick={() => setEnabledTypes(new Set())}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >None</button>
              </div>
            </div>
          )}
        </div>
        </div>

        <div className="w-80">
          <div className="relative">
            <FiSearch className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
            <input
              type="text"
              placeholder="Search albums, singles & tracks..."
              className="input pl-10 pr-8 w-full"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-white p-0.5"
              >
                <FiX className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Albums Section */}
      {albumsSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Albums ({albumsSection.length})
          </h2>
          {renderReleaseGrid(albumsSection, 'album')}
        </div>
      )}

      {/* EPs Section */}
      {epsSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            EPs ({epsSection.length})
          </h2>
          {renderReleaseGrid(epsSection, 'album')}
        </div>
      )}

      {/* Singles Section */}
      {singlesSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Singles ({singlesSection.length})
          </h2>
          {renderReleaseGrid(singlesSection, 'single')}
        </div>
      )}

      {/* Compilations Section */}
      {compilationsSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Compilations ({compilationsSection.length})
          </h2>
          {renderReleaseGrid(compilationsSection, 'album')}
        </div>
      )}

      {/* Live Albums Section */}
      {liveSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Live Albums ({liveSection.length})
          </h2>
          {renderReleaseGrid(liveSection, 'album')}
        </div>
      )}

      {/* Soundtracks Section */}
      {soundtracksSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Soundtracks ({soundtracksSection.length})
          </h2>
          {renderReleaseGrid(soundtracksSection, 'album')}
        </div>
      )}

      {/* Audiobooks Section */}
      {audiobooksSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Audiobooks ({audiobooksSection.length})
          </h2>
          {renderReleaseGrid(audiobooksSection, 'album')}
        </div>
      )}

      {/* Matching Tracks Section */}
      {searchQuery.length >= 2 && (trackSearchResults?.tracks?.length ?? 0) > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Matching Tracks ({trackSearchResults!.tracks.length})
          </h2>
          <div className="card overflow-hidden">
            <div className="divide-y divide-gray-100 dark:divide-[#30363D]">
              {trackSearchResults!.tracks.map((track) => {
                const isCurrentTrack = player.state.currentTrack?.id === track.id
                const durationStr = track.duration_ms
                  ? `${Math.floor(track.duration_ms / 60000)}:${((track.duration_ms % 60000) / 1000).toFixed(0).padStart(2, '0')}`
                  : '-'
                return (
                  <div
                    key={track.id}
                    className={`flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-[#1C2128]/30 transition-colors ${
                      isCurrentTrack ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                    }`}
                  >
                    {/* Album art */}
                    <div
                      className="w-10 h-10 rounded overflow-hidden shrink-0 cursor-pointer"
                      onClick={() => navigate(`/disco-lounge/albums/${track.album_id}`)}
                    >
                      <img src={track.album_cover_art_url || S54.defaultAlbumArt} alt="" className="w-full h-full object-cover" />
                    </div>

                    {/* Play button */}
                    <button
                      onClick={() => {
                        if (track.has_file) {
                          player.play(trackToPlayerTrack(track))
                        }
                      }}
                      disabled={!track.has_file}
                      className={`p-1.5 rounded-full shrink-0 transition-colors ${
                        track.has_file
                          ? 'text-green-500 hover:bg-green-500/20'
                          : 'text-gray-300 dark:text-gray-600 cursor-not-allowed'
                      }`}
                      title={track.has_file ? 'Play' : 'No file available'}
                    >
                      <FiPlay size={14} />
                    </button>

                    {/* Track info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`font-medium truncate ${
                          isCurrentTrack ? 'text-blue-600 dark:text-blue-400' : 'text-gray-900 dark:text-white'
                        }`}>
                          {track.title}
                        </span>
                        {track.has_file && (
                          <FiCheck className="text-green-500 shrink-0" size={12} />
                        )}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 truncate">
                        <span
                          className="hover:text-blue-400 cursor-pointer"
                          onClick={() => navigate(`/disco-lounge/albums/${track.album_id}`)}
                        >
                          {track.album_title}
                        </span>
                        <span className="mx-1">·</span>
                        Track {track.track_number}
                      </div>
                    </div>

                    {/* Duration */}
                    <span className="text-sm text-gray-500 dark:text-gray-400 shrink-0 tabular-nums">
                      {durationStr}
                    </span>

                    {/* iTunes preview */}
                    <button
                      className="p-1.5 rounded-full text-amber-500 hover:bg-amber-500/20 transition-colors shrink-0"
                      title="30-second iTunes preview"
                      onClick={async () => {
                        const result = await searchPreview(artist.name, track.title)
                        if (result) {
                          player.play({
                            id: track.id,
                            title: track.title,
                            track_number: track.track_number,
                            duration_ms: track.duration_ms,
                            has_file: false,
                            preview_url: result.preview_url,
                            artist_name: artist.name,
                            artist_id: artist.id,
                            album_id: track.album_id,
                            album_title: track.album_title,
                            album_cover_art_url: track.album_cover_art_url,
                          })
                        } else {
                          showToast(`No iTunes preview found for "${track.title}"`, 'error')
                        }
                      }}
                    >
                      <FiHeadphones size={14} />
                    </button>

                    {/* Rating */}
                    <div className="shrink-0">
                      <StarRating
                        rating={track.average_rating}
                        size="sm"
                        onChange={async (r) => {
                          await tracksApi.setRating(track.id, r)
                          queryClient.invalidateQueries({ queryKey: ['artist-track-search', id, searchQuery] })
                        }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* Empty State */}
      {filteredAlbums.length === 0 && (!trackSearchResults?.tracks?.length || searchQuery.length < 2) && (
        <div className="card p-12 text-center">
          <p className="text-gray-500 dark:text-gray-400">
            {searchQuery ? 'No albums, singles, or tracks match your search' : 'No albums or singles found for this artist'}
          </p>
          {!artist.albums?.length && (
            <button
              className="btn btn-primary mt-4"
              onClick={() => syncAlbumsMutation.mutate()}
              disabled={syncAlbumsMutation.isPending}
            >
              {syncAlbumsMutation.isPending ? 'Syncing...' : 'Sync Albums from MusicBrainz'}
            </button>
          )}
        </div>
      )}

      {/* Delete Artist Confirmation Dialog */}
      {deleteDialogOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="p-6">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                Remove Artist
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Are you sure you want to remove <strong>{artist.name}</strong>? This will delete all associated albums, tracks, and download history.
              </p>

              {(artist.linked_files_count || 0) > 0 && (
                <div className="mb-4 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                  <p className="text-sm text-amber-800 dark:text-amber-200 mb-3">
                    This artist has <strong>{artist.linked_files_count}</strong> linked file{artist.linked_files_count !== 1 ? 's' : ''} on disk.
                  </p>
                  <label className="flex items-center space-x-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={deleteFiles}
                      onChange={(e) => setDeleteFiles(e.target.checked)}
                      className="rounded border-gray-300 text-red-600 focus:ring-red-500"
                    />
                    <span className="text-sm font-medium text-amber-900 dark:text-amber-100">
                      Also delete music files from disk
                    </span>
                  </label>
                </div>
              )}

              {deleteFiles && (
                <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                  <p className="text-sm text-red-800 dark:text-red-200">
                    <strong>Warning:</strong> This will permanently delete {artist.linked_files_count} music file{(artist.linked_files_count || 0) !== 1 ? 's' : ''} from disk. This cannot be undone.
                  </p>
                </div>
              )}
            </div>

            <div className="flex justify-end space-x-3 p-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-lg">
              <button
                className="btn btn-secondary"
                onClick={() => setDeleteDialogOpen(false)}
              >
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() => deleteArtistMutation.mutate(deleteFiles)}
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
                    {deleteFiles ? 'Remove & Delete Files' : 'Remove Artist'}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Organize Files Dialog */}
      {organizeDialogOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="p-6">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                Organize Artist Files
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Organize files for <strong>{artist.name}</strong> into standardized folder structure with MBID-based naming.
              </p>

              <div className="space-y-4">
                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={organizeOptions.dry_run}
                    onChange={(e) => setOrganizeOptions(prev => ({ ...prev, dry_run: e.target.checked }))}
                    className="rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
                  />
                  <div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">Dry Run</span>
                    <p className="text-xs text-gray-500">Preview changes without moving files</p>
                  </div>
                </label>

                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={organizeOptions.create_metadata_files}
                    onChange={(e) => setOrganizeOptions(prev => ({ ...prev, create_metadata_files: e.target.checked }))}
                    className="rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
                  />
                  <div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">Create Metadata Files</span>
                    <p className="text-xs text-gray-500">Create .mbid.json files in album directories</p>
                  </div>
                </label>

                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={organizeOptions.only_with_mbid}
                    onChange={(e) => setOrganizeOptions(prev => ({ ...prev, only_with_mbid: e.target.checked }))}
                    className="rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
                  />
                  <div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">Only With MBID</span>
                    <p className="text-xs text-gray-500">Skip files without MusicBrainz IDs</p>
                  </div>
                </label>

                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={organizeOptions.only_unorganized}
                    onChange={(e) => setOrganizeOptions(prev => ({ ...prev, only_unorganized: e.target.checked }))}
                    className="rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
                  />
                  <div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">Only Unorganized</span>
                    <p className="text-xs text-gray-500">Skip files already in correct location</p>
                  </div>
                </label>
              </div>

              {!organizeOptions.dry_run && (
                <div className="mt-4 p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg">
                  <p className="text-sm text-yellow-800 dark:text-yellow-200">
                    <strong>Warning:</strong> This will move files to new locations. Make sure you have backups.
                  </p>
                </div>
              )}
            </div>

            <div className="flex justify-end space-x-3 p-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-lg">
              <button
                className="btn btn-secondary"
                onClick={() => setOrganizeDialogOpen(false)}
                title="Cancel file organization"
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={() => organizeFilesMutation.mutate()}
                disabled={organizeFilesMutation.isPending}
                title={organizeOptions.dry_run ? 'Preview what changes would be made' : 'Move files to organized folder structure'}
              >
                {organizeFilesMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Starting...
                  </>
                ) : (
                  organizeOptions.dry_run ? 'Preview Changes' : 'Organize Files'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* MBDB Search Modal */}
      {mbdbModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setMbdbModalOpen(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-[#30363D]">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Search Local MBDB</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Matches for "{artist?.name}" {artist?.musicbrainz_id && <span className="text-xs">(current: {artist.musicbrainz_id.slice(0, 8)}...)</span>}
                </p>
              </div>
              <button onClick={() => setMbdbModalOpen(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <FiX className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 overflow-y-auto flex-1">
              {mbdbLoading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493] mr-3"></div>
                  <span className="text-gray-600 dark:text-gray-400">Searching local database...</span>
                </div>
              ) : mbdbMatches.length === 0 ? (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  <FiAlertCircle className="w-8 h-8 mx-auto mb-2" />
                  <p>No matches found in local MusicBrainz database.</p>
                  <p className="text-sm mt-1">Try the remote API or check the artist name spelling.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {mbdbMatches.map((match) => (
                    <div
                      key={match.id}
                      className="flex items-center justify-between p-3 border border-gray-200 dark:border-[#30363D] rounded-lg hover:bg-gray-50 dark:hover:bg-[#1C2128]"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center space-x-2">
                          <span className="font-medium text-gray-900 dark:text-white truncate">{match.name}</span>
                          {match.type && (
                            <span className="text-xs px-2 py-0.5 bg-gray-100 dark:bg-[#0D1117] text-gray-600 dark:text-gray-400 rounded">
                              {match.type}
                            </span>
                          )}
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                            match.score >= 95 ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' :
                            match.score >= 80 ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400' :
                            'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                          }`}>
                            {match.score}%
                          </span>
                        </div>
                        {match.disambiguation && (
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{match.disambiguation}</p>
                        )}
                        <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 font-mono">{match.id}</p>
                      </div>
                      <button
                        className="btn btn-primary btn-sm ml-3 flex-shrink-0"
                        onClick={() => handleSelectMbid(match.id)}
                        disabled={mbdbSettingId === match.id}
                      >
                        {mbdbSettingId === match.id ? (
                          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        ) : (
                          <>
                            <FiCheck className="w-4 h-4 mr-1" />
                            Select
                          </>
                        )}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex justify-end p-4 border-t border-gray-200 dark:border-[#30363D]">
              <button className="btn btn-secondary" onClick={() => setMbdbModalOpen(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ArtistDetail
