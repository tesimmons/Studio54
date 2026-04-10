import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { libraryApi, jobsApi } from '../api/client'
import {
  FiFolder,
  FiPlus,
  FiX,
  FiRefreshCw,
  FiPlay,
  FiTrash2,
  FiSearch,
  FiDatabase,
  FiBarChart2,
  FiClock,
  FiCheck,
  FiFileText,
  FiDownload,
} from 'react-icons/fi'
import type { LibraryPath } from '../types'
import toast, { Toaster } from 'react-hot-toast'
import FileBrowser from '../components/FileBrowser'

interface LibraryScannerProps {
  libraryType?: 'music' | 'audiobook'
}

function Library({ libraryType }: LibraryScannerProps) {
  const [activeTab, setActiveTab] = useState<'paths' | 'scans' | 'search' | 'stats'>('paths')
  const [showAddModal, setShowAddModal] = useState(false)
  const [pathInput, setPathInput] = useState('')
  const [nameInput, setNameInput] = useState('')

  // Log viewer state
  const [selectedLogJobId, setSelectedLogJobId] = useState<string | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  // Search filters
  const [searchArtist, setSearchArtist] = useState('')
  const [searchAlbum, setSearchAlbum] = useState('')
  const [searchTitle, setSearchTitle] = useState('')

  const queryClient = useQueryClient()

  // Fetch library paths
  const { data: paths = [], isLoading: pathsLoading } = useQuery({
    queryKey: ['library-paths', libraryType],
    queryFn: () => libraryApi.listPaths(libraryType),
  })

  // Fetch recent scans
  const { data: scans = [], refetch: refetchScans } = useQuery({
    queryKey: ['library-scans', libraryType],
    queryFn: () => libraryApi.listScans(undefined, 20, libraryType),
  })

  // Fetch library stats
  const { data: stats } = useQuery({
    queryKey: ['library-stats', libraryType],
    queryFn: () => libraryApi.getStats(libraryType),
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  // Search files
  const { data: searchResults, isLoading: searchLoading } = useQuery({
    queryKey: ['library-files', libraryType, searchArtist, searchAlbum, searchTitle],
    queryFn: () => libraryApi.searchFiles({
      library_type: libraryType,
      artist: searchArtist || undefined,
      album: searchAlbum || undefined,
      title: searchTitle || undefined,
      limit: 100,
    }),
    enabled: !!(searchArtist || searchAlbum || searchTitle),
  })

  // Fetch log content for selected job
  const selectedScan = scans.find((s: any) => s.id === selectedLogJobId)
  const isRunning = selectedScan?.status === 'running' || selectedScan?.status === 'pending'
  const { data: logData } = useQuery({
    queryKey: ['job-log', selectedLogJobId],
    queryFn: () => jobsApi.getLogContent(selectedLogJobId!, { lines: 500, tail: true }),
    enabled: !!selectedLogJobId,
    refetchInterval: isRunning ? 3000 : false,
  })

  // Auto-scroll log to bottom on new content
  useEffect(() => {
    if (logData && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logData])

  // Add path mutation
  const addPathMutation = useMutation({
    mutationFn: (data: { path: string; name: string; library_type?: string }) => libraryApi.addPath(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-paths', libraryType] })
      setShowAddModal(false)
      setPathInput('')
      setNameInput('')
      toast.success('Library path added successfully')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to add library path'
      toast.error(message)
    },
  })

  // Delete path mutation
  const deletePathMutation = useMutation({
    mutationFn: (pathId: string) => libraryApi.deletePath(pathId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-paths', libraryType] })
      toast.success('Library path deleted successfully')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to delete library path'
      toast.error(message)
    },
  })

  // Start scan mutation
  const startScanMutation = useMutation({
    mutationFn: (pathId: string) => libraryApi.startScan(pathId, {
      incremental: true,
      fetch_images: true,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-scans', libraryType] })
      toast.success('Scan started successfully')
      setActiveTab('scans')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to start scan'
      toast.error(message)
    },
  })

  // Cancel scan mutation
  const cancelScanMutation = useMutation({
    mutationFn: (scanId: string) => libraryApi.cancelScan(scanId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-scans', libraryType] })
      toast.success('Scan cancelled')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to cancel scan'
      toast.error(message)
    },
  })


  // Rescan file mutation
  const rescanFileMutation = useMutation({
    mutationFn: (fileId: string) => libraryApi.rescanFile(fileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-files'] })
      toast.success('File rescanned successfully')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to rescan file'
      toast.error(message)
    },
  })

  // Rescan by album mutation
  const rescanByAlbumMutation = useMutation({
    mutationFn: ({ album, artist }: { album: string; artist?: string }) =>
      libraryApi.rescanByAlbum(album, artist),
    onSuccess: (data) => {
      toast.success(`Queued ${data.file_count} files for rescan`)
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to queue rescan'
      toast.error(message)
    },
  })

  // Rescan by artist mutation
  const rescanByArtistMutation = useMutation({
    mutationFn: (artist: string) => libraryApi.rescanByArtist(artist),
    onSuccess: (data) => {
      toast.success(`Queued ${data.file_count} files for rescan`)
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to queue rescan'
      toast.error(message)
    },
  })

  const handleAddPath = () => {
    if (!pathInput.trim() || !nameInput.trim()) {
      toast.error('Please provide both path and name')
      return
    }
    addPathMutation.mutate({
      path: pathInput,
      name: nameInput,
      library_type: libraryType,
    })
  }

  const handleDeletePath = (path: LibraryPath) => {
    const fileCount = path.total_files || 0
    const message = fileCount > 0
      ? `Delete library path "${path.name}"?\n\nThis will permanently remove ${fileCount.toLocaleString()} indexed file${fileCount === 1 ? '' : 's'} from the database.\n\nThis action cannot be undone!`
      : `Delete library path "${path.name}"?\n\nThis library has no indexed files.`

    if (confirm(message)) {
      deletePathMutation.mutate(path.id)
    }
  }

  const handleStartScan = (pathId: string) => {
    if (confirm('Start scanning this library path? This may take a while for large libraries.')) {
      startScanMutation.mutate(pathId)
    }
  }


  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
  }

  const formatDuration = (seconds: number | null): string => {
    if (!seconds) return '--:--'
    const minutes = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${minutes}:${secs.toString().padStart(2, '0')}`
  }

  const getScanStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return 'badge-success'
      case 'running':
        return 'badge-info'
      case 'failed':
        return 'badge-danger'
      default:
        return 'badge-secondary'
    }
  }

  // Auto-refresh scans when on scans tab
  useEffect(() => {
    if (activeTab === 'scans') {
      const interval = setInterval(() => {
        refetchScans()
      }, 5000) // Refresh every 5 seconds

      return () => clearInterval(interval)
    }
  }, [activeTab, refetchScans])

  return (
    <div className="space-y-6">
      <Toaster position="top-right" />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Library Scanner</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            Index and search your {libraryType === 'audiobook' ? 'audiobook' : 'music'} collection
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowAddModal(true)}>
          <FiPlus className="w-4 h-4 mr-2" />
          Add Library Path
        </button>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-[#30363D]">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('paths')}
            className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'paths'
                ? 'border-[#FF1493] text-[#FF1493] dark:text-[#ff4da6]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <FiFolder className="w-4 h-4 inline-block mr-2" />
            Library Paths
          </button>
          <button
            onClick={() => setActiveTab('scans')}
            className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'scans'
                ? 'border-[#FF1493] text-[#FF1493] dark:text-[#ff4da6]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <FiRefreshCw className="w-4 h-4 inline-block mr-2" />
            Scan History
          </button>
          <button
            onClick={() => setActiveTab('search')}
            className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'search'
                ? 'border-[#FF1493] text-[#FF1493] dark:text-[#ff4da6]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <FiSearch className="w-4 h-4 inline-block mr-2" />
            Search Files
          </button>
          <button
            onClick={() => setActiveTab('stats')}
            className={`py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'stats'
                ? 'border-[#FF1493] text-[#FF1493] dark:text-[#ff4da6]'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            <FiBarChart2 className="w-4 h-4 inline-block mr-2" />
            Statistics
          </button>
        </nav>
      </div>

      {/* Tab Content */}
      <div>
        {/* Library Paths Tab */}
        {activeTab === 'paths' && (
          <div className="space-y-4">
            {pathsLoading ? (
              <div className="flex justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
              </div>
            ) : paths.length > 0 ? (
              paths.map((path) => (
                <div key={path.id} className="card p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center space-x-3 mb-2">
                        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                          {path.name}
                        </h3>
                        {path.is_enabled ? (
                          <span className="badge badge-success">Enabled</span>
                        ) : (
                          <span className="badge badge-secondary">Disabled</span>
                        )}
                      </div>
                      <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                        {path.path}
                      </p>
                      <div className="grid grid-cols-3 gap-4 text-sm">
                        <div>
                          <span className="text-gray-500 dark:text-gray-400">Files:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {path.total_files.toLocaleString()}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500 dark:text-gray-400">Size:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {formatBytes(path.total_size_bytes)}
                          </span>
                        </div>
                        <div>
                          <span className="text-gray-500 dark:text-gray-400">Last Scan:</span>
                          <span className="ml-2 font-medium text-gray-900 dark:text-white">
                            {path.last_scan_at
                              ? new Date(path.last_scan_at).toLocaleDateString()
                              : 'Never'}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex space-x-2 ml-4">
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => handleStartScan(path.id)}
                        disabled={!path.is_enabled || startScanMutation.isPending}
                      >
                        {startScanMutation.isPending ? (
                          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                        ) : (
                          <>
                            <FiPlay className="w-4 h-4 mr-2" />
                            Scan
                          </>
                        )}
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => handleDeletePath(path)}
                      >
                        <FiTrash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="card p-12 text-center">
                <FiFolder className="w-16 h-16 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
                <p className="text-gray-500 dark:text-gray-400 mb-4">
                  No library paths configured
                </p>
                <button className="btn btn-primary" onClick={() => setShowAddModal(true)}>
                  Add Your First Library Path
                </button>
              </div>
            )}
          </div>
        )}

        {/* Scan History Tab */}
        {activeTab === 'scans' && (
          <div className="card overflow-hidden">
            {scans.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 dark:bg-[#161B22]">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                        Status
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                        Progress
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                        Files
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                        Started
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                        Duration
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-[#0D1117] divide-y divide-gray-200 dark:divide-[#30363D]">
                    {scans.map((scan) => {
                      const filesProcessed = scan.files_added + scan.files_updated + scan.files_skipped + scan.files_failed
                      const progress = scan.files_scanned > 0 ? (filesProcessed / scan.files_scanned) * 100 : 0

                      return (
                        <tr key={scan.id} className="hover:bg-gray-50 dark:hover:bg-[#1C2128]">
                          <td className="px-4 py-3">
                            <span className={`badge ${getScanStatusBadge(scan.status)}`}>
                              {scan.status}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            {scan.status === 'running' || scan.status === 'pending' ? (
                              <div className="space-y-1">
                                <div className="flex items-center justify-between text-xs text-gray-600 dark:text-gray-400">
                                  <span>{filesProcessed.toLocaleString()} / {scan.files_scanned.toLocaleString()}</span>
                                  <span>{Math.round(progress)}%</span>
                                </div>
                                <div className="w-full bg-gray-200 dark:bg-[#0D1117] rounded-full h-2">
                                  <div
                                    className="bg-[#FF1493] h-2 rounded-full transition-all duration-300"
                                    style={{ width: `${Math.min(progress, 100)}%` }}
                                  />
                                </div>
                              </div>
                            ) : (
                              <span className="text-sm text-gray-900 dark:text-white">
                                {scan.files_scanned.toLocaleString()} scanned
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <div className="text-xs space-y-0.5">
                              <div className="text-gray-900 dark:text-white">
                                <span className="text-green-600 dark:text-green-400 font-medium">{scan.files_added}</span> added
                              </div>
                              <div className="text-gray-600 dark:text-gray-400">
                                <span className="font-medium">{scan.files_updated}</span> updated,
                                <span className="font-medium ml-1">{scan.files_skipped}</span> skipped
                                {scan.files_failed > 0 && (
                                  <>, <span className="text-red-600 font-medium">{scan.files_failed}</span> failed</>
                                )}
                              </div>
                            </div>
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            {scan.started_at
                              ? new Date(scan.started_at).toLocaleString()
                              : '-'}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            {scan.duration_seconds
                              ? `${Math.round(scan.duration_seconds)}s`
                              : scan.status === 'running'
                              ? 'In progress...'
                              : '-'}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => setSelectedLogJobId(scan.id)}
                                className="btn btn-sm btn-secondary"
                                title="View log"
                              >
                                <FiFileText className="w-4 h-4" />
                              </button>
                              {(scan.status === 'running' || scan.status === 'pending') && (
                                <button
                                  onClick={() => cancelScanMutation.mutate(scan.id)}
                                  disabled={cancelScanMutation.isPending}
                                  className="btn btn-sm btn-secondary"
                                  title="Cancel scan"
                                >
                                  Cancel
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-12 text-center">
                <FiClock className="w-16 h-16 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
                <p className="text-gray-500 dark:text-gray-400">
                  No scans yet. Start scanning a library path to see history here.
                </p>
              </div>
            )}
          </div>
        )}

        {/* Search Files Tab */}
        {activeTab === 'search' && (
          <div className="space-y-4">
            <div className="card p-4 space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <input
                  type="text"
                  placeholder="Search by artist..."
                  className="input"
                  value={searchArtist}
                  onChange={(e) => setSearchArtist(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="Search by album..."
                  className="input"
                  value={searchAlbum}
                  onChange={(e) => setSearchAlbum(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="Search by title..."
                  className="input"
                  value={searchTitle}
                  onChange={(e) => setSearchTitle(e.target.value)}
                />
              </div>

              {/* Rescan by Album/Artist */}
              <div className="flex items-center space-x-2 pt-2 border-t border-gray-200 dark:border-[#30363D]">
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Bulk Rescan:</span>
                <button
                  onClick={() => {
                    if (searchAlbum && confirm(`Rescan all files for album "${searchAlbum}"?`)) {
                      rescanByAlbumMutation.mutate({ album: searchAlbum, artist: searchArtist || undefined })
                    } else if (!searchAlbum) {
                      toast.error('Enter an album name to rescan by album')
                    }
                  }}
                  disabled={rescanByAlbumMutation.isPending || !searchAlbum}
                  className="btn btn-sm btn-secondary"
                >
                  Rescan by Album
                </button>
                <button
                  onClick={() => {
                    if (searchArtist && confirm(`Rescan all files for artist "${searchArtist}"?`)) {
                      rescanByArtistMutation.mutate(searchArtist)
                    } else if (!searchArtist) {
                      toast.error('Enter an artist name to rescan by artist')
                    }
                  }}
                  disabled={rescanByArtistMutation.isPending || !searchArtist}
                  className="btn btn-sm btn-secondary"
                >
                  Rescan by Artist
                </button>
              </div>
            </div>

            {searchLoading ? (
              <div className="flex justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
              </div>
            ) : searchResults && searchResults.items.length > 0 ? (
              <div className="card overflow-hidden">
                <div className="p-4 border-b border-gray-200 dark:border-[#30363D]">
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    Found {searchResults.total_count.toLocaleString()} files
                  </p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-gray-50 dark:bg-[#161B22]">
                      <tr>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                          Title
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                          Artist
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                          Album
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                          Year
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                          Format
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                          Duration
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                          MusicBrainz
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-[#0D1117] divide-y divide-gray-200 dark:divide-[#30363D]">
                      {searchResults.items.map((file) => (
                        <tr key={file.id} className="hover:bg-gray-50 dark:hover:bg-[#1C2128]">
                          <td className="px-4 py-3 text-sm text-gray-900 dark:text-white">
                            {file.title || '-'}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            {file.artist || '-'}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            {file.album || '-'}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            {file.year || '-'}
                          </td>
                          <td className="px-4 py-3">
                            <span className="badge badge-info">{file.format || '-'}</span>
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
                            {formatDuration(file.duration_seconds)}
                          </td>
                          <td className="px-4 py-3">
                            {file.musicbrainz_trackid ? (
                              <FiCheck className="w-4 h-4 text-green-600" title="Has MusicBrainz ID" />
                            ) : (
                              <FiX className="w-4 h-4 text-gray-400" />
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <button
                              onClick={() => rescanFileMutation.mutate(file.id)}
                              disabled={rescanFileMutation.isPending}
                              className="btn btn-sm btn-secondary"
                              title="Rescan file to refresh metadata"
                            >
                              <FiRefreshCw className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="card p-12 text-center">
                <FiSearch className="w-16 h-16 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
                <p className="text-gray-500 dark:text-gray-400">
                  {searchArtist || searchAlbum || searchTitle
                    ? 'No files found matching your search'
                    : 'Enter search criteria to find files'}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Statistics Tab */}
        {activeTab === 'stats' && stats && (
          <div className="space-y-6">
            {/* Overview Stats */}
            <div className="grid grid-cols-4 gap-4">
              <div className="card p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Total Files</p>
                    <p className="text-3xl font-bold text-gray-900 dark:text-white mt-2">
                      {stats.total_files.toLocaleString()}
                    </p>
                  </div>
                  <FiDatabase className="w-10 h-10 text-[#FF1493]" />
                </div>
              </div>

              <div className="card p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Total Size</p>
                    <p className="text-3xl font-bold text-gray-900 dark:text-white mt-2">
                      {stats.total_size_gb.toFixed(1)} GB
                    </p>
                  </div>
                  <FiFolder className="w-10 h-10 text-[#FF1493]" />
                </div>
              </div>

              <div className="card p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Library Paths</p>
                    <p className="text-3xl font-bold text-gray-900 dark:text-white mt-2">
                      {stats.total_library_paths}
                    </p>
                  </div>
                  <FiFolder className="w-10 h-10 text-[#FF1493]" />
                </div>
              </div>

              <div className="card p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">MB Coverage</p>
                    <p className="text-3xl font-bold text-gray-900 dark:text-white mt-2">
                      {stats.musicbrainz_coverage.track_coverage_percent}%
                    </p>
                  </div>
                  <FiCheck className="w-10 h-10 text-green-600" />
                </div>
              </div>
            </div>

            {/* Formats */}
            <div className="card p-6">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                File Formats
              </h3>
              <div className="grid grid-cols-4 gap-4">
                {stats.formats.map((format) => (
                  <div key={format.format} className="p-4 bg-gray-50 dark:bg-[#161B22] rounded-lg">
                    <p className="text-sm text-gray-500 dark:text-gray-400">{format.format}</p>
                    <p className="text-2xl font-bold text-gray-900 dark:text-white mt-1">
                      {format.count.toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* MusicBrainz Coverage */}
            <div className="card p-6">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                MusicBrainz Coverage
              </h3>
              <div className="space-y-4">
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-gray-600 dark:text-gray-400">Tracks with MB ID</span>
                    <span className="font-medium text-gray-900 dark:text-white">
                      {stats.musicbrainz_coverage.tracks_with_mb_id.toLocaleString()} /{' '}
                      {stats.total_files.toLocaleString()}
                    </span>
                  </div>
                  <div className="w-full bg-gray-200 dark:bg-[#0D1117] rounded-full h-2">
                    <div
                      className="bg-green-600 h-2 rounded-full"
                      style={{
                        width: `${stats.musicbrainz_coverage.track_coverage_percent}%`,
                      }}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 mt-4">
                  <div className="p-3 bg-gray-50 dark:bg-[#161B22] rounded">
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      Albums with MB ID
                    </p>
                    <p className="text-xl font-bold text-gray-900 dark:text-white mt-1">
                      {stats.musicbrainz_coverage.albums_with_mb_id.toLocaleString()}
                    </p>
                  </div>
                  <div className="p-3 bg-gray-50 dark:bg-[#161B22] rounded">
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      Artists with MB ID
                    </p>
                    <p className="text-xl font-bold text-gray-900 dark:text-white mt-1">
                      {stats.musicbrainz_coverage.artists_with_mb_id.toLocaleString()}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Log Viewer Modal */}
      {selectedLogJobId && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-4xl w-full max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-[#30363D]">
              <div className="flex items-center gap-3">
                <h2 className="text-lg font-bold text-gray-900 dark:text-white">
                  Scan Job Log
                </h2>
                {isRunning && (
                  <span className="badge badge-info text-xs">Live</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={jobsApi.getLogDownloadUrl(selectedLogJobId)}
                  download
                  className="btn btn-sm btn-secondary"
                  title="Download log"
                >
                  <FiDownload className="w-4 h-4" />
                </a>
                <button
                  onClick={() => setSelectedLogJobId(null)}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                >
                  <FiX className="w-6 h-6" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4 bg-gray-900">
              {logData?.log_available === false ? (
                <p className="text-gray-400 text-center py-8">No log available for this job.</p>
              ) : logData?.content ? (
                <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-words leading-relaxed">
                  {logData.content}
                  <div ref={logEndRef} />
                </pre>
              ) : (
                <p className="text-gray-400 text-center py-8">Loading log...</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Add Library Path Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-3xl w-full p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
                Add Library Path
              </h2>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              >
                <FiX className="w-6 h-6" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Name *
                </label>
                <input
                  type="text"
                  className="input w-full"
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  placeholder={libraryType === 'audiobook' ? 'My Audiobook Collection' : 'My Music Collection'}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Path *
                </label>
                <input
                  type="text"
                  className="input w-full"
                  value={pathInput}
                  onChange={(e) => setPathInput(e.target.value)}
                  placeholder={libraryType === 'audiobook' ? '/path/to/audiobooks' : '/path/to/music'}
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Absolute path to your {libraryType === 'audiobook' ? 'audiobook' : 'music'} directory
                </p>
              </div>

              {/* File Browser */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Browse Filesystem
                </label>
                <FileBrowser
                  onSelect={(path) => setPathInput(path)}
                  initialPath={pathInput || '/'}
                />
              </div>

              <div className="flex space-x-3 pt-4">
                <button
                  className="btn btn-secondary flex-1"
                  onClick={() => setShowAddModal(false)}
                >
                  Cancel
                </button>
                <button
                  className="btn btn-primary flex-1"
                  onClick={handleAddPath}
                  disabled={addPathMutation.isPending}
                >
                  {addPathMutation.isPending ? 'Adding...' : 'Add Path'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Library
