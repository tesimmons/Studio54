import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { authFetch } from '../api/client'
import { FiPlay, FiX, FiAlertCircle, FiCheckCircle, FiClock, FiUsers, FiDisc, FiMusic } from 'react-icons/fi'

interface ImportJob {
  id: string
  library_path_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  current_phase: string | null
  progress_percent: number
  current_action: string | null
  phases: {
    scanning: string
    artist_matching: string
    metadata_sync: string
    folder_matching: string
    track_matching: string
    enrichment: string
    finalization: string
  }
  statistics: {
    files_scanned: number
    artists_found: number
    artists_matched: number
    artists_created: number
    artists_pending: number
    albums_synced: number
    tracks_matched: number
    tracks_unmatched: number
  }
  configuration: {
    auto_match_artists: boolean
    auto_assign_folders: boolean
    auto_match_tracks: boolean
    confidence_threshold: number
  }
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  duration_seconds: number | null
}

interface LibraryPath {
  id: string
  name: string
  path: string
  total_files: number
  is_enabled: boolean
}

function LibraryImport() {
  const [selectedLibrary] = useState<string | null>(null)
  const [selectedJob, setSelectedJob] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)

  // Fetch library paths
  const { data: libraryPaths } = useQuery<{ library_paths: LibraryPath[] }>({
    queryKey: ['library-paths'],
    queryFn: async () => {
      const response = await authFetch('/api/v1/library/paths')
      if (!response.ok) throw new Error('Failed to fetch library paths')
      return response.json()
    },
  })

  // Fetch import jobs
  const { data: importsData, refetch: refetchImports } = useQuery<{ imports: ImportJob[] }>({
    queryKey: ['library-imports', selectedLibrary],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (selectedLibrary) params.append('library_path_id', selectedLibrary)
      const response = await authFetch(`/api/v1/library/imports?${params}`)
      if (!response.ok) throw new Error('Failed to fetch imports')
      return response.json()
    },
    refetchInterval: autoRefresh ? 5000 : false,
  })

  // Fetch detailed import job status
  const { data: jobDetails, refetch: refetchJobDetails } = useQuery<ImportJob>({
    queryKey: ['library-import-detail', selectedJob],
    queryFn: async () => {
      if (!selectedJob) throw new Error('No job selected')
      const response = await authFetch(`/api/v1/library/imports/${selectedJob}`)
      if (!response.ok) throw new Error('Failed to fetch import details')
      return response.json()
    },
    enabled: !!selectedJob,
    refetchInterval: autoRefresh && selectedJob ? 3000 : false,
  })

  // Auto-select first running job
  useEffect(() => {
    if (importsData?.imports && !selectedJob) {
      const runningJob = importsData.imports.find(j => j.status === 'running')
      if (runningJob) {
        setSelectedJob(runningJob.id)
      }
    }
  }, [importsData, selectedJob])

  const startImport = async (libraryPathId: string) => {
    try {
      const response = await authFetch(`/api/v1/library/paths/${libraryPathId}/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          auto_match_artists: true,
          auto_assign_folders: true,
          auto_match_tracks: true,
          confidence_threshold: 85,
        }),
      })
      if (!response.ok) {
        const error = await response.json()
        alert(error.detail || 'Failed to start import')
        return
      }
      const result = await response.json()
      setSelectedJob(result.import_job_id)
      refetchImports()
    } catch (error) {
      console.error('Failed to start import:', error)
      alert('Failed to start import')
    }
  }

  const cancelImport = async (jobId: string) => {
    try {
      await authFetch(`/api/v1/library/imports/${jobId}/cancel`, { method: 'POST' })
      refetchImports()
      refetchJobDetails()
    } catch (error) {
      console.error('Failed to cancel import:', error)
    }
  }

  const getPhaseIcon = (phase: string) => {
    switch (phase) {
      case 'completed': return <FiCheckCircle className="text-green-500" />
      case 'running': return <FiClock className="text-blue-500 animate-pulse" />
      case 'failed': return <FiAlertCircle className="text-red-500" />
      default: return <FiClock className="text-gray-400 dark:text-gray-500" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running': return 'text-blue-600 bg-blue-50 dark:text-blue-400 dark:bg-blue-900/20'
      case 'completed': return 'text-green-600 bg-green-50 dark:text-green-400 dark:bg-green-900/20'
      case 'failed': return 'text-red-600 bg-red-50 dark:text-red-400 dark:bg-red-900/20'
      case 'cancelled': return 'text-gray-600 bg-gray-50 dark:text-gray-400 dark:bg-[#0D1117]'
      default: return 'text-gray-600 bg-gray-50 dark:text-gray-400 dark:bg-[#0D1117]'
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Library Import</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Scan files and import artists, albums, and tracks via MusicBrainz
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
            className="rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
          />
          Auto-refresh
        </label>
      </div>

      {/* Start New Import */}
      <div className="card p-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Start New Import</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {libraryPaths?.library_paths?.map((lib) => (
            <div key={lib.id} className="border border-gray-200 dark:border-[#30363D] rounded-lg p-4 hover:border-[#FF1493] transition">
              <div className="flex justify-between items-start mb-2">
                <div>
                  <h3 className="font-semibold text-gray-900 dark:text-white">{lib.name}</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400 truncate">{lib.path}</p>
                </div>
                {lib.is_enabled && (
                  <button
                    onClick={() => startImport(lib.id)}
                    className="btn btn-primary btn-sm"
                  >
                    <FiPlay className="w-4 h-4 mr-1" />
                    Import
                  </button>
                )}
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
                {lib.total_files.toLocaleString()} files indexed
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Import Job Details */}
      {jobDetails && (
        <div className="card p-6">
          <div className="flex justify-between items-start mb-6">
            <div>
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Import Progress</h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                {libraryPaths?.library_paths?.find(l => l.id === jobDetails.library_path_id)?.name || 'Library'}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${getStatusColor(jobDetails.status)}`}>
                {jobDetails.status.toUpperCase()}
              </span>
              {jobDetails.status === 'running' && (
                <button
                  onClick={() => cancelImport(jobDetails.id)}
                  className="btn btn-danger btn-sm"
                >
                  <FiX className="w-4 h-4 mr-1" />
                  Cancel
                </button>
              )}
            </div>
          </div>

          {/* Progress Bar */}
          <div className="mb-6">
            <div className="flex justify-between text-sm text-gray-600 dark:text-gray-400 mb-2">
              <span>{jobDetails.current_action || 'Initializing...'}</span>
              <span>{jobDetails.progress_percent.toFixed(1)}%</span>
            </div>
            <div className="w-full bg-gray-200 dark:bg-[#0D1117] rounded-full h-3 overflow-hidden">
              <div
                className="bg-[#FF1493] h-full transition-all duration-500 ease-out rounded-full"
                style={{ width: `${jobDetails.progress_percent}%` }}
              />
            </div>
          </div>

          {/* Phases */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            {Object.entries(jobDetails.phases).map(([phase, status]) => (
              <div key={phase} className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-[#161B22] rounded">
                {getPhaseIcon(status)}
                <div className="flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-white capitalize">
                    {phase.replace(/_/g, ' ')}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 capitalize">{status}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Statistics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-blue-50 dark:bg-blue-900/20 p-4 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <FiMusic className="text-blue-600 dark:text-blue-400" />
                <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Files Scanned</span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {jobDetails.statistics.files_scanned.toLocaleString()}
              </p>
            </div>

            <div className="bg-green-50 dark:bg-green-900/20 p-4 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <FiUsers className="text-green-600 dark:text-green-400" />
                <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Artists</span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {jobDetails.statistics.artists_matched} / {jobDetails.statistics.artists_found}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {jobDetails.statistics.artists_created} created, {jobDetails.statistics.artists_pending} pending
              </p>
            </div>

            <div className="bg-purple-50 dark:bg-purple-900/20 p-4 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <FiDisc className="text-purple-600 dark:text-purple-400" />
                <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Albums Synced</span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {jobDetails.statistics.albums_synced.toLocaleString()}
              </p>
            </div>

            <div className="bg-yellow-50 dark:bg-yellow-900/20 p-4 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <FiMusic className="text-yellow-600 dark:text-yellow-400" />
                <span className="text-sm font-medium text-gray-600 dark:text-gray-400">Tracks Matched</span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                {jobDetails.statistics.tracks_matched.toLocaleString()}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {jobDetails.statistics.tracks_unmatched} unmatched
              </p>
            </div>
          </div>

          {/* Error Message */}
          {jobDetails.error_message && (
            <div className="mt-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
              <div className="flex items-start gap-2">
                <FiAlertCircle className="text-red-600 dark:text-red-400 mt-0.5" />
                <div>
                  <p className="font-medium text-red-800 dark:text-red-300">Error</p>
                  <p className="text-sm text-red-600 dark:text-red-400 mt-1">{jobDetails.error_message}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Recent Imports */}
      <div className="card p-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">Recent Imports</h2>
        {importsData?.imports && importsData.imports.length > 0 ? (
          <div className="space-y-2">
            {importsData.imports.slice(0, 10).map((job) => (
              <div
                key={job.id}
                onClick={() => setSelectedJob(job.id)}
                className={`p-4 border rounded-lg cursor-pointer hover:border-[#FF1493] transition ${
                  selectedJob === job.id
                    ? 'border-[#FF1493] bg-[#FF1493]/5 dark:bg-[#FF1493]/10'
                    : 'border-gray-200 dark:border-[#30363D]'
                }`}
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${getStatusColor(job.status)}`}>
                        {job.status}
                      </span>
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {job.progress_percent.toFixed(1)}%
                      </span>
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400">{job.current_action || 'Waiting...'}</p>
                  </div>
                  <div className="text-right text-sm text-gray-500 dark:text-gray-400">
                    {job.started_at && (
                      <p>{new Date(job.started_at).toLocaleString()}</p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8">
            <FiMusic className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-3" />
            <p className="text-gray-500 dark:text-gray-400">No imports yet. Select a library above to start.</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default LibraryImport
