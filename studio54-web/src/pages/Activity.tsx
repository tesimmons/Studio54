import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { jobsApi, downloadHistoryApi, type Job, type JobStats } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import QueueStatus from './QueueStatus'
import {
  FiPause,
  FiX,
  FiRefreshCw,
  FiAlertCircle,
  FiCheckCircle,
  FiClock,
  FiActivity,
  FiTrash2,
  FiCopy,
  FiFileText,
  FiDownload,
  FiSearch,
  FiInfo,
  FiChevronLeft,
  FiChevronRight,
} from 'react-icons/fi'
import Pagination from '../components/Pagination'

const DEFAULT_PER_PAGE = 50

function Activity() {
  const { isDirector } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState<'jobs' | 'downloads' | 'queue-status'>('jobs')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')

  // Downloads tab state
  const [dlStatusFilter, setDlStatusFilter] = useState('')
  const [dlDateFrom, setDlDateFrom] = useState('')
  const [dlDateTo, setDlDateTo] = useState('')

  // Read URL search params on mount
  useEffect(() => {
    const tab = searchParams.get('tab')
    if (tab === 'downloads') setActiveTab('downloads')
    else if (tab === 'queue-status') setActiveTab('queue-status')

    const sf = searchParams.get('status_filter')
    if (sf) setDlStatusFilter(sf)

    const df = searchParams.get('date_from')
    if (df) setDlDateFrom(df)

    const dt = searchParams.get('date_to')
    if (dt) setDlDateTo(dt)

    // Clear params after reading so they don't persist on tab switches
    if (tab || sf || df || dt) {
      setSearchParams({}, { replace: true })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  const [dlPage, setDlPage] = useState(0)
  const DL_PAGE_SIZE = 50
  const [selectedJobForLog, setSelectedJobForLog] = useState<Job | null>(null)
  const [logContent, setLogContent] = useState<string>('')
  const [logLoading, setLogLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [itemsPerPage, setItemsPerPage] = useState(DEFAULT_PER_PAGE)
  const queryClient = useQueryClient()

  // Fetch jobs with auto-refresh every 5 seconds
  const { data: jobsData, isLoading } = useQuery({
    queryKey: ['jobs', statusFilter, typeFilter, page, itemsPerPage],
    queryFn: () =>
      jobsApi.list({
        status: statusFilter || undefined,
        job_type: typeFilter || undefined,
        limit: itemsPerPage,
        offset: (page - 1) * itemsPerPage,
      }),
    refetchInterval: 5000,
  })

  const jobs = jobsData?.jobs || []
  const totalCount = jobsData?.total_count || 0
  const totalPages = Math.ceil(totalCount / itemsPerPage)

  // Fetch stats
  const { data: stats } = useQuery<JobStats>({
    queryKey: ['jobStats'],
    queryFn: () => jobsApi.getStats(),
    refetchInterval: 5000,
  })

  // Fetch download history
  const { data: dlData, isLoading: dlLoading, isError: dlError, error: dlErrorObj } = useQuery({
    queryKey: ['download-history', dlStatusFilter, dlDateFrom, dlDateTo, dlPage],
    queryFn: () =>
      downloadHistoryApi.getHistory({
        status_filter: dlStatusFilter || undefined,
        date_from: dlDateFrom || undefined,
        date_to: dlDateTo || undefined,
        limit: DL_PAGE_SIZE,
        offset: dlPage * DL_PAGE_SIZE,
      }),
    refetchInterval: 30000,
    enabled: activeTab === 'downloads',
  })

  const dlTotalPages = dlData ? Math.ceil(dlData.total / DL_PAGE_SIZE) : 0

  const DL_STATUS_BADGES: Record<string, { label: string; className: string }> = {
    GRABBED: { label: 'Grabbed', className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
    IMPORTED: { label: 'Imported', className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
    IMPORT_STARTED: { label: 'Importing', className: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400' },
    DOWNLOAD_FAILED: { label: 'Download Failed', className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
    IMPORT_FAILED: { label: 'Import Failed', className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
    DELETED: { label: 'Deleted', className: 'bg-gray-100 text-gray-700 dark:bg-[#0D1117] dark:text-gray-300' },
    BLACKLISTED: { label: 'Blacklisted', className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' },
  }

  // Cancel mutation with error handling
  const cancelMutation = useMutation({
    mutationFn: jobsApi.cancel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobStats'] })
    },
    onError: (error: unknown, jobId: string) => {
      // Extract error message from axios error response
      const axiosError = error as { response?: { data?: { detail?: string }, status?: number }, message?: string }
      const errorMsg = axiosError.response?.data?.detail || axiosError.message || 'Unknown error'
      const statusCode = axiosError.response?.status

      if (statusCode === 404 || errorMsg.includes('not found') || errorMsg.includes('Not Found')) {
        if (confirm(`Job not found on server. This may be a stale entry.\n\nWould you like to remove it from the list?`)) {
          forceDeleteMutation.mutate(jobId)
        }
      } else if (errorMsg.includes('Cannot cancel') || errorMsg.includes('status')) {
        alert(`Cannot cancel job: ${errorMsg}\n\nTry using the Delete button instead.`)
        queryClient.invalidateQueries({ queryKey: ['jobs'] })
      } else {
        alert(`Failed to cancel job: ${errorMsg}`)
      }
    },
  })

  // Force delete mutation for stale/orphaned jobs
  const forceDeleteMutation = useMutation({
    mutationFn: (jobId: string) => jobsApi.delete(jobId, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobStats'] })
    },
    onError: (error: Error) => {
      alert(`Failed to remove job: ${error.message}`)
    },
  })

  // Retry mutation
  const retryMutation = useMutation({
    mutationFn: jobsApi.retry,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobStats'] })
    },
  })

  // Delete mutation with error handling
  const deleteMutation = useMutation({
    mutationFn: (jobId: string) => jobsApi.delete(jobId, false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobStats'] })
    },
    onError: (error: unknown, jobId: string) => {
      // Extract error message from axios error response
      const axiosError = error as { response?: { data?: { detail?: string }, status?: number }, message?: string }
      const errorMsg = axiosError.response?.data?.detail || axiosError.message || 'Unknown error'
      const statusCode = axiosError.response?.status

      if (statusCode === 404 || errorMsg.includes('not found')) {
        // Job already gone, just refresh the list
        queryClient.invalidateQueries({ queryKey: ['jobs'] })
        queryClient.invalidateQueries({ queryKey: ['jobStats'] })
      } else if (statusCode === 400 || errorMsg.includes('Cannot delete active job') || errorMsg.includes('pending') || errorMsg.includes('Cancel the job first')) {
        // Offer force delete for stuck/stale active jobs
        if (confirm(`This job is in an active state but may be stale.\n\nWould you like to force delete it?`)) {
          forceDeleteMutation.mutate(jobId)
        }
      } else {
        alert(`Failed to delete job: ${errorMsg}`)
      }
    },
  })

  // Resume mutation (for paused jobs)
  const resumeMutation = useMutation({
    mutationFn: jobsApi.resume,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobStats'] })
    },
  })

  // Clear all mutation
  const clearAllMutation = useMutation({
    mutationFn: (includeActive: boolean) => jobsApi.clearAll(includeActive),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      queryClient.invalidateQueries({ queryKey: ['jobStats'] })
      alert(`Cleared ${data.deleted_count} job(s) from history`)
    },
  })

  const handleClearAll = () => {
    const hasActiveJobs = stats && (stats.running > 0 || stats.pending > 0)

    if (hasActiveJobs) {
      const confirmMsg = `There are ${stats.running + stats.pending} active jobs. Do you want to:\n\n` +
        `- Click OK to clear only completed/failed jobs\n` +
        `- Click Cancel, then use "Clear All (Including Active)" to cancel and clear everything`

      if (confirm(confirmMsg)) {
        clearAllMutation.mutate(false)
      }
    } else {
      if (confirm('Clear all job history? This cannot be undone.')) {
        clearAllMutation.mutate(false)
      }
    }
  }

  const handleClearAllIncludingActive = () => {
    const confirmMsg = `This will CANCEL all running jobs and clear ALL history. Are you sure?`

    if (confirm(confirmMsg)) {
      clearAllMutation.mutate(true)
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
            <FiCheckCircle className="mr-1" />
            Completed
          </span>
        )
      case 'running':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
            <FiActivity className="mr-1 animate-pulse" />
            Running
          </span>
        )
      case 'failed':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
            <FiAlertCircle className="mr-1" />
            Failed
          </span>
        )
      case 'paused':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
            <FiPause className="mr-1" />
            Paused
          </span>
        )
      case 'cancelled':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-[#0D1117] dark:text-gray-200">
            <FiX className="mr-1" />
            Cancelled
          </span>
        )
      case 'stalled':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200">
            <FiClock className="mr-1" />
            Stalled
          </span>
        )
      case 'pending':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200">
            <FiClock className="mr-1" />
            Pending
          </span>
        )
      case 'retrying':
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200">
            <FiRefreshCw className="mr-1" />
            Retrying
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-[#0D1117] dark:text-gray-200">
            {status}
          </span>
        )
    }
  }

  const jobTypeInfo: Record<string, { label: string; description: string }> = {
    artist_sync: {
      label: 'Artist Sync',
      description: 'Syncs artist metadata and album/track listings from MusicBrainz. Updates artist info, discovers new albums, and populates track listings.',
    },
    album_search: {
      label: 'Album Search',
      description: 'Searches Usenet indexers (Newznab) for NZB files matching a wanted album. Downloads the best matching NZB and sends it to SABnzbd.',
    },
    download_monitor: {
      label: 'Download Monitor',
      description: 'Monitors SABnzbd for completed downloads. Checks download status, detects failures, and triggers import when a download finishes.',
    },
    import_download: {
      label: 'Download Import',
      description: 'Imports completed downloads into your library. Moves files from the download directory to the correct artist/album folder and updates the database.',
    },
    library_scan: {
      label: 'Library Scan',
      description: 'Scans a library path for audio files and reads their metadata (tags, MBIDs). Updates the database with file locations and tag information.',
    },
    metadata_refresh: {
      label: 'Metadata Refresh',
      description: 'Refreshes artist metadata from external sources. Fetches biographies from Wikipedia, genres from MusicBrainz, and updates cover art.',
    },
    image_fetch: {
      label: 'Image Fetch',
      description: 'Downloads cover art images for albums and artist photos from MusicBrainz Cover Art Archive and other sources.',
    },
    cleanup: {
      label: 'Cleanup',
      description: 'Cleans up stale data such as orphaned records, expired jobs, and old log files.',
    },
    file_organization: {
      label: 'File Organization',
      description: 'General file organization task that renames and moves files into a standardized folder structure based on artist, album, and track metadata.',
    },
    scan: {
      label: 'Library Scan',
      description: 'Scans a library path for audio files and reads their metadata (tags, MBIDs). Updates the database with file locations and tag information.',
    },
    import: {
      label: 'Library Import',
      description: 'Imports new audio files found during a library scan. Reads metadata and creates or updates database records for discovered tracks.',
    },
    associate_and_organize: {
      label: 'Associate & Organize',
      description: 'Walks artist directories, reads file metadata, and matches files to database tracks using MBIDs, track numbers, and fuzzy title matching. Links matched files and optionally moves them to the correct folder structure.',
    },
    validate_structure: {
      label: 'Validate Structure',
      description: 'Checks that files on disk match the expected folder structure (Artist/Album/Track). Reports files that are misplaced, missing, or have incorrect naming.',
    },
    fetch_metadata: {
      label: 'Fetch Metadata',
      description: 'Searches MusicBrainz for files that are missing MBIDs. Matches files by artist, album, and track info, then writes the MBIDs to file comment tags.',
    },
    organize_library: {
      label: 'Organize Library',
      description: 'Renames and moves all files in a library path into the standard folder structure: Artist/Album (Year)/Artist - Album - TrackNum - Title.ext',
    },
    organize_artist: {
      label: 'Organize Artist',
      description: 'Renames and moves all files for a single artist into the standard folder structure.',
    },
    organize_album: {
      label: 'Organize Album',
      description: 'Renames and moves all files for a single album into the standard folder structure.',
    },
    rollback: {
      label: 'Rollback',
      description: 'Reverses a previous file organization job by moving files back to their original locations using the audit trail.',
    },
    validate_mbid: {
      label: 'Validate MBIDs',
      description: 'Reads audio files and verifies that MusicBrainz IDs stored in comment tags are valid and match the expected format (RecordingMBID, ReleaseMBID, etc.).',
    },
    validate_mbid_metadata: {
      label: 'Validate MBID Metadata',
      description: 'Cross-references MBIDs in file tags against the MusicBrainz database to ensure they point to the correct recordings, releases, and artists.',
    },
    link_files: {
      label: 'Link Files',
      description: 'Matches scanned library files to database tracks using MBIDs from file comment tags. Updates Track.file_path and has_file for matched tracks.',
    },
    reindex_albums: {
      label: 'Reindex Albums',
      description: 'Detects albums and singles from file metadata in a library path. Creates new album records for files that belong to albums not yet in the database.',
    },
    verify_audio: {
      label: 'Verify Audio',
      description: 'Verifies the integrity of recently downloaded audio files. Checks that files are valid, not corrupted, and can be decoded properly.',
    },
    library_migration: {
      label: 'Library Migration',
      description: 'Migrates files from one library path to another. Moves all audio files while preserving folder structure and updating database paths.',
    },
    migration_fingerprint: {
      label: 'Migration Fingerprint',
      description: 'Generates audio fingerprints for files during a library migration to help identify and match files across different locations.',
    },
  }

  const getJobTypeLabel = (jobType: string) => {
    return jobTypeInfo[jobType]?.label || jobType
  }

  const getJobTypeDescription = (jobType: string) => {
    return jobTypeInfo[jobType]?.description || ''
  }

  const formatDateTime = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const formatDuration = (start: string, end?: string) => {
    const startTime = new Date(start).getTime()
    const endTime = end ? new Date(end).getTime() : Date.now()
    const seconds = Math.floor((endTime - startTime) / 1000)

    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
  }

  const formatETA = (seconds?: number) => {
    if (!seconds) return ''
    if (seconds < 60) return `${seconds}s remaining`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m remaining`
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m remaining`
  }

  const formatSpeed = (speed?: number) => {
    if (!speed) return ''
    return `${speed.toFixed(2)} items/s`
  }

  const openLogViewer = async (job: Job) => {
    setSelectedJobForLog(job)
    setLogLoading(true)
    setLogContent('')
    try {
      const result = await jobsApi.getLogContent(job.id, { lines: 10000 })
      if (result.log_available) {
        setLogContent(result.content)
      } else {
        setLogContent('No log available for this job.')
      }
    } catch (error) {
      setLogContent('Error loading log: ' + (error instanceof Error ? error.message : 'Unknown error'))
    } finally {
      setLogLoading(false)
    }
  }

  const downloadLog = (job: Job) => {
    const url = jobsApi.getLogDownloadUrl(job.id)
    window.open(url, '_blank')
  }

  const closeLogViewer = () => {
    setSelectedJobForLog(null)
    setLogContent('')
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Activity</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">Monitor running jobs and view job history</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-[#30363D]">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('jobs')}
            className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
              activeTab === 'jobs'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Jobs
          </button>
          <button
            onClick={() => setActiveTab('downloads')}
            className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
              activeTab === 'downloads'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Downloads
          </button>
          {isDirector && (
            <button
              onClick={() => setActiveTab('queue-status')}
              className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
                activeTab === 'queue-status'
                  ? 'border-[#FF1493] text-[#FF1493]'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              Queue Status
            </button>
          )}
        </nav>
      </div>

      {/* Queue Status Tab */}
      {activeTab === 'queue-status' && isDirector && <QueueStatus />}

      {/* Downloads Tab */}
      {activeTab === 'downloads' && (
        <>
          {/* Filters */}
          <div className="card p-4">
            <div className="flex flex-wrap gap-4 items-end">
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Status</label>
                <select
                  value={dlStatusFilter}
                  onChange={(e) => { setDlStatusFilter(e.target.value); setDlPage(0) }}
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
                  value={dlDateFrom}
                  onChange={(e) => { setDlDateFrom(e.target.value); setDlPage(0) }}
                  className="input text-sm py-1.5"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">To</label>
                <input
                  type="date"
                  value={dlDateTo}
                  onChange={(e) => { setDlDateTo(e.target.value); setDlPage(0) }}
                  className="input text-sm py-1.5"
                />
              </div>
              {(dlStatusFilter || dlDateFrom || dlDateTo) && (
                <div className="flex flex-col justify-end">
                  <label className="block text-xs mb-1">&nbsp;</label>
                  <button
                    onClick={() => { setDlStatusFilter(''); setDlDateFrom(''); setDlDateTo(''); setDlPage(0) }}
                    className="text-sm text-[#FF1493] dark:text-[#ff4da6] hover:underline whitespace-nowrap"
                  >
                    Clear filters
                  </button>
                </div>
              )}
              {dlData && (
                <div className="flex flex-col justify-end ml-auto">
                  <label className="block text-xs mb-1">&nbsp;</label>
                  <span className="text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
                    {dlData.total.toLocaleString()} result{dlData.total !== 1 ? 's' : ''}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Table */}
          <div className="card overflow-hidden">
            {dlLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]" />
              </div>
            ) : dlError ? (
              <div className="text-center py-12 text-red-500 dark:text-red-400">
                Failed to load download history{dlErrorObj instanceof Error ? `: ${dlErrorObj.message}` : ''}
              </div>
            ) : !dlData || dlData.items.length === 0 ? (
              <div className="text-center py-12">
                <FiDownload className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-600" />
                <p className="mt-4 text-gray-500 dark:text-gray-400">No download history found</p>
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
                    {dlData.items.map((item) => {
                      const badge = DL_STATUS_BADGES[item.event_type] || {
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
                                to={`/albums/${item.album_id}`}
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
            {dlTotalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-[#30363D]">
                <button
                  onClick={() => setDlPage((p) => Math.max(0, p - 1))}
                  disabled={dlPage === 0}
                  className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <FiChevronLeft className="w-4 h-4" /> Previous
                </button>
                <span className="text-sm text-gray-600 dark:text-gray-400">
                  Page {dlPage + 1} of {dlTotalPages}
                </span>
                <button
                  onClick={() => setDlPage((p) => Math.min(dlTotalPages - 1, p + 1))}
                  disabled={dlPage >= dlTotalPages - 1}
                  className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Next <FiChevronRight className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>
        </>
      )}

      {/* Jobs Tab */}
      {activeTab === 'jobs' && <>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="card p-4">
            <div className="text-sm text-gray-600 dark:text-gray-400">Running</div>
            <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">{stats.running}</div>
          </div>
          <div className="card p-4">
            <div className="text-sm text-gray-600 dark:text-gray-400">Completed</div>
            <div className="text-2xl font-bold text-green-600 dark:text-green-400">{stats.completed}</div>
          </div>
          <div className="card p-4">
            <div className="text-sm text-gray-600 dark:text-gray-400">Failed</div>
            <div className="text-2xl font-bold text-red-600 dark:text-red-400">{stats.failed}</div>
          </div>
          <div className="card p-4">
            <div className="text-sm text-gray-600 dark:text-gray-400">Total</div>
            <div className="text-2xl font-bold text-gray-900 dark:text-white">{stats.total_jobs}</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="card p-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between space-y-4 sm:space-y-0">
          <div className="flex flex-col sm:flex-row items-start sm:items-center space-y-4 sm:space-y-0 sm:space-x-4">
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mr-2">Status:</label>
              <select
                className="input px-3 py-1.5 text-sm"
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
              >
                <option value="">All</option>
                <option value="running">Running</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="paused">Paused</option>
                <option value="stalled">Stalled</option>
                <option value="pending">Pending</option>
              </select>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-700 dark:text-gray-300 mr-2">Type:</label>
              <select
                className="input px-3 py-1.5 text-sm"
                value={typeFilter}
                onChange={(e) => { setTypeFilter(e.target.value); setPage(1) }}
              >
                <option value="">All</option>
                <optgroup label="Library & Media">
                  <option value="library_scan">Library Scan</option>
                  <option value="scan">Library Scan (Legacy)</option>
                  <option value="import">Library Import</option>
                  <option value="artist_sync">Artist Sync</option>
                  <option value="metadata_refresh">Metadata Refresh</option>
                  <option value="image_fetch">Image Fetch</option>
                </optgroup>
                <optgroup label="Search & Download">
                  <option value="album_search">Album Search</option>
                  <option value="download_monitor">Download Monitor</option>
                  <option value="import_download">Download Import</option>
                </optgroup>
                <optgroup label="File Management">
                  <option value="associate_and_organize">Associate & Organize</option>
                  <option value="organize_library">Organize Library</option>
                  <option value="organize_artist">Organize Artist</option>
                  <option value="organize_album">Organize Album</option>
                  <option value="validate_structure">Validate Structure</option>
                  <option value="fetch_metadata">Fetch Metadata</option>
                  <option value="validate_mbid">Validate MBIDs</option>
                  <option value="validate_mbid_metadata">Validate MBID Metadata</option>
                  <option value="link_files">Link Files</option>
                  <option value="reindex_albums">Reindex Albums</option>
                  <option value="verify_audio">Verify Audio</option>
                  <option value="rollback">Rollback</option>
                  <option value="library_migration">Library Migration</option>
                </optgroup>
                <optgroup label="System">
                  <option value="cleanup">Cleanup</option>
                </optgroup>
              </select>
            </div>
            {(statusFilter || typeFilter) && (
              <button
                className="btn btn-secondary btn-sm"
                onClick={() => {
                  setStatusFilter('')
                  setTypeFilter('')
                  setPage(1)
                }}
              >
                Clear Filters
              </button>
            )}
          </div>

          {/* Clear History Buttons */}
          <div className="flex items-center space-x-2">
            <button
              className="btn btn-danger btn-sm flex items-center space-x-2"
              onClick={handleClearAll}
              disabled={clearAllMutation.isPending}
            >
              <FiTrash2 className="h-4 w-4" />
              <span>Clear History</span>
            </button>
            {stats && (stats.running > 0 || stats.pending > 0) && (
              <button
                className="btn btn-danger btn-sm flex items-center space-x-2 opacity-75"
                onClick={handleClearAllIncludingActive}
                disabled={clearAllMutation.isPending}
                title="Cancel active jobs and clear all history"
              >
                <FiX className="h-4 w-4" />
                <span>Clear All (Inc. Active)</span>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Jobs Table */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
        </div>
      ) : jobs.length > 0 ? (
        <>
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-[#30363D]">
              <thead className="bg-gray-50 dark:bg-[#161B22]">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Job Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Progress
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Started / Duration
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white dark:bg-[#0D1117] divide-y divide-gray-200 dark:divide-[#30363D]">
                {jobs.map((job: Job) => (
                  <tr key={job.id} className="hover:bg-gray-50 dark:hover:bg-[#1C2128]">
                    <td className="px-6 py-4">
                      <div className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-1.5">
                        {getJobTypeLabel(job.job_type)}
                        {getJobTypeDescription(job.job_type) && (
                          <span className="relative group">
                            <FiInfo className="w-3.5 h-3.5 text-gray-400 dark:text-gray-500 cursor-help" />
                            <span className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-72 px-3 py-2 text-xs font-normal text-gray-200 bg-gray-800 dark:bg-[#0D1117] rounded-lg shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none z-50 leading-relaxed">
                              {getJobTypeDescription(job.job_type)}
                            </span>
                          </span>
                        )}
                      </div>
                      {job.current_step && (
                        <div className="text-sm text-gray-500 dark:text-gray-400 truncate max-w-xs">
                          {job.current_step}
                        </div>
                      )}
                      {job.error_message && (
                        <div className="mt-1 flex items-start space-x-2 max-w-2xl">
                          <div className="text-sm text-red-600 dark:text-red-400 break-words flex-1">
                            {job.error_message}
                          </div>
                          <button
                            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 flex-shrink-0"
                            onClick={() => {
                              const text = job.error_message || ''
                              if (navigator.clipboard && window.isSecureContext) {
                                navigator.clipboard.writeText(text)
                              } else {
                                const textarea = document.createElement('textarea')
                                textarea.value = text
                                textarea.style.position = 'fixed'
                                textarea.style.opacity = '0'
                                document.body.appendChild(textarea)
                                textarea.select()
                                document.execCommand('copy')
                                document.body.removeChild(textarea)
                              }
                            }}
                            title="Copy error message"
                          >
                            <FiCopy className="h-4 w-4" />
                          </button>
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4">{getStatusBadge(job.status)}</td>
                    <td className="px-6 py-4">
                      <div className="flex items-center space-x-3">
                        <div className="flex-1">
                          <div className="w-full bg-gray-200 dark:bg-[#0D1117] rounded-full h-2">
                            <div
                              className={`h-2 rounded-full transition-all duration-500 ${
                                job.status === 'failed' || job.status === 'stalled'
                                  ? 'bg-red-600'
                                  : job.status === 'completed'
                                  ? 'bg-green-600'
                                  : 'bg-blue-600'
                              }`}
                              style={{ width: `${job.progress_percent}%` }}
                            ></div>
                          </div>
                          <div className="mt-1 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                            <span>{job.progress_percent.toFixed(1)}%</span>
                            {job.items_total && (
                              <span>
                                {job.items_processed} / {job.items_total} items
                              </span>
                            )}
                          </div>
                          {job.eta_seconds && job.status === 'running' && (
                            <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                              {formatETA(job.eta_seconds)} {job.speed_metric && `· ${formatSpeed(job.speed_metric)}`}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">
                      {job.started_at ? (
                        <div>
                          <div className="font-medium text-gray-700 dark:text-gray-300">
                            {formatDateTime(job.started_at)}
                          </div>
                          <div className="text-xs">
                            {formatDuration(job.started_at, job.completed_at)}
                          </div>
                        </div>
                      ) : (
                        <span className="text-gray-400">Not started</span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right text-sm font-medium">
                      <div className="flex items-center justify-end space-x-2">
                        {/* Log viewing/download buttons */}
                        {job.log_file_path && (
                          <>
                            <button
                              className="text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-200"
                              onClick={() => openLogViewer(job)}
                              title="View Log"
                            >
                              <FiFileText className="h-5 w-5" />
                            </button>
                            <button
                              className="text-green-600 hover:text-green-900 dark:text-green-400 dark:hover:text-green-300"
                              onClick={() => downloadLog(job)}
                              title="Download Log"
                            >
                              <FiDownload className="h-5 w-5" />
                            </button>
                          </>
                        )}
                        {/* Resume/Cancel buttons for paused jobs */}
                        {job.status === 'paused' && (
                          <>
                            {job.job_type === 'fetch_metadata' && (
                              <button
                                className="inline-flex items-center px-2.5 py-1.5 text-xs font-medium rounded text-white bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600"
                                onClick={() => resumeMutation.mutate(job.id)}
                                disabled={resumeMutation.isPending}
                                title="Fetch metadata from MusicBrainz"
                              >
                                <FiSearch className="h-4 w-4 mr-1" />
                                Fetch Metadata
                              </button>
                            )}
                            <button
                              className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300"
                              onClick={() => cancelMutation.mutate(job.id)}
                              title="Cancel Job"
                            >
                              <FiX className="h-5 w-5" />
                            </button>
                          </>
                        )}
                        {job.status === 'running' && (
                          <button
                            className="text-yellow-600 hover:text-yellow-900 dark:text-yellow-400 dark:hover:text-yellow-300"
                            onClick={() => cancelMutation.mutate(job.id)}
                            disabled={cancelMutation.isPending}
                            title="Cancel Job"
                          >
                            <FiX className="h-5 w-5" />
                          </button>
                        )}
                        {job.status === 'pending' && (
                          <button
                            className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300"
                            onClick={() => cancelMutation.mutate(job.id)}
                            disabled={cancelMutation.isPending}
                            title="Cancel Pending Job"
                          >
                            <FiX className="h-5 w-5" />
                          </button>
                        )}
                        {(job.status === 'failed' || job.status === 'stalled' || job.status === 'cancelled') && (
                          <button
                            className="text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                            onClick={() => retryMutation.mutate(job.id)}
                            title="Retry Job"
                          >
                            <FiRefreshCw className="h-5 w-5" />
                          </button>
                        )}
                        {(job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled' || job.status === 'pending') && (
                          <button
                            className="text-red-600 hover:text-red-900 dark:text-red-400 dark:hover:text-red-300"
                            onClick={() => deleteMutation.mutate(job.id)}
                            disabled={deleteMutation.isPending}
                            title="Delete Job"
                          >
                            <FiTrash2 className="h-5 w-5" />
                          </button>
                        )}
                      </div>
                    </td>
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
          onPageChange={(p) => { setPage(p); window.scrollTo({ top: 0, behavior: 'smooth' }) }}
          onItemsPerPageChange={(pp) => { setItemsPerPage(pp); setPage(1) }}
        />
        </>
      ) : (
        <div className="card p-12 text-center">
          <FiActivity className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-600" />
          <p className="mt-4 text-gray-500 dark:text-gray-400">No jobs found</p>
          <p className="mt-2 text-sm text-gray-400 dark:text-gray-500">
            {statusFilter || typeFilter
              ? 'Try adjusting your filters'
              : 'Jobs will appear here as they are created'}
          </p>
        </div>
      )}

      </>}

      {/* Log Viewer Modal */}
      {selectedJobForLog && (
        <div className="fixed inset-0 z-50 overflow-y-auto">
          <div className="flex min-h-screen items-end justify-center px-4 pt-4 pb-20 text-center sm:block sm:p-0">
            {/* Backdrop */}
            <div
              className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity dark:bg-[#0D1117] dark:bg-opacity-75"
              onClick={closeLogViewer}
            ></div>

            {/* Modal panel */}
            <div className="inline-block transform overflow-hidden rounded-lg bg-white dark:bg-[#161B22] text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-5xl sm:align-middle">
              {/* Header */}
              <div className="bg-gray-50 dark:bg-[#0D1117] px-4 py-3 sm:px-6 flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-medium text-gray-900 dark:text-white">
                    Job Log: {getJobTypeLabel(selectedJobForLog.job_type)}
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Job ID: {selectedJobForLog.id}
                  </p>
                </div>
                <div className="flex items-center space-x-2">
                  <button
                    className="btn btn-secondary btn-sm flex items-center space-x-1"
                    onClick={() => downloadLog(selectedJobForLog)}
                    title="Download Log"
                  >
                    <FiDownload className="h-4 w-4" />
                    <span>Download</span>
                  </button>
                  <button
                    className="btn btn-secondary btn-sm flex items-center space-x-1"
                    onClick={() => {
                      if (navigator.clipboard && window.isSecureContext) {
                        navigator.clipboard.writeText(logContent)
                      } else {
                        const textarea = document.createElement('textarea')
                        textarea.value = logContent
                        textarea.style.position = 'fixed'
                        textarea.style.opacity = '0'
                        document.body.appendChild(textarea)
                        textarea.select()
                        document.execCommand('copy')
                        document.body.removeChild(textarea)
                      }
                    }}
                    title="Copy to Clipboard"
                  >
                    <FiCopy className="h-4 w-4" />
                    <span>Copy</span>
                  </button>
                  <button
                    className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                    onClick={closeLogViewer}
                  >
                    <FiX className="h-6 w-6" />
                  </button>
                </div>
              </div>

              {/* Log content */}
              <div className="px-4 py-4 sm:px-6 max-h-[70vh] overflow-y-auto">
                {logLoading ? (
                  <div className="flex justify-center py-12">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]"></div>
                  </div>
                ) : (
                  <pre className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap font-mono bg-gray-100 dark:bg-[#0D1117] p-4 rounded-lg overflow-x-auto">
                    {logContent || 'No log content available.'}
                  </pre>
                )}
              </div>

              {/* Footer */}
              <div className="bg-gray-50 dark:bg-[#0D1117] px-4 py-3 sm:px-6 flex justify-end">
                <button
                  className="btn btn-secondary"
                  onClick={closeLogViewer}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Activity
