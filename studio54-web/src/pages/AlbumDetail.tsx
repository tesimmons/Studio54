import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast, { Toaster } from 'react-hot-toast'
import { albumsApi, tracksApi, fileOrganizationApi, jobsApi, playlistsApi, authFetch } from '../api/client'
import CoverArtUploader from '../components/CoverArtUploader'
import type { Job } from '../api/client'
import { usePlayer, type PlayerTrack } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import FileBrowserModal from '../components/FileBrowserModal'
import AddToPlaylistDropdown from '../components/AddToPlaylistDropdown'
import StarRating from '../components/StarRating'
import {
  FiArrowLeft,
  FiRefreshCw,
  FiCheck,
  FiX,
  FiDisc,
  FiCalendar,
  FiMusic,
  FiPlay,
  FiPlus,
  FiSearch,
  FiClock,
  FiFolder,
  FiEdit2,
  FiSave,
  FiLoader,
  FiHeadphones,
  FiAlignLeft,
  FiDownload,
  FiTrash2,
  FiMoreVertical,
  FiChevronDown,
  FiChevronUp
} from 'react-icons/fi'
import { searchPreview } from '../api/itunes'
import { S54 } from '../assets/graphics'

interface Track {
  id: string
  title: string
  track_number: number
  disc_number: number
  duration_ms: number | null
  has_file: boolean
  file_path: string | null
  musicbrainz_id: string | null
  muse_file_id?: string
  artist_name?: string
  rating: number | null
  average_rating: number | null
  user_rating: number | null
  rating_count?: number
}

interface AlbumWithTracks {
  id: string
  title: string
  artist_id: string
  artist_name: string
  musicbrainz_id: string | null
  release_mbid: string | null
  release_date: string | null
  album_type: string | null
  status: string
  monitored: boolean
  cover_art_url: string | null
  custom_folder_path: string | null
  track_count: number
  muse_library_id: string | null
  muse_verified: boolean
  added_at: string | null
  updated_at: string | null
  tracks: Track[]
  downloads?: any[]
}

function AlbumDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const player = usePlayer()
  const { isDjOrAbove } = useAuth()
  const [isEditingFolderPath, setIsEditingFolderPath] = useState(false)
  const [folderPath, setFolderPath] = useState('')
  const [showFileBrowser, setShowFileBrowser] = useState(false)
  const [scanResults, setScanResults] = useState<any>(null)
  const [showScanResults, setShowScanResults] = useState(false)
  const [previewLoading, setPreviewLoading] = useState<Map<string, boolean>>(new Map())
  const [searchingTrackId, setSearchingTrackId] = useState<string | null>(null)
  const [showMobileActions, setShowMobileActions] = useState(false)
  const [expandedTrackId, setExpandedTrackId] = useState<string | null>(null)

  // Active job tracking for this album
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  // Poll for active jobs for this album
  const { data: activeJobs } = useQuery({
    queryKey: ['album-jobs', id],
    queryFn: async (): Promise<Job[]> => {
      const result = await jobsApi.list({ entity_id: id!, status: 'running', limit: 5 })
      return result.jobs || []
    },
    enabled: !!id,
    refetchInterval: (query) => {
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
        return false
      }
      return 2000
    },
  })

  // React to tracked job completion
  useEffect(() => {
    if (!trackedJob) return
    if (trackedJob.status === 'completed') {
      toast.success(`Job completed: ${trackedJob.current_step || trackedJob.job_type}`)
      setActiveJobId(null)
      queryClient.invalidateQueries({ queryKey: ['album', id] })
      queryClient.invalidateQueries({ queryKey: ['album-jobs', id] })
    } else if (trackedJob.status === 'failed') {
      toast.error(`Job failed: ${trackedJob.error_message || 'Unknown error'}`)
      setActiveJobId(null)
      queryClient.invalidateQueries({ queryKey: ['album-jobs', id] })
    }
  }, [trackedJob?.status])

  // Organize dialog state
  const [organizeDialogOpen, setOrganizeDialogOpen] = useState(false)
  const [organizeOptions, setOrganizeOptions] = useState({
    dry_run: true,
    create_metadata_files: true,
    only_with_mbid: true,
    only_unorganized: true,
  })

  // Fetch album details with tracks - auto-refresh when downloading/searching
  const { data: album, isLoading, refetch } = useQuery({
    queryKey: ['album', id],
    queryFn: async (): Promise<AlbumWithTracks> => {
      const response = await authFetch(`/api/v1/albums/${id}`)
      if (!response.ok) throw new Error('Failed to fetch album')
      return response.json()
    },
    enabled: !!id,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return false
      // Auto-refresh every 5s while downloading/searching, or if there are active downloads
      const hasActiveDownloads = data.downloads?.some(
        (dl: any) => ['queued', 'downloading', 'post_processing', 'importing',
                       'QUEUED', 'DOWNLOADING', 'POST_PROCESSING', 'IMPORTING'].includes(dl.status)
      )
      if (data.status === 'downloading' || data.status === 'searching' || hasActiveDownloads) {
        return 5000
      }
      return false
    },
  })

  // Update album monitoring
  const updateMonitoringMutation = useMutation({
    mutationFn: async (monitored: boolean) => {
      return albumsApi.update(id!, { monitored })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['album', id] })
      queryClient.invalidateQueries({ queryKey: ['artist'] })
    }
  })

  // Manual search mutation
  const manualSearchMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch(`/api/v1/albums/${id}/search`, {
        method: 'POST'
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to search for album')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['album', id] })
      if (data.already_exists) {
        toast.success(`Album already exists in MUSE library (${data.file_count} files)`)
      } else if (data.success === false) {
        toast.error(data.error || data.message || 'Search failed')
      } else {
        toast.success(data.message || 'Album search started - tracking progress...')
        if (data.task_id) {
          const findJob = async () => {
            const result = await jobsApi.list({ entity_id: id!, status: 'running', limit: 5 })
            const job = result.jobs?.find((j: Job) => j.celery_task_id === data.task_id)
            if (job) {
              setActiveJobId(job.id)
            }
          }
          setTimeout(findJob, 1000)
        }
        queryClient.invalidateQueries({ queryKey: ['album-jobs', id] })
      }
    },
    onError: (error: Error) => {
      toast.error(`Search failed: ${error.message}`)
    }
  })

  // Update custom folder path mutation
  const updateFolderPathMutation = useMutation({
    mutationFn: async (customPath: string | null) => {
      return albumsApi.update(id!, { custom_folder_path: customPath })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['album', id] })
      setIsEditingFolderPath(false)
    }
  })

  // Scan files mutation
  const scanFilesMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch(`/api/v1/albums/${id}/scan-files`, {
        method: 'POST'
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to scan files')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['album', id] })
      setScanResults(data)
      setShowScanResults(true)
    },
    onError: (error: Error) => {
      alert(`Scan failed: ${error.message}`)
    }
  })

  // Manual link mutation
  const linkTrackMutation = useMutation({
    mutationFn: async ({ trackId, filePath }: { trackId: string, filePath: string }) => {
      const response = await authFetch(
        `/api/v1/albums/${id}/link-track?track_id=${trackId}&file_path=${encodeURIComponent(filePath)}`,
        { method: 'POST' }
      )
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to link track')
      }
      return response.json()
    },
    onSuccess: (_data, variables) => {
      // Update scan results to remove the linked track from potential matches
      if (scanResults) {
        const updatedPotentialMatches = scanResults.potential_matches?.filter(
          (match: any) => match.track_id !== variables.trackId
        ) || []

        const updatedUnmatchedTracks = scanResults.unmatched_tracks?.filter(
          (track: any) => track.id !== variables.trackId
        ) || []

        setScanResults({
          ...scanResults,
          matches: (scanResults.matches || 0) + 1,
          potential_matches: updatedPotentialMatches,
          unmatched_tracks: updatedUnmatchedTracks
        })
      }

      // Refresh album data to update track list
      queryClient.invalidateQueries({ queryKey: ['album', id] })
    },
    onError: (error: Error) => {
      alert(`Failed to link track: ${error.message}`)
    }
  })

  // Unlink mutation
  const unlinkTrackMutation = useMutation({
    mutationFn: async (trackId: string) => {
      const response = await authFetch(
        `/api/v1/albums/${id}/unlink-track?track_id=${trackId}`,
        { method: 'POST' }
      )
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to unlink track')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['album', id] })
    },
    onError: (error: Error) => {
      alert(`Failed to unlink track: ${error.message}`)
    }
  })

  // Organize album files mutation
  const organizeFilesMutation = useMutation({
    mutationFn: async () => {
      return fileOrganizationApi.organizeAlbum(id!, organizeOptions)
    },
    onSuccess: () => {
      setOrganizeDialogOpen(false)
      const mode = organizeOptions.dry_run ? 'dry run' : 'organization'
      toast.success(`File ${mode} job started. Check File Management page to monitor progress.`)
    },
    onError: (error: Error) => {
      toast.error(`Failed to start organization job: ${error.message}`)
    }
  })

  const prefetchLyricsMutation = useMutation({
    mutationFn: async () => {
      return albumsApi.prefetchLyrics(id!)
    },
    onSuccess: (data) => {
      toast.success(`Lyrics: ${data.fetched} fetched, ${data.already_cached} cached, ${data.failed} not found`)
    },
    onError: (error: Error) => {
      toast.error(`Failed to fetch lyrics: ${error.message}`)
    }
  })

  // Per-track search mutation
  const trackSearchMutation = useMutation({
    mutationFn: async (trackId: string) => {
      const response = await authFetch(`/api/v1/tracks/${trackId}/search`, { method: 'POST' })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to search for track')
      }
      return response.json()
    },
    onSuccess: (data) => {
      setSearchingTrackId(null)
      queryClient.invalidateQueries({ queryKey: ['album', id] })
      if (data.success) {
        toast.success(data.message || `Track search started: ${data.track_title}`)
        queryClient.invalidateQueries({ queryKey: ['album-jobs', id] })
      } else {
        toast.error(data.error || 'Track search failed')
      }
    },
    onError: (error: Error) => {
      setSearchingTrackId(null)
      toast.error(`Track search failed: ${error.message}`)
    }
  })

  const clearDownloadsMutation = useMutation({
    mutationFn: async (statusFilter?: string) => {
      return albumsApi.clearDownloads(id!, statusFilter)
    },
    onSuccess: (data) => {
      toast.success(`Cleared ${data.cleared} download${data.cleared !== 1 ? 's' : ''}`)
      queryClient.invalidateQueries({ queryKey: ['album', id] })
    },
    onError: (error: Error) => {
      toast.error(`Failed to clear downloads: ${error.message}`)
    }
  })

  // Delete track file mutation
  const deleteFileMutation = useMutation({
    mutationFn: async (trackId: string) => {
      return tracksApi.deleteFile(trackId)
    },
    onSuccess: (data) => {
      toast.success(data.message || 'File deleted')
      queryClient.invalidateQueries({ queryKey: ['album', id] })
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete file: ${error.message}`)
    }
  })

  const ratingMutation = useMutation({
    mutationFn: async ({ trackId, rating }: { trackId: string; rating: number | null }) => {
      return tracksApi.setRating(trackId, rating)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['album', id] })
    },
  })

  const createPlaylistMutation = useMutation({
    mutationFn: async () => {
      if (!album) throw new Error('Album not loaded')
      const trackIds = album.tracks.filter(t => t.has_file).map(t => t.id)
      if (trackIds.length === 0) throw new Error('No playable tracks')

      // Find unique name (handle duplicates)
      let name = album.title
      const existing = await playlistsApi.list(1000, 0)
      const existingNames = new Set(existing.items.map(p => p.name))
      if (existingNames.has(name)) {
        let suffix = 2
        while (existingNames.has(`${album.title} (${suffix})`)) suffix++
        name = `${album.title} (${suffix})`
      }

      const playlist = await playlistsApi.create({ name })
      await playlistsApi.addTracksBulk(playlist.id, trackIds)
      return playlist
    },
    onSuccess: (playlist) => {
      toast.success(`Created playlist "${playlist.name}"`)
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      navigate(`/playlists/${playlist.id}`)
    },
    onError: (error: any) => {
      toast.error(error?.response?.data?.detail || error.message || 'Failed to create playlist')
    },
  })

  const formatDuration = (ms: number | null): string => {
    if (!ms) return '--:--'
    const minutes = Math.floor(ms / 60000)
    const seconds = Math.floor((ms % 60000) / 1000)
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }

  const getTotalDuration = (): string => {
    if (!album?.tracks) return '--:--'
    const totalMs = album.tracks.reduce((sum, track) => sum + (track.duration_ms || 0), 0)
    return formatDuration(totalMs)
  }

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'downloaded':
        return 'badge-success'
      case 'wanted':
        return 'badge-warning'
      case 'missing':
        return 'badge-danger'
      case 'searching':
        return 'badge-info'
      default:
        return 'badge-secondary'
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
      </div>
    )
  }

  if (!album) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen">
        <p className="text-gray-500 dark:text-gray-400 mb-4">Album not found</p>
        <button className="btn btn-primary" onClick={() => navigate(-1)}>
          Go Back
        </button>
      </div>
    )
  }

  const tracksWithFile = album.tracks.filter(t => t.has_file).length
  const missingTracks = album.tracks.length - tracksWithFile

  return (
    <div className="relative min-h-screen -m-3 md:-m-6 overflow-x-hidden">
      <Toaster position="top-right" />
      {/* Blurred Album Art Background */}
      {album.cover_art_url && (
        <div
          className="fixed inset-0 bg-cover bg-center filter blur-3xl opacity-20 -z-10"
          style={{ backgroundImage: `url(${album.cover_art_url})` }}
        />
      )}

      {/* Content */}
      <div className="relative z-10 p-3 md:p-6 space-y-4 md:space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-start md:space-x-6">
        {/* Album Info - shown first on mobile */}
        <div className="flex-1 order-1 md:order-2">
          <div className="flex items-center space-x-3 mb-2">
            <button
              className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              onClick={() => navigate(`/disco-lounge/artists/${album.artist_id}`)}
              title="Go back to artist"
            >
              <FiArrowLeft className="w-5 h-5" />
            </button>
            <span className={`badge ${getStatusColor(album.status)}`}>
              {album.status}
            </span>
            {album.monitored && (
              <span className="badge badge-primary">
                <FiCheck className="w-3 h-3 mr-1" />
                Monitored
              </span>
            )}
          </div>

          <h1 className="text-2xl md:text-4xl font-bold text-gray-900 dark:text-white mb-1 md:mb-2">{album.title}</h1>

          <button
            className="text-lg md:text-xl text-[#FF1493] hover:text-[#d10f7a] mb-3 md:mb-4"
            onClick={() => navigate(`/disco-lounge/artists/${album.artist_id}`)}
          >
            {album.artist_name}
          </button>

        {/* Album Cover - inline on mobile, shown after title/artist */}
        <div className="md:hidden mb-4">
          <CoverArtUploader
            entityType="album"
            entityId={id!}
            currentUrl={album.cover_art_url}
            onSuccess={() => queryClient.invalidateQueries({ queryKey: ['album', id] })}
            uploadFn={albumsApi.uploadCoverArt}
            uploadFromUrlFn={albumsApi.uploadCoverArtFromUrl}
            fallback={<img src={S54.defaultAlbumArt} alt={album.title} className="w-full h-full rounded-lg object-contain" />}
            alt={album.title}
            className="w-48 h-48 mx-auto bg-gradient-to-br from-gray-600 to-gray-800 rounded-lg flex items-center justify-center shadow-lg overflow-hidden"
          />
        </div>

          {/* Album Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
            <div className="space-y-1">
              <div className="text-sm text-gray-500 dark:text-gray-400">Release Date</div>
              <div className="flex items-center space-x-2">
                <FiCalendar className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-gray-900 dark:text-white">
                  {album.release_date ? new Date(album.release_date).toLocaleDateString() : 'Unknown'}
                </span>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-sm text-gray-500 dark:text-gray-400">Type</div>
              <div className="flex items-center space-x-2">
                <FiDisc className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-gray-900 dark:text-white">
                  {album.album_type || 'Unknown'}
                </span>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-sm text-gray-500 dark:text-gray-400">Tracks</div>
              <div className="flex items-center space-x-2">
                <FiMusic className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-gray-900 dark:text-white">
                  {album.track_count} tracks
                </span>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-sm text-gray-500 dark:text-gray-400">Duration</div>
              <div className="flex items-center space-x-2">
                <FiClock className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-gray-900 dark:text-white">
                  {getTotalDuration()}
                </span>
              </div>
            </div>
          </div>

          {/* File Stats */}
          {album.tracks.length > 0 && (
            <div className="mt-4 p-4 bg-gray-50 dark:bg-[#161B22] rounded-lg">
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center space-x-4">
                  <div>
                    <span className="text-success-600 dark:text-success-400 font-medium">{tracksWithFile}</span>
                    <span className="text-gray-600 dark:text-gray-400"> available</span>
                  </div>
                  {missingTracks > 0 && (
                    <div>
                      <span className="text-danger-600 dark:text-danger-400 font-medium">{missingTracks}</span>
                      <span className="text-gray-600 dark:text-gray-400"> missing</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Custom Folder Path */}
          <div className="mt-4 p-4 bg-gray-50 dark:bg-[#161B22] rounded-lg">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <div className="flex items-center space-x-2 mb-2">
                  <FiFolder className="w-4 h-4 text-gray-400" />
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Custom Folder Path</span>
                </div>
                {isEditingFolderPath ? (
                  <div className="space-y-2">
                    <div className="flex items-center space-x-2">
                      <input
                        type="text"
                        value={folderPath}
                        onChange={(e) => setFolderPath(e.target.value)}
                        placeholder="/music/Artist/Album"
                        className="flex-1 px-3 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                      />
                      <button
                        className="btn btn-sm btn-secondary"
                        onClick={() => setShowFileBrowser(true)}
                      >
                        <FiFolder className="w-4 h-4 mr-1" />
                        Browse
                      </button>
                      <button
                        className="btn btn-sm btn-primary"
                        onClick={() => updateFolderPathMutation.mutate(folderPath || null)}
                        disabled={updateFolderPathMutation.isPending}
                        title="Save custom folder path"
                      >
                        {updateFolderPathMutation.isPending ? (
                          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        ) : (
                          <FiSave className="w-4 h-4" />
                        )}
                      </button>
                      <button
                        className="btn btn-sm btn-secondary"
                        onClick={() => {
                          setIsEditingFolderPath(false)
                          setFolderPath(album.custom_folder_path || '')
                        }}
                        title="Cancel editing"
                      >
                        <FiX className="w-4 h-4" />
                      </button>
                    </div>
                    {/* Scan button in edit mode - only if path is already saved */}
                    {album.custom_folder_path && (
                      <button
                        className="btn btn-sm btn-success w-full mt-2"
                        onClick={() => scanFilesMutation.mutate()}
                        disabled={scanFilesMutation.isPending}
                      >
                        {scanFilesMutation.isPending ? (
                          <div className="flex items-center justify-center">
                            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                            Scanning files...
                          </div>
                        ) : (
                          <div className="flex items-center justify-center">
                            <FiRefreshCw className="w-4 h-4 mr-2" />
                            Scan Files & Match Tracks
                          </div>
                        )}
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-600 dark:text-gray-400 font-mono">
                        {album.custom_folder_path || <span className="italic">Default path (Artist/Album structure)</span>}
                      </span>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => {
                          setFolderPath(album.custom_folder_path || '')
                          setIsEditingFolderPath(true)
                        }}
                        title="Edit custom folder path"
                      >
                        <FiEdit2 className="w-4 h-4" />
                      </button>
                    </div>
                    {/* Scan button - visible when custom path is set */}
                    {album.custom_folder_path && (
                      <button
                        className="btn btn-sm btn-success w-full"
                        onClick={() => scanFilesMutation.mutate()}
                        disabled={scanFilesMutation.isPending}
                      >
                        {scanFilesMutation.isPending ? (
                          <div className="flex items-center justify-center">
                            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                            Scanning files...
                          </div>
                        ) : (
                          <div className="flex items-center justify-center">
                            <FiRefreshCw className="w-4 h-4 mr-2" />
                            Scan Files & Match Tracks
                          </div>
                        )}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Action Buttons - desktop: inline, mobile: three-dot menu */}
          {/* Desktop buttons */}
          <div className="hidden md:flex flex-wrap gap-2 mt-6">
            {tracksWithFile > 0 && (
              <button
                className="btn btn-primary"
                title="Play all available tracks in this album"
                onClick={() => {
                  const playerTracks: PlayerTrack[] = album.tracks
                    .filter(t => t.has_file)
                    .map(t => ({
                      id: t.id,
                      title: t.title,
                      track_number: t.track_number,
                      duration_ms: t.duration_ms,
                      has_file: t.has_file,
                      file_path: t.file_path,
                      artist_name: album.artist_name,
                      artist_id: album.artist_id,
                      album_id: album.id,
                      album_title: album.title,
                      album_cover_art_url: album.cover_art_url,
                    }))
                  player.playAlbum(playerTracks)
                }}
              >
                <FiPlay className="w-4 h-4 mr-2" />
                Play All
              </button>
            )}
            {tracksWithFile > 0 && (
              <button
                className="btn btn-secondary"
                title="Shuffle play all available tracks"
                onClick={() => {
                  const playerTracks: PlayerTrack[] = album.tracks
                    .filter(t => t.has_file)
                    .map(t => ({
                      id: t.id,
                      title: t.title,
                      track_number: t.track_number,
                      duration_ms: t.duration_ms,
                      has_file: t.has_file,
                      file_path: t.file_path,
                      artist_name: album.artist_name,
                      artist_id: album.artist_id,
                      album_id: album.id,
                      album_title: album.title,
                      album_cover_art_url: album.cover_art_url,
                    }))
                  // Shuffle the array then play from index 0
                  const shuffled = [...playerTracks].sort(() => Math.random() - 0.5)
                  player.playAlbum(shuffled, 0)
                }}
              >
                <img src={S54.player.shuffle} alt="Shuffle" className="w-4 h-4 mr-2" />
                Shuffle
              </button>
            )}

            {tracksWithFile > 0 && (
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

            {isDjOrAbove && (
            <button
              className="btn btn-secondary"
              onClick={() => prefetchLyricsMutation.mutate()}
              disabled={prefetchLyricsMutation.isPending}
              title="Fetch lyrics for all tracks from LRCLIB"
            >
              {prefetchLyricsMutation.isPending ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                  Fetching...
                </>
              ) : (
                <>
                  <FiAlignLeft className="w-4 h-4 mr-2" />
                  Fetch Lyrics
                </>
              )}
            </button>
            )}

            {isDjOrAbove && (
            <button
              className="btn btn-primary"
              onClick={() => setOrganizeDialogOpen(true)}
              title="Organize album files into standardized folder structure"
            >
              <FiFolder className="w-4 h-4 mr-2" />
              Organize Files
            </button>
            )}

            {isDjOrAbove && (
            <button
              className={`btn ${album.monitored ? 'btn-secondary' : 'btn-primary'}`}
              onClick={() => updateMonitoringMutation.mutate(!album.monitored)}
              disabled={updateMonitoringMutation.isPending}
              title={album.monitored ? 'Stop monitoring this album for downloads' : 'Monitor this album for automatic downloads'}
            >
              {updateMonitoringMutation.isPending ? (
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
              ) : (
                <div className="flex items-center">
                  {album.monitored ? (
                    <>
                      <FiX className="w-4 h-4 mr-2" />
                      Unmonitor
                    </>
                  ) : (
                    <>
                      <FiCheck className="w-4 h-4 mr-2" />
                      Monitor
                    </>
                  )}
                </div>
              )}
            </button>
            )}

            {isDjOrAbove && (
            <button
              className="btn btn-secondary"
              onClick={() => manualSearchMutation.mutate()}
              disabled={manualSearchMutation.isPending}
              title="Search Usenet for this album"
            >
              {manualSearchMutation.isPending ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                  Searching...
                </>
              ) : (
                <>
                  <FiSearch className="w-4 h-4 mr-2" />
                  Manual Search
                </>
              )}
            </button>
            )}

            <button className="btn btn-secondary" onClick={() => refetch()} title="Refresh album data">
              <FiRefreshCw className="w-4 h-4 mr-2" />
              Refresh
            </button>
          </div>

          {/* Mobile action menu */}
          <div className="md:hidden mt-4 relative">
            <div className="flex items-center gap-2">
              {tracksWithFile > 0 && (
                <button
                  className="btn btn-primary btn-sm flex-1"
                  onClick={() => {
                    const playerTracks: PlayerTrack[] = album.tracks
                      .filter(t => t.has_file)
                      .map(t => ({
                        id: t.id,
                        title: t.title,
                        track_number: t.track_number,
                        duration_ms: t.duration_ms,
                        has_file: t.has_file,
                        file_path: t.file_path,
                        artist_name: album.artist_name,
                        artist_id: album.artist_id,
                        album_id: album.id,
                        album_title: album.title,
                        album_cover_art_url: album.cover_art_url,
                      }))
                    player.playAlbum(playerTracks)
                  }}
                >
                  <FiPlay className="w-4 h-4 mr-1" />
                  Play All
                </button>
              )}
              {tracksWithFile > 0 && (
                <button
                  className="btn btn-secondary btn-sm"
                  title="Shuffle play"
                  onClick={() => {
                    const playerTracks: PlayerTrack[] = album.tracks
                      .filter(t => t.has_file)
                      .map(t => ({
                        id: t.id,
                        title: t.title,
                        track_number: t.track_number,
                        duration_ms: t.duration_ms,
                        has_file: t.has_file,
                        file_path: t.file_path,
                        artist_name: album.artist_name,
                        artist_id: album.artist_id,
                        album_id: album.id,
                        album_title: album.title,
                        album_cover_art_url: album.cover_art_url,
                      }))
                    const shuffled = [...playerTracks].sort(() => Math.random() - 0.5)
                    player.playAlbum(shuffled, 0)
                  }}
                >
                  <img src={S54.player.shuffle} alt="Shuffle" className="w-4 h-4 mr-1" />
                  Shuffle
                </button>
              )}
              <button
                className="btn btn-secondary btn-sm p-2"
                onClick={() => setShowMobileActions(!showMobileActions)}
                title="More actions"
              >
                <FiMoreVertical className="w-5 h-5" />
              </button>
            </div>
            {showMobileActions && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowMobileActions(false)} />
                <div className="absolute right-0 top-full mt-1 z-50 w-56 bg-white dark:bg-[#161B22] rounded-lg shadow-xl border border-gray-200 dark:border-[#30363D] py-1">
                  {tracksWithFile > 0 && (
                  <button
                    className="w-full px-4 py-2.5 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#1C2128] flex items-center"
                    onClick={() => { createPlaylistMutation.mutate(); setShowMobileActions(false) }}
                    disabled={createPlaylistMutation.isPending}
                  >
                    <FiPlus className="w-4 h-4 mr-3" />
                    Create Playlist
                  </button>
                  )}
                  {isDjOrAbove && (
                  <button
                    className="w-full px-4 py-2.5 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#1C2128] flex items-center"
                    onClick={() => { prefetchLyricsMutation.mutate(); setShowMobileActions(false) }}
                    disabled={prefetchLyricsMutation.isPending}
                  >
                    <FiAlignLeft className="w-4 h-4 mr-3" />
                    Fetch Lyrics
                  </button>
                  )}
                  {isDjOrAbove && (
                  <button
                    className="w-full px-4 py-2.5 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#1C2128] flex items-center"
                    onClick={() => { setOrganizeDialogOpen(true); setShowMobileActions(false) }}
                  >
                    <FiFolder className="w-4 h-4 mr-3" />
                    Organize Files
                  </button>
                  )}
                  {isDjOrAbove && (
                  <button
                    className="w-full px-4 py-2.5 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#1C2128] flex items-center"
                    onClick={() => { updateMonitoringMutation.mutate(!album.monitored); setShowMobileActions(false) }}
                    disabled={updateMonitoringMutation.isPending}
                  >
                    {album.monitored ? <FiX className="w-4 h-4 mr-3" /> : <FiCheck className="w-4 h-4 mr-3" />}
                    {album.monitored ? 'Unmonitor' : 'Monitor'}
                  </button>
                  )}
                  {isDjOrAbove && (
                  <button
                    className="w-full px-4 py-2.5 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#1C2128] flex items-center"
                    onClick={() => { manualSearchMutation.mutate(); setShowMobileActions(false) }}
                    disabled={manualSearchMutation.isPending}
                  >
                    <FiSearch className="w-4 h-4 mr-3" />
                    Manual Search
                  </button>
                  )}
                  <button
                    className="w-full px-4 py-2.5 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#1C2128] flex items-center"
                    onClick={() => { refetch(); setShowMobileActions(false) }}
                  >
                    <FiRefreshCw className="w-4 h-4 mr-3" />
                    Refresh
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Album Cover - desktop only (shown to the left via order) */}
        <CoverArtUploader
          entityType="album"
          entityId={id!}
          currentUrl={album.cover_art_url}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ['album', id] })}
          uploadFn={albumsApi.uploadCoverArt}
          uploadFromUrlFn={albumsApi.uploadCoverArtFromUrl}
          fallback={<img src={S54.defaultAlbumArt} alt={album.title} className="w-full h-full rounded-lg object-contain" />}
          alt={album.title}
          className="hidden md:flex order-1 w-64 h-64 bg-gradient-to-br from-gray-600 to-gray-800 rounded-lg items-center justify-center flex-shrink-0 shadow-lg overflow-hidden"
        />
      </div>

      {/* Download Status Banner */}
      {album.downloads && album.downloads.length > 0 && (
        <div className="space-y-2">
          {album.downloads
            .filter((dl: any) => !['completed', 'COMPLETED'].includes(dl.status))
            .map((dl: any) => {
              const status = dl.status?.toUpperCase()
              const isActive = ['QUEUED', 'DOWNLOADING', 'POST_PROCESSING', 'IMPORTING'].includes(status)
              const isFailed = status === 'FAILED'
              return (
                <div
                  key={dl.id}
                  className={`flex items-center justify-between rounded-lg px-4 py-3 border ${
                    isFailed
                      ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                      : isActive
                      ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800'
                      : 'bg-gray-50 dark:bg-[#161B22] border-gray-200 dark:border-[#30363D]'
                  }`}
                >
                  <div className="flex items-center space-x-3 min-w-0">
                    {isActive ? (
                      <FiLoader className="w-4 h-4 text-amber-600 dark:text-amber-400 animate-spin flex-shrink-0" />
                    ) : isFailed ? (
                      <FiX className="w-4 h-4 text-red-600 dark:text-red-400 flex-shrink-0" />
                    ) : (
                      <FiCheck className="w-4 h-4 text-green-600 dark:text-green-400 flex-shrink-0" />
                    )}
                    <div className="min-w-0">
                      <div className="flex items-center space-x-2">
                        <span className={`text-sm font-medium ${
                          isFailed ? 'text-red-800 dark:text-red-200' :
                          isActive ? 'text-amber-800 dark:text-amber-200' :
                          'text-gray-800 dark:text-gray-200'
                        }`}>
                          {status === 'QUEUED' ? 'Queued in SABnzbd' :
                           status === 'DOWNLOADING' ? 'Downloading...' :
                           status === 'POST_PROCESSING' ? 'Extracting...' :
                           status === 'IMPORTING' ? 'Importing...' :
                           status === 'FAILED' ? 'Download Failed' :
                           status}
                        </span>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                          isFailed ? 'bg-red-100 text-red-700 dark:bg-red-800 dark:text-red-200' :
                          isActive ? 'bg-amber-100 text-amber-700 dark:bg-amber-800 dark:text-amber-200' :
                          'bg-gray-100 text-gray-700 dark:bg-[#0D1117] dark:text-gray-200'
                        }`}>
                          {(dl.size_bytes / (1024 * 1024)).toFixed(1)} MB
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5" title={dl.nzb_title}>
                        {dl.nzb_title}
                      </p>
                      {dl.error_message && (
                        <p className="text-xs text-red-600 dark:text-red-400 mt-1">{dl.error_message}</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center space-x-3 flex-shrink-0 ml-4">
                    {isActive && (
                      <>
                        <div className="w-24 bg-amber-200 dark:bg-amber-800 rounded-full h-2">
                          <div
                            className="bg-amber-600 dark:bg-amber-400 h-2 rounded-full transition-all duration-500"
                            style={{ width: `${Math.min(100, dl.progress_percent || 0)}%` }}
                          />
                        </div>
                        <span className="text-xs font-medium text-amber-800 dark:text-amber-200 w-10 text-right">
                          {dl.progress_percent || 0}%
                        </span>
                      </>
                    )}
                    {isFailed && (
                      <button
                        onClick={() => clearDownloadsMutation.mutate('failed')}
                        className="p-1 rounded hover:bg-red-200 dark:hover:bg-red-800 transition-colors"
                        title="Clear failed downloads"
                      >
                        <FiX className="w-4 h-4 text-red-500 dark:text-red-400" />
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
        </div>
      )}

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
                    {job.job_type === 'album_search' ? 'Album Search' : job.job_type.replace(/_/g, ' ')}
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

      {/* Tracks Table */}
      <div className="card">
        <div className="p-4 border-b border-gray-200 dark:border-[#30363D]">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white">Tracks</h2>
        </div>

        {(() => {
          const isMultiDisc = album.tracks.some(t => t.disc_number > 1)
          const discNumbers = isMultiDisc ? [...new Set(album.tracks.map(t => t.disc_number))].sort((a, b) => a - b) : [1]
          const tracksByDisc = (disc: number) => album.tracks.filter(t => t.disc_number === disc)

          return album.tracks.length > 0 ? (
          <>
          {/* Desktop table */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 dark:bg-[#161B22]">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-16">
                    #
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Title
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-24">
                    Duration
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-28">
                    Rating
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-32">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-24">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-[#0D1117] divide-y divide-gray-200 dark:divide-[#30363D]">
                {discNumbers.flatMap((disc) => [
                  ...(isMultiDisc ? [
                    <tr key={`disc-header-${disc}`} className="bg-gray-100 dark:bg-[#161B22]">
                      <td colSpan={6} className="px-4 py-2">
                        <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">Disc {disc}</span>
                        <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">{tracksByDisc(disc).length} tracks</span>
                      </td>
                    </tr>
                  ] : []),
                  ...tracksByDisc(disc).map((track) => (
                  <tr
                    key={track.id}
                    className="hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors"
                  >
                    <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      {track.track_number}
                    </td>
                    <td className="px-4 py-3">
                      <div className={`text-sm font-medium ${
                        track.has_file
                          ? 'text-gray-900 dark:text-white'
                          : 'text-gray-500 dark:text-gray-600'
                      }`}>
                        {track.title}
                      </div>
                      {track.has_file && track.file_path && (
                        <div className="text-xs text-gray-500 dark:text-gray-400 font-mono mt-1 truncate max-w-md" title={track.file_path}>
                          {track.file_path}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      {formatDuration(track.duration_ms)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <StarRating
                          rating={track.user_rating}
                          size="sm"
                          onChange={(rating) => ratingMutation.mutate({ trackId: track.id, rating })}
                        />
                        {track.average_rating != null && track.rating_count != null && track.rating_count > 1 && (
                          <span className="text-[10px] text-gray-400 dark:text-[#484F58]" title={`${track.rating_count} ratings`}>
                            Avg: {track.average_rating.toFixed(1)}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      {track.has_file ? (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium bg-success-100 text-success-800 dark:bg-success-900 dark:text-success-200">
                          <FiCheck className="w-3 h-3 mr-1" />
                          Available
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800 dark:bg-[#0D1117] dark:text-gray-300">
                          <FiX className="w-3 h-3 mr-1" />
                          Missing
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center space-x-2">
                        {track.has_file ? (
                          <>
                            <button
                              className="text-[#FF1493] hover:text-[#d10f7a]"
                              title="Play this track from your library"
                              onClick={() => player.play({
                                id: track.id,
                                title: track.title,
                                track_number: track.track_number,
                                duration_ms: track.duration_ms,
                                has_file: track.has_file,
                                file_path: track.file_path,
                                artist_name: album.artist_name,
                                artist_id: album.artist_id,
                                album_id: album.id,
                                album_title: album.title,
                                album_cover_art_url: album.cover_art_url,
                              })}
                            >
                              <FiPlay className="w-4 h-4" />
                            </button>
                            <button
                              className="text-gray-500 dark:text-gray-400 hover:text-[#FF1493]"
                              title="Add to the play queue"
                              onClick={() => player.addToQueue({
                                id: track.id,
                                title: track.title,
                                track_number: track.track_number,
                                duration_ms: track.duration_ms,
                                has_file: track.has_file,
                                file_path: track.file_path,
                                artist_name: album.artist_name,
                                artist_id: album.artist_id,
                                album_id: album.id,
                                album_title: album.title,
                                album_cover_art_url: album.cover_art_url,
                              })}
                            >
                              <FiPlus className="w-4 h-4" />
                            </button>
                            {isDjOrAbove && (
                              <button
                                className="text-green-600 hover:text-green-700 dark:text-green-400 dark:hover:text-green-300"
                                title="Download file to your computer"
                                onClick={async () => {
                                  try {
                                    const blob = await tracksApi.download(track.id)
                                    const url = window.URL.createObjectURL(blob)
                                    const a = document.createElement('a')
                                    a.href = url
                                    a.download = track.file_path?.split('/').pop() || `${track.title}.mp3`
                                    document.body.appendChild(a)
                                    a.click()
                                    window.URL.revokeObjectURL(url)
                                    document.body.removeChild(a)
                                  } catch {
                                    toast.error('Failed to download track')
                                  }
                                }}
                              >
                                <FiDownload className="w-4 h-4" />
                              </button>
                            )}
                            <button
                              className="text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
                              title="30-second iTunes preview (compare with your file)"
                              disabled={previewLoading.get(track.id)}
                              onClick={async () => {
                                setPreviewLoading(prev => new Map(prev).set(track.id, true))
                                try {
                                  const result = await searchPreview(album.artist_name, track.title)
                                  if (result) {
                                    player.play({
                                      id: `preview-${track.id}`,
                                      title: `[Preview] ${track.title}`,
                                      track_number: track.track_number,
                                      duration_ms: track.duration_ms,
                                      has_file: false,
                                      preview_url: result.preview_url,
                                      artist_name: album.artist_name,
                                      artist_id: album.artist_id,
                                      album_id: album.id,
                                      album_title: album.title,
                                      album_cover_art_url: album.cover_art_url,
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
                          </>
                        ) : (
                          <>
                            {/* Search/Download track button - only when not already downloading */}
                            {isDjOrAbove && album.status !== 'downloading' && album.status !== 'searching' && (
                              <button
                                className="text-[#FF1493] hover:text-[#d10f7a] dark:text-[#ff4da6] dark:hover:text-[#ff4da6]"
                                title="Search Usenet for this track"
                                disabled={searchingTrackId === track.id}
                                onClick={() => {
                                  setSearchingTrackId(track.id)
                                  trackSearchMutation.mutate(track.id)
                                }}
                              >
                                {searchingTrackId === track.id ? (
                                  <FiLoader className="w-4 h-4 animate-spin" />
                                ) : (
                                  <FiDownload className="w-4 h-4" />
                                )}
                              </button>
                            )}
                            <button
                              className="text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
                              title="Listen to a 30-second preview from iTunes"
                              disabled={previewLoading.get(track.id)}
                              onClick={async () => {
                                setPreviewLoading(prev => new Map(prev).set(track.id, true))
                                try {
                                  const result = await searchPreview(album.artist_name, track.title)
                                  if (result) {
                                    player.play({
                                      id: track.id,
                                      title: track.title,
                                      track_number: track.track_number,
                                      duration_ms: track.duration_ms,
                                      has_file: false,
                                      preview_url: result.preview_url,
                                      artist_name: album.artist_name,
                                      artist_id: album.artist_id,
                                      album_id: album.id,
                                      album_title: album.title,
                                      album_cover_art_url: album.cover_art_url,
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
                          </>
                        )}
                        {track.has_file && (
                          <>
                            <AddToPlaylistDropdown trackId={track.id} />
                            {isDjOrAbove && (
                            <button
                              className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                              title="Unlink this track from its file (keeps file on disk)"
                              onClick={() => {
                                if (confirm(`Unlink "${track.title}" from its file? The file will remain on disk.`)) {
                                  unlinkTrackMutation.mutate(track.id)
                                }
                              }}
                              disabled={unlinkTrackMutation.isPending}
                            >
                              {unlinkTrackMutation.isPending && unlinkTrackMutation.variables === track.id ? (
                                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-400"></div>
                              ) : (
                                <FiX className="w-4 h-4" />
                              )}
                            </button>
                            )}
                            {isDjOrAbove && (
                            <button
                              className="text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300"
                              title="Delete this track's file from disk"
                              onClick={() => {
                                if (confirm(`Delete the file for "${track.title}"? This cannot be undone.`)) {
                                  deleteFileMutation.mutate(track.id)
                                }
                              }}
                              disabled={deleteFileMutation.isPending}
                            >
                              {deleteFileMutation.isPending && deleteFileMutation.variables === track.id ? (
                                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-red-500"></div>
                              ) : (
                                <FiTrash2 className="w-4 h-4" />
                              )}
                            </button>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                )),
                ])}
              </tbody>
            </table>
          </div>

          {/* Mobile track list */}
          <div className="md:hidden divide-y divide-gray-200 dark:divide-[#30363D]">
            {discNumbers.flatMap((disc) => [
              ...(isMultiDisc ? [
                <div key={`disc-header-mobile-${disc}`} className="bg-gray-100 dark:bg-[#161B22] px-3 py-2">
                  <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">Disc {disc}</span>
                  <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">{tracksByDisc(disc).length} tracks</span>
                </div>
              ] : []),
              ...tracksByDisc(disc).map((track) => (
              <div key={track.id}>
                <div
                  className="flex items-center px-3 py-3 active:bg-gray-50 dark:active:bg-gray-800"
                  onClick={() => setExpandedTrackId(expandedTrackId === track.id ? null : track.id)}
                >
                  <div className="flex-1 min-w-0 mr-2">
                    <div className="flex items-center">
                      <span className="text-xs text-gray-400 dark:text-gray-500 w-6 flex-shrink-0">{track.track_number}.</span>
                      <span className={`text-sm font-medium truncate ${
                        track.has_file ? 'text-gray-900 dark:text-white' : 'text-gray-400 dark:text-gray-600'
                      }`}>
                        {track.title}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <div className="flex items-center gap-1.5">
                      <StarRating
                        rating={track.user_rating}
                        size="sm"
                        onChange={(rating) => { ratingMutation.mutate({ trackId: track.id, rating }) }}
                      />
                      {track.average_rating != null && track.rating_count != null && track.rating_count > 1 && (
                        <span className="text-[10px] text-gray-400 dark:text-[#484F58]" title={`${track.rating_count} ratings`}>
                          Avg: {track.average_rating.toFixed(1)}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center space-x-1">
                      {track.has_file ? (
                        <button
                          className="p-1.5 text-[#FF1493] hover:text-[#d10f7a]"
                          title="Play"
                          onClick={(e) => {
                            e.stopPropagation()
                            player.play({
                              id: track.id,
                              title: track.title,
                              track_number: track.track_number,
                              duration_ms: track.duration_ms,
                              has_file: track.has_file,
                              file_path: track.file_path,
                              artist_name: album.artist_name,
                              artist_id: album.artist_id,
                              album_id: album.id,
                              album_title: album.title,
                              album_cover_art_url: album.cover_art_url,
                            })
                          }}
                        >
                          <FiPlay className="w-4 h-4" />
                        </button>
                      ) : (
                        <button
                          className="p-1.5 text-amber-600 hover:text-amber-700"
                          title="Preview"
                          disabled={previewLoading.get(track.id)}
                          onClick={async (e) => {
                            e.stopPropagation()
                            setPreviewLoading(prev => new Map(prev).set(track.id, true))
                            try {
                              const result = await searchPreview(album.artist_name, track.title)
                              if (result) {
                                player.play({
                                  id: track.id,
                                  title: track.title,
                                  track_number: track.track_number,
                                  duration_ms: track.duration_ms,
                                  has_file: false,
                                  preview_url: result.preview_url,
                                  artist_name: album.artist_name,
                                  artist_id: album.artist_id,
                                  album_id: album.id,
                                  album_title: album.title,
                                  album_cover_art_url: album.cover_art_url,
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
                    </div>
                    {expandedTrackId === track.id ? (
                      <FiChevronUp className="w-4 h-4 text-gray-400" />
                    ) : (
                      <FiChevronDown className="w-4 h-4 text-gray-400" />
                    )}
                  </div>
                </div>

                {/* Expanded detail panel */}
                {expandedTrackId === track.id && (
                  <div className="px-3 pb-3 bg-gray-50 dark:bg-[#161B22]/50 space-y-2">
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="text-gray-500 dark:text-gray-400">Duration</span>
                        <p className="text-gray-900 dark:text-white font-medium">{formatDuration(track.duration_ms)}</p>
                      </div>
                      <div>
                        <span className="text-gray-500 dark:text-gray-400">Status</span>
                        <p>
                          {track.has_file ? (
                            <span className="inline-flex items-center text-success-700 dark:text-success-400 font-medium">
                              <FiCheck className="w-3 h-3 mr-1" /> Available
                            </span>
                          ) : (
                            <span className="inline-flex items-center text-gray-500 dark:text-gray-400 font-medium">
                              <FiX className="w-3 h-3 mr-1" /> Missing
                            </span>
                          )}
                        </p>
                      </div>
                    </div>
                    {track.has_file && track.file_path && (
                      <div className="text-xs">
                        <span className="text-gray-500 dark:text-gray-400">Path</span>
                        <p className="text-gray-700 dark:text-gray-300 font-mono break-all">{track.file_path}</p>
                      </div>
                    )}
                    <div className="flex items-center gap-2 pt-1 flex-wrap">
                      {track.has_file ? (
                        <>
                          <button
                            className="text-xs px-2 py-1 bg-[#FF1493]/10 dark:bg-[#FF1493]/15 text-[#d10f7a] dark:text-[#ff4da6] rounded hover:bg-[#FF1493]/15 dark:hover:bg-[#FF1493]/20"
                            onClick={() => player.addToQueue({
                              id: track.id, title: track.title, track_number: track.track_number, duration_ms: track.duration_ms,
                              has_file: track.has_file, file_path: track.file_path, artist_name: album.artist_name,
                              artist_id: album.artist_id, album_id: album.id, album_title: album.title, album_cover_art_url: album.cover_art_url,
                            })}
                          >
                            <FiPlus className="w-3 h-3 inline mr-1" />Queue
                          </button>
                          {isDjOrAbove && (
                            <button
                              className="text-xs px-2 py-1 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 rounded hover:bg-green-200 dark:hover:bg-green-900/50"
                              onClick={async () => {
                                try {
                                  const blob = await tracksApi.download(track.id)
                                  const url = window.URL.createObjectURL(blob)
                                  const a = document.createElement('a')
                                  a.href = url
                                  a.download = track.file_path?.split('/').pop() || `${track.title}.mp3`
                                  document.body.appendChild(a)
                                  a.click()
                                  window.URL.revokeObjectURL(url)
                                  document.body.removeChild(a)
                                } catch {
                                  toast.error('Failed to download track')
                                }
                              }}
                            >
                              <FiDownload className="w-3 h-3 inline mr-1" />Download
                            </button>
                          )}
                          <button
                            className="text-xs px-2 py-1 bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 rounded hover:bg-amber-200 dark:hover:bg-amber-900/50"
                            disabled={previewLoading.get(track.id)}
                            onClick={async () => {
                              setPreviewLoading(prev => new Map(prev).set(track.id, true))
                              try {
                                const result = await searchPreview(album.artist_name, track.title)
                                if (result) {
                                  player.play({
                                    id: `preview-${track.id}`, title: `[Preview] ${track.title}`, track_number: track.track_number,
                                    duration_ms: track.duration_ms, has_file: false, preview_url: result.preview_url,
                                    artist_name: album.artist_name, artist_id: album.artist_id, album_id: album.id,
                                    album_title: album.title, album_cover_art_url: album.cover_art_url,
                                  })
                                } else { toast.error(`No preview found for "${track.title}"`) }
                              } catch { toast.error('Failed to fetch preview') }
                              finally { setPreviewLoading(prev => new Map(prev).set(track.id, false)) }
                            }}
                          >
                            <FiHeadphones className="w-3 h-3 inline mr-1" />Preview
                          </button>
                          <AddToPlaylistDropdown trackId={track.id} />
                          {isDjOrAbove && (
                          <button
                            className="text-xs px-2 py-1 bg-gray-100 dark:bg-[#0D1117] text-gray-600 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-[#30363D]"
                            onClick={() => {
                              if (confirm(`Unlink "${track.title}" from its file?`)) unlinkTrackMutation.mutate(track.id)
                            }}
                          >
                            <FiX className="w-3 h-3 inline mr-1" />Unlink
                          </button>
                          )}
                          {isDjOrAbove && (
                          <button
                            className="text-xs px-2 py-1 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 rounded hover:bg-red-200 dark:hover:bg-red-900/50"
                            onClick={() => {
                              if (confirm(`Delete the file for "${track.title}"? This cannot be undone.`)) deleteFileMutation.mutate(track.id)
                            }}
                          >
                            <FiTrash2 className="w-3 h-3 inline mr-1" />Delete
                          </button>
                          )}
                        </>
                      ) : (
                        <>
                          {isDjOrAbove && album.status !== 'downloading' && album.status !== 'searching' && (
                            <button
                              className="text-xs px-2 py-1 bg-[#FF1493]/10 dark:bg-[#FF1493]/15 text-[#d10f7a] dark:text-[#ff4da6] rounded hover:bg-[#FF1493]/15 dark:hover:bg-[#FF1493]/20"
                              disabled={searchingTrackId === track.id}
                              onClick={() => { setSearchingTrackId(track.id); trackSearchMutation.mutate(track.id) }}
                            >
                              {searchingTrackId === track.id ? <FiLoader className="w-3 h-3 inline mr-1 animate-spin" /> : <FiDownload className="w-3 h-3 inline mr-1" />}
                              Search
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )),
            ])}
          </div>
          </>
        ) : (
          <div className="p-12 text-center">
            <FiMusic className="w-16 h-16 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400 mb-4">
              No tracks found for this album
            </p>
            <button className="btn btn-primary">
              Sync Tracks from MusicBrainz
            </button>
          </div>
        )
        })()}
      </div>

      {/* Download History (if any) */}
      {album.downloads && album.downloads.length > 0 && (
        <div className="card">
          <div className="p-4 border-b border-gray-200 dark:border-[#30363D] flex items-center justify-between">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">Download History</h2>
            <div className="flex gap-2">
              {album.downloads.some((dl: any) => dl.status?.toUpperCase() === 'FAILED') && (
                <button
                  onClick={() => clearDownloadsMutation.mutate('failed')}
                  disabled={clearDownloadsMutation.isPending}
                  className="px-3 py-1.5 text-sm bg-red-100 hover:bg-red-200 dark:bg-red-900/30 dark:hover:bg-red-900/50 text-red-700 dark:text-red-400 rounded-lg transition-colors"
                >
                  {clearDownloadsMutation.isPending ? 'Clearing...' : 'Clear Failed'}
                </button>
              )}
              <button
                onClick={() => clearDownloadsMutation.mutate(undefined)}
                disabled={clearDownloadsMutation.isPending}
                className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 dark:bg-[#0D1117] dark:hover:bg-[#30363D] text-gray-700 dark:text-gray-300 rounded-lg transition-colors"
              >
                Clear All
              </button>
            </div>
          </div>
          <div className="p-4 space-y-3">
            {album.downloads.map((download: any, index: number) => (
              <div key={index} className={`p-3 rounded-lg ${
                download.status?.toUpperCase() === 'FAILED'
                  ? 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'
                  : download.status?.toUpperCase() === 'COMPLETED'
                  ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
                  : 'bg-gray-50 dark:bg-[#161B22]'
              }`}>
                <div className="flex items-center justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-gray-900 dark:text-white truncate">
                      {download.nzb_title || download.release_title || 'Unknown'}
                    </div>
                    <div className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                      {download.size_bytes ? `${(download.size_bytes / (1024 * 1024)).toFixed(1)} MB` : download.size_mb ? `${download.size_mb} MB` : ''}
                      {download.queued_at && ` • ${new Date(download.queued_at).toLocaleString()}`}
                      {download.completed_at && ` • Completed: ${new Date(download.completed_at).toLocaleString()}`}
                    </div>
                  </div>
                  <span className={`badge ${getStatusColor(download.status)} ml-3 flex-shrink-0`}>
                    {download.status}
                  </span>
                </div>
                {download.error_message && (
                  <div className="mt-2 text-sm text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-900/30 rounded px-3 py-2">
                    {download.error_message}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* File Browser Modal */}
      <FileBrowserModal
        isOpen={showFileBrowser}
        onClose={() => setShowFileBrowser(false)}
        onSelect={(path) => {
          setFolderPath(path)
          setShowFileBrowser(false)
        }}
        initialPath={folderPath || '/music'}
      />

      {/* Scan Results Modal */}
      {showScanResults && scanResults && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <div>
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Scan Results</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {scanResults.files_found} files found • {scanResults.matches} auto-matched • {scanResults.potential_matches?.length || 0} need review
                </p>
              </div>
              <button
                onClick={() => setShowScanResults(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                title="Close scan results"
              >
                <FiX className="w-6 h-6" />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Auto-matched tracks */}
              {scanResults.matches > 0 && (
                <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4">
                  <h3 className="font-semibold text-green-900 dark:text-green-100 mb-2">
                    <FiCheck className="inline w-5 h-5 mr-2" />
                    {scanResults.matches} Track{scanResults.matches > 1 ? 's' : ''} Matched Automatically
                  </h3>
                </div>
              )}

              {/* Potential matches for manual selection */}
              {scanResults.potential_matches && scanResults.potential_matches.length > 0 && (
                <div className="space-y-4">
                  <h3 className="font-semibold text-gray-900 dark:text-white text-lg">
                    Manual Linking - Select File for Each Track
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400 -mt-2">
                    Click "Link" to manually connect a track to its file
                  </p>
                  {scanResults.potential_matches.map((match: any) => (
                    <div key={match.track_id} className="border border-gray-200 dark:border-[#30363D] rounded-lg p-4">
                      <div className="font-medium text-gray-900 dark:text-white mb-3">
                        Track #{match.track_number}: {match.track_title}
                      </div>
                      <div className="space-y-2">
                        {match.suggestions.map((suggestion: any, idx: number) => {
                          const fileExt = suggestion.file_name.split('.').pop()?.toUpperCase() || 'UNKNOWN'
                          return (
                            <div
                              key={idx}
                              className="flex items-start justify-between p-3 bg-gray-50 dark:bg-[#0D1117] rounded-lg hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors"
                            >
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center space-x-2 mb-1">
                                  <span className="px-2 py-0.5 bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300 text-xs font-mono rounded">
                                    {fileExt}
                                  </span>
                                  <div className="font-medium text-sm text-gray-900 dark:text-white truncate">
                                    {suggestion.file_name}
                                  </div>
                                </div>
                                <div className="text-xs text-gray-600 dark:text-gray-400 font-mono bg-gray-100 dark:bg-gray-950 px-2 py-1 rounded mb-1 overflow-x-auto">
                                  {suggestion.file_path}
                                </div>
                                <div className="text-xs text-gray-500 dark:text-gray-400">
                                  <span className="font-medium">Metadata:</span>{' '}
                                  {suggestion.metadata.title || 'No title'} • {suggestion.metadata.artist || 'No artist'}
                                  {suggestion.metadata.duration_ms && (
                                    <span> • {formatDuration(suggestion.metadata.duration_ms)}</span>
                                  )}
                                </div>
                              </div>
                              <div className="flex items-center space-x-3 ml-4 flex-shrink-0">
                                <span className={`px-2 py-1 rounded text-xs font-medium whitespace-nowrap ${
                                  suggestion.confidence >= 80 ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300' :
                                  suggestion.confidence >= 65 ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300' :
                                  'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300'
                                }`}>
                                  {suggestion.confidence}%
                                </span>
                                <button
                                  onClick={() => {
                                    linkTrackMutation.mutate({
                                      trackId: match.track_id,
                                      filePath: suggestion.file_path
                                    })
                                  }}
                                  className="btn btn-sm btn-primary"
                                  disabled={linkTrackMutation.isPending}
                                >
                                  {linkTrackMutation.isPending ? (
                                    <div className="flex items-center">
                                      <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-white mr-1"></div>
                                      Linking...
                                    </div>
                                  ) : (
                                    <>
                                      <FiCheck className="w-3 h-3 mr-1" />
                                      Link
                                    </>
                                  )}
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Unmatched tracks */}
              {scanResults.unmatched_tracks && scanResults.unmatched_tracks.length > 0 && (
                <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
                  <h3 className="font-semibold text-yellow-900 dark:text-yellow-100 mb-2">
                    {scanResults.unmatched_tracks.length} Unmatched Track{scanResults.unmatched_tracks.length > 1 ? 's' : ''}
                  </h3>
                  <ul className="text-sm text-yellow-800 dark:text-yellow-200 ml-4 list-disc">
                    {scanResults.unmatched_tracks.map((track: any) => (
                      <li key={track.id}>#{track.track_number}: {track.title}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Unmatched files */}
              {scanResults.unmatched_files && scanResults.unmatched_files.length > 0 && (
                <div className="bg-gray-50 dark:bg-[#0D1117] border border-gray-200 dark:border-[#30363D] rounded-lg p-4">
                  <h3 className="font-semibold text-gray-900 dark:text-white mb-2">
                    {scanResults.unmatched_files.length} Unmatched File{scanResults.unmatched_files.length > 1 ? 's' : ''}
                  </h3>
                  <ul className="text-sm text-gray-600 dark:text-gray-400 ml-4 list-disc">
                    {scanResults.unmatched_files.map((file: any, idx: number) => (
                      <li key={idx}>{file.name || file.path}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="p-6 border-t border-gray-200 dark:border-[#30363D]">
              <button
                onClick={() => setShowScanResults(false)}
                className="btn btn-primary w-full"
              >
                Done
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
                Organize Album Files
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Organize files for <strong>{album.title}</strong> by <strong>{album.artist_name}</strong> into standardized folder structure with MBID-based naming.
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
                    <p className="text-xs text-gray-500">Create .mbid.json file in album directory</p>
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
      </div>
    </div>
  )
}

export default AlbumDetail
