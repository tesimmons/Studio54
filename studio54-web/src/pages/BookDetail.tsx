import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast, { Toaster } from 'react-hot-toast'
import { booksApi, bookProgressApi, fileOrganizationApi, jobsApi, authorsApi, authFetch } from '../api/client'
import type { Job } from '../api/client'
import { usePlayer, type PlayerTrack } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import FileBrowserModal from '../components/FileBrowserModal'
import CoverArtUploader from '../components/CoverArtUploader'
import {
  FiArrowLeft,
  FiRefreshCw,
  FiCheck,
  FiCheckCircle,
  FiX,
  FiCalendar,
  FiPlay,
  FiPlus,
  FiSearch,
  FiClock,
  FiFolder,
  FiEdit2,
  FiSave,
  FiLoader,
  FiBook,
  FiChevronDown,
  FiChevronUp,
  FiChevronLeft,
  FiChevronRight,
  FiMoreVertical,
  FiBookOpen,
  FiLink,
  FiRotateCcw,
} from 'react-icons/fi'
import { S54 } from '../assets/graphics'

interface Chapter {
  id: string
  title: string
  chapter_number: number
  disc_number: number
  duration_ms: number | null
  has_file: boolean
  file_path: string | null
  musicbrainz_id: string | null
}

interface BookWithChapters {
  id: string
  title: string
  author_id: string
  author_name: string
  musicbrainz_id: string | null
  release_mbid: string | null
  release_date: string | null
  album_type: string | null
  status: string
  monitored: boolean
  cover_art_url: string | null
  credit_name: string | null
  custom_folder_path: string | null
  chapter_count: number
  series_id: string | null
  series_name: string | null
  series_position: number | null
  related_series: string | null
  added_at: string | null
  updated_at: string | null
  chapters: Chapter[]
  downloads?: any[]
}

interface SeriesBook {
  id: string
  title: string
  series_position: number | null
}

function BookDetail() {
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
  const [showMobileActions, setShowMobileActions] = useState(false)
  const [expandedChapterId, setExpandedChapterId] = useState<string | null>(null)
  const [isEditingRelatedSeries, setIsEditingRelatedSeries] = useState(false)
  const [relatedSeriesText, setRelatedSeriesText] = useState('')
  const [showEditMetadataModal, setShowEditMetadataModal] = useState(false)
  const [editMetaTitle, setEditMetaTitle] = useState('')
  const [editMetaAuthor, setEditMetaAuthor] = useState('')
  const [tagWriteJobId, setTagWriteJobId] = useState<string | null>(null)

  // Bulk chapter selection state
  const [bulkChapterMode, setBulkChapterMode] = useState(false)
  const [selectedChapterIds, setSelectedChapterIds] = useState<Set<string>>(new Set())

  const toggleChapterSelection = useCallback((chapterId: string) => {
    setSelectedChapterIds(prev => {
      const next = new Set(prev)
      if (next.has(chapterId)) next.delete(chapterId)
      else next.add(chapterId)
      return next
    })
  }, [])

  const toggleSelectAllChapters = useCallback((chapters: Chapter[]) => {
    setSelectedChapterIds(prev => {
      if (prev.size === chapters.length) return new Set()
      return new Set(chapters.map(c => c.id))
    })
  }, [])

  // Active job tracking for this book
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  // Poll for active jobs for this book
  const { data: activeJobs } = useQuery({
    queryKey: ['book-jobs', id],
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
      queryClient.invalidateQueries({ queryKey: ['book', id] })
      queryClient.invalidateQueries({ queryKey: ['book-jobs', id] })
    } else if (trackedJob.status === 'failed') {
      toast.error(`Job failed: ${trackedJob.error_message || 'Unknown error'}`)
      setActiveJobId(null)
      queryClient.invalidateQueries({ queryKey: ['book-jobs', id] })
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

  // Fetch book details with chapters - auto-refresh when downloading/searching
  const { data: book, isLoading, refetch } = useQuery({
    queryKey: ['book', id],
    queryFn: async (): Promise<BookWithChapters> => {
      const response = await authFetch(`/api/v1/books/${id}`)
      if (!response.ok) throw new Error('Failed to fetch book')
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

  // Fetch user's playback progress for resume
  const { data: bookProgress, refetch: refetchProgress } = useQuery({
    queryKey: ['book-progress', id],
    queryFn: () => bookProgressApi.get(id!),
    enabled: !!id,
  })

  // Mark book as finished/unfinished
  const markFinishedMutation = useMutation({
    mutationFn: async (completed: boolean) => {
      if (!bookProgress?.chapter_id) {
        // No progress yet — create one with the first chapter
        const firstChapter = book?.chapters?.[0]
        if (!firstChapter) throw new Error('No chapters')
        return bookProgressApi.upsert(id!, {
          chapter_id: firstChapter.id,
          position_ms: 0,
          completed,
        })
      }
      return bookProgressApi.upsert(id!, {
        chapter_id: bookProgress.chapter_id,
        position_ms: bookProgress.position_ms || 0,
        completed,
      })
    },
    onSuccess: () => {
      toast.success(markFinishedMutation.variables ? 'Marked as finished' : 'Marked as unfinished')
      queryClient.invalidateQueries({ queryKey: ['book-progress', id] })
    },
    onError: () => {
      toast.error('Failed to update progress')
    },
  })

  // Reset progress
  const resetProgressMutation = useMutation({
    mutationFn: async () => {
      return bookProgressApi.reset(id!)
    },
    onSuccess: () => {
      toast.success('Progress reset')
      queryClient.invalidateQueries({ queryKey: ['book-progress', id] })
    },
    onError: () => {
      toast.error('Failed to reset progress')
    },
  })

  // Fetch series books for prev/next navigation
  const { data: seriesBooks } = useQuery({
    queryKey: ['series-books', book?.series_id],
    queryFn: async (): Promise<SeriesBook[]> => {
      const response = await authFetch(`/api/v1/series/${book!.series_id}`)
      if (!response.ok) return []
      const data = await response.json()
      return (data.books || []).sort((a: SeriesBook, b: SeriesBook) =>
        (a.series_position ?? 999) - (b.series_position ?? 999)
      )
    },
    enabled: !!book?.series_id,
  })

  // Update book monitoring
  const updateMonitoringMutation = useMutation({
    mutationFn: async (monitored: boolean) => {
      return booksApi.update(id!, { monitored })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['book', id] })
      queryClient.invalidateQueries({ queryKey: ['author'] })
    }
  })

  // Manual search mutation
  const manualSearchMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch(`/api/v1/books/${id}/search`, {
        method: 'POST'
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to search for book')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['book', id] })
      if (data.success === false) {
        toast.error(data.error || data.message || 'Search failed')
      } else {
        toast.success(data.message || 'Book search started - tracking progress...')
        if (data.download_task_id) {
          const findJob = async () => {
            const result = await jobsApi.list({ entity_id: id!, status: 'running', limit: 5 })
            const job = result.jobs?.find((j: Job) => j.celery_task_id === data.download_task_id)
            if (job) {
              setActiveJobId(job.id)
            }
          }
          setTimeout(findJob, 1000)
        }
        queryClient.invalidateQueries({ queryKey: ['book-jobs', id] })
      }
    },
    onError: (error: Error) => {
      toast.error(`Search failed: ${error.message}`)
    }
  })

  // Update custom folder path mutation
  const updateFolderPathMutation = useMutation({
    mutationFn: async (customPath: string | null) => {
      return booksApi.update(id!, { custom_folder_path: customPath })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['book', id] })
      setIsEditingFolderPath(false)
    }
  })

  // Update related_series mutation
  const updateRelatedSeriesMutation = useMutation({
    mutationFn: async (relatedSeries: string | null) => {
      return booksApi.update(id!, { related_series: relatedSeries })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['book', id] })
      setIsEditingRelatedSeries(false)
    }
  })

  // Scan files mutation
  const scanFilesMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch(`/api/v1/books/${id}/scan-files`, {
        method: 'POST'
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to scan files')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['book', id] })
      setScanResults(data)
      setShowScanResults(true)
    },
    onError: (error: Error) => {
      alert(`Scan failed: ${error.message}`)
    }
  })

  // Organize book files mutation
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

  // Bulk delete chapters mutation
  const bulkDeleteChaptersMutation = useMutation({
    mutationFn: async (chapterIds: string[]) => {
      const deletePromises = chapterIds.map(chapterId =>
        authFetch(`/api/v1/chapters/${chapterId}`, { method: 'DELETE' })
      )
      return Promise.all(deletePromises)
    },
    onSuccess: () => {
      toast.success(`Deleted ${selectedChapterIds.size} chapters`)
      queryClient.invalidateQueries({ queryKey: ['book', id] })
      setSelectedChapterIds(new Set())
      setBulkChapterMode(false)
    },
    onError: (error: Error) => {
      toast.error(`Bulk delete failed: ${error.message}`)
    }
  })

  const editMetadataMutation = useMutation({
    mutationFn: (payload: { title?: string; author_name?: string; author_id?: string }) =>
      booksApi.editMetadata(id!, payload),
    onSuccess: (data) => {
      setShowEditMetadataModal(false)
      setEditAuthorSearch('')
      setEditAuthorResults([])
      setEditSelectedAuthor(null)
      if (data.chapters_to_update > 0) {
        toast.success(`Updating tags on ${data.chapters_to_update} chapter file${data.chapters_to_update !== 1 ? 's' : ''}…`)
        setTagWriteJobId(data.task_id)
      } else {
        toast.success('Book updated')
      }
      queryClient.invalidateQueries({ queryKey: ['book', id] })
      queryClient.invalidateQueries({ queryKey: ['reading-room-authors'] })
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to update metadata')
    },
  })

  // Author search state for the edit modal
  const [editAuthorSearch, setEditAuthorSearch] = useState('')
  const [editAuthorResults, setEditAuthorResults] = useState<{ id: string; name: string }[]>([])
  const [editSelectedAuthor, setEditSelectedAuthor] = useState<{ id: string; name: string } | null>(null)

  const { data: authorSearchData } = useQuery({
    queryKey: ['author-search-edit', editAuthorSearch],
    queryFn: () => authorsApi.list({ search_query: editAuthorSearch, limit: 8 }),
    enabled: editAuthorSearch.length >= 2,
    select: (d) => d.authors.map((a: any) => ({ id: a.id, name: a.name })),
  })

  useEffect(() => {
    setEditAuthorResults(authorSearchData ?? [])
  }, [authorSearchData])

  // Poll the tag-write job until it completes
  const { data: tagWriteJob } = useQuery({
    queryKey: ['tag-write-job', tagWriteJobId],
    queryFn: () => jobsApi.list({ job_type: 'metadata_refresh', entity_id: id, limit: 1 }).then(r => r.jobs[0]),
    enabled: !!tagWriteJobId,
    refetchInterval: tagWriteJobId ? 3000 : false,
    select: (job) => job,
  })

  useEffect(() => {
    if (!tagWriteJobId || !tagWriteJob) return
    if (tagWriteJob.status === 'completed') {
      setTagWriteJobId(null)
      toast.success('File tags updated successfully')
    } else if (tagWriteJob.status === 'failed') {
      setTagWriteJobId(null)
      toast.error('Some file tags could not be written — check logs')
    }
  }, [tagWriteJobId, tagWriteJob])

  const formatDuration = (ms: number | null): string => {
    if (!ms) return '--:--'
    const totalSeconds = Math.floor(ms / 1000)
    const hours = Math.floor(totalSeconds / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    const seconds = totalSeconds % 60
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    }
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }

  const getTotalDuration = (): string => {
    if (!book?.chapters) return '--:--'
    const totalMs = book.chapters.reduce((sum, ch) => sum + (ch.duration_ms || 0), 0)
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

  // Compute prev/next books in series
  const prevBook = (() => {
    if (!book?.series_id || !seriesBooks) return null
    const idx = seriesBooks.findIndex((b) => b.id === book.id)
    return idx > 0 ? seriesBooks[idx - 1] : null
  })()

  const nextBook = (() => {
    if (!book?.series_id || !seriesBooks) return null
    const idx = seriesBooks.findIndex((b) => b.id === book.id)
    return idx >= 0 && idx < seriesBooks.length - 1 ? seriesBooks[idx + 1] : null
  })()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
      </div>
    )
  }

  if (!book) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen">
        <p className="text-gray-500 dark:text-gray-400 mb-4">Book not found</p>
        <button className="btn btn-primary" onClick={() => navigate(-1)}>
          Go Back
        </button>
      </div>
    )
  }

  const chaptersWithFile = book.chapters.filter(ch => ch.has_file).length
  const missingChapters = book.chapters.length - chaptersWithFile

  // Build PlayerTrack array from chapters
  const buildPlayerTracks = (): PlayerTrack[] =>
    book.chapters
      .filter(ch => ch.has_file)
      .map(ch => ({
        id: ch.id,
        title: ch.title,
        track_number: ch.chapter_number,
        duration_ms: ch.duration_ms,
        has_file: ch.has_file,
        file_path: ch.file_path,
        artist_name: book.author_name,
        artist_id: book.author_id,
        album_id: book.id,
        album_title: book.title,
        album_cover_art_url: book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : null,
        isBookChapter: true,
      }))

  const hasProgress = bookProgress && !bookProgress.completed
  const progressChapterIndex = hasProgress
    ? book.chapters.findIndex(ch => ch.id === bookProgress.chapter_id)
    : -1

  const handlePlayBook = (fromBeginning = false) => {
    const tracks = buildPlayerTracks()
    if (tracks.length === 0) return

    if (fromBeginning) {
      // Reset progress and play from start
      bookProgressApi.reset(book.id).catch(() => {})
      refetchProgress()
      player.playBook(tracks, 0, book.id)
      return
    }

    if (hasProgress && progressChapterIndex >= 0) {
      // Find the index in the filtered (has_file) tracks
      const fileTrackIndex = tracks.findIndex(t => t.id === bookProgress.chapter_id)
      const startIdx = fileTrackIndex >= 0 ? fileTrackIndex : 0
      player.playBook(tracks, startIdx, book.id)
      // Seek to saved position after a short delay to let audio load
      if (bookProgress.position_ms > 0) {
        const seekAfterLoad = () => {
          const audio = player.audioRef.current
          if (audio) {
            const doSeek = () => {
              audio.currentTime = bookProgress.position_ms / 1000
              audio.removeEventListener('canplay', doSeek)
            }
            audio.addEventListener('canplay', doSeek)
          }
        }
        setTimeout(seekAfterLoad, 100)
      }
    } else {
      player.playBook(tracks, 0, book.id)
    }
  }

  return (
    <div className="relative min-h-screen -m-3 md:-m-6 overflow-x-hidden">
      <Toaster position="top-right" />
      {/* Blurred Cover Art Background */}
      {book.cover_art_url && (
        <div
          className="fixed inset-0 bg-cover bg-center filter blur-3xl opacity-20 -z-10"
          style={{ backgroundImage: `url(/api/v1/books/${id}/cover-art)` }}
        />
      )}

      {/* Content */}
      <div className="relative z-10 p-3 md:p-6 space-y-4 md:space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-start md:space-x-6">
        {/* Book Info - shown first on mobile */}
        <div className="flex-1 order-1 md:order-2">
          <div className="flex items-center space-x-3 mb-2">
            <button
              className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
              onClick={() => window.history.length > 1 ? navigate(-1) : navigate(`/reading-room/authors/${book.author_id}`)}
              title="Go back"
            >
              <FiArrowLeft className="w-5 h-5" />
            </button>
            <span className={`badge ${getStatusColor(book.status)}`}>
              {book.status}
            </span>
            {book.monitored && (
              <span className="badge badge-primary">
                <FiCheck className="w-3 h-3 mr-1" />
                Monitored
              </span>
            )}
          </div>

          <div className="flex items-start gap-2 mb-1 md:mb-2">
            <h1 className="text-2xl md:text-4xl font-bold text-gray-900 dark:text-white">{book.title}</h1>
            {isDjOrAbove && (
              <button
                onClick={() => {
                  setEditMetaTitle(book.title)
                  setEditMetaAuthor(book.credit_name || book.author_name || '')
                  setShowEditMetadataModal(true)
                }}
                className="mt-1 p-1.5 rounded text-gray-400 hover:text-[#FF1493] hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors flex-shrink-0"
                title="Edit title and author in book and file tags"
              >
                <FiEdit2 className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* Tag-write progress */}
          {tagWriteJobId && tagWriteJob && (
            <div className="flex items-center gap-2 mb-2 text-xs text-gray-500 dark:text-gray-400">
              <FiLoader className="w-3 h-3 animate-spin text-[#FF1493]" />
              <span>
                Writing tags… {tagWriteJob.items_processed != null && tagWriteJob.items_total
                  ? `${tagWriteJob.items_processed}/${tagWriteJob.items_total} files`
                  : tagWriteJob.current_step || ''}
              </span>
            </div>
          )}

          <button
            className="text-lg md:text-xl text-[#FF1493] hover:text-[#d10f7a] mb-3 md:mb-4"
            onClick={() => navigate(`/reading-room/authors/${book.author_id}`)}
          >
            {book.credit_name || book.author_name}
          </button>

          {/* Series Info */}
          {book.series_id && book.series_name && (
            <div className="flex items-center flex-wrap gap-2 mb-3">
              <FiBookOpen className="w-4 h-4 text-gray-400" />
              <span className="text-sm text-gray-600 dark:text-gray-400">
                {book.series_position != null ? `Book ${book.series_position} of ` : 'Part of '}
              </span>
              <button
                className="text-sm text-[#FF1493] hover:text-[#d10f7a] font-medium"
                onClick={() => navigate(`/reading-room/series/${book.series_id}`)}
              >
                {book.series_name}
              </button>
              {/* Prev/Next navigation */}
              {(prevBook || nextBook) && (
                <div className="flex items-center gap-1 ml-2">
                  <button
                    className={`p-1 rounded ${prevBook ? 'text-gray-600 dark:text-gray-400 hover:text-[#FF1493] dark:hover:text-[#FF1493]' : 'text-gray-300 dark:text-gray-700 cursor-not-allowed'}`}
                    onClick={() => prevBook && navigate(`/reading-room/books/${prevBook.id}`)}
                    disabled={!prevBook}
                    title={prevBook ? `Previous: ${prevBook.title}` : 'No previous book'}
                  >
                    <FiChevronLeft className="w-4 h-4" />
                  </button>
                  <button
                    className={`p-1 rounded ${nextBook ? 'text-gray-600 dark:text-gray-400 hover:text-[#FF1493] dark:hover:text-[#FF1493]' : 'text-gray-300 dark:text-gray-700 cursor-not-allowed'}`}
                    onClick={() => nextBook && navigate(`/reading-room/books/${nextBook.id}`)}
                    disabled={!nextBook}
                    title={nextBook ? `Next: ${nextBook.title}` : 'No next book'}
                  >
                    <FiChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Related Series */}
          {(book.related_series || isEditingRelatedSeries) && (
            <div className="flex items-center gap-2 mb-3">
              <FiLink className="w-4 h-4 text-gray-400 flex-shrink-0" />
              {isEditingRelatedSeries ? (
                <div className="flex items-center gap-2 flex-1">
                  <input
                    type="text"
                    value={relatedSeriesText}
                    onChange={(e) => setRelatedSeriesText(e.target.value)}
                    placeholder="Related series info..."
                    className="flex-1 px-3 py-1.5 text-sm border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                  />
                  <button
                    className="btn btn-sm btn-primary"
                    onClick={() => updateRelatedSeriesMutation.mutate(relatedSeriesText || null)}
                    disabled={updateRelatedSeriesMutation.isPending}
                  >
                    <FiSave className="w-3 h-3" />
                  </button>
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={() => {
                      setIsEditingRelatedSeries(false)
                      setRelatedSeriesText(book.related_series || '')
                    }}
                  >
                    <FiX className="w-3 h-3" />
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-600 dark:text-gray-400">{book.related_series}</span>
                  {isDjOrAbove && (
                    <button
                      className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                      onClick={() => {
                        setRelatedSeriesText(book.related_series || '')
                        setIsEditingRelatedSeries(true)
                      }}
                      title="Edit related series"
                    >
                      <FiEdit2 className="w-3 h-3" />
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

        {/* Book Cover - inline on mobile, shown after title/author */}
        <div className="md:hidden mb-4">
          <CoverArtUploader
            entityType="book"
            entityId={id!}
            currentUrl={book.cover_art_url}
            onSuccess={() => queryClient.invalidateQueries({ queryKey: ['book', id] })}
            uploadFn={booksApi.uploadCoverArt}
            uploadFromUrlFn={booksApi.uploadCoverArtFromUrl}
            fallback={<img src={S54.defaultBookCover} alt={book.title} className="w-full h-full rounded-lg object-contain" />}
            alt={book.title}
            className="w-48 h-48 mx-auto bg-gradient-to-br from-gray-600 to-gray-800 rounded-lg flex items-center justify-center shadow-lg overflow-hidden"
          />
        </div>

          {/* Book Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
            <div className="space-y-1">
              <div className="text-sm text-gray-500 dark:text-gray-400">Release Date</div>
              <div className="flex items-center space-x-2">
                <FiCalendar className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-gray-900 dark:text-white">
                  {book.release_date ? new Date(book.release_date).toLocaleDateString() : 'Unknown'}
                </span>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-sm text-gray-500 dark:text-gray-400">Type</div>
              <div className="flex items-center space-x-2">
                <FiBook className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-gray-900 dark:text-white">
                  {book.album_type || 'Audiobook'}
                </span>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-sm text-gray-500 dark:text-gray-400">Chapters</div>
              <div className="flex items-center space-x-2">
                <FiBookOpen className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-gray-900 dark:text-white">
                  {book.chapter_count} chapters
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
          {book.chapters.length > 0 && (
            <div className="mt-4 p-4 bg-gray-50 dark:bg-[#161B22] rounded-lg">
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center space-x-4">
                  <div>
                    <span className="text-success-600 dark:text-success-400 font-medium">{chaptersWithFile}</span>
                    <span className="text-gray-600 dark:text-gray-400"> available</span>
                  </div>
                  {missingChapters > 0 && (
                    <div>
                      <span className="text-danger-600 dark:text-danger-400 font-medium">{missingChapters}</span>
                      <span className="text-gray-600 dark:text-gray-400"> missing</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Play Progress Status */}
          {bookProgress && (
            <div className="mt-4 p-4 bg-gray-50 dark:bg-[#161B22] rounded-lg">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  {bookProgress.completed ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
                      <FiCheckCircle className="w-3.5 h-3.5" />
                      Finished
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                      <FiBookOpen className="w-3.5 h-3.5" />
                      Reading
                    </span>
                  )}
                  {bookProgress.chapter_title && !bookProgress.completed && (
                    <span className="text-sm text-gray-600 dark:text-gray-400">
                      Ch. {bookProgress.chapter_number}: {bookProgress.chapter_title}
                    </span>
                  )}
                </div>
                <div className="flex items-center space-x-2">
                  <button
                    className={`text-xs px-3 py-1.5 rounded font-medium transition-colors ${
                      bookProgress.completed
                        ? 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                        : 'bg-green-100 dark:bg-green-900/20 text-green-700 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-900/30'
                    }`}
                    onClick={() => markFinishedMutation.mutate(!bookProgress.completed)}
                    disabled={markFinishedMutation.isPending}
                    title={bookProgress.completed ? 'Mark as unfinished' : 'Mark as finished'}
                  >
                    {bookProgress.completed ? 'Mark Unfinished' : 'Mark Finished'}
                  </button>
                  <button
                    className="text-xs px-3 py-1.5 rounded font-medium bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D] transition-colors"
                    onClick={() => resetProgressMutation.mutate()}
                    disabled={resetProgressMutation.isPending}
                    title="Reset all progress for this book"
                  >
                    <FiRotateCcw className="w-3 h-3 inline mr-1" />
                    Reset
                  </button>
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
                        placeholder="/audiobooks/Author/Book"
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
                          setFolderPath(book.custom_folder_path || '')
                        }}
                        title="Cancel editing"
                      >
                        <FiX className="w-4 h-4" />
                      </button>
                    </div>
                    {/* Scan button in edit mode - only if path is already saved */}
                    {book.custom_folder_path && (
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
                            Scan Files & Match Chapters
                          </div>
                        )}
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-gray-600 dark:text-gray-400 font-mono">
                        {book.custom_folder_path || <span className="italic">Default path (Author/Book structure)</span>}
                      </span>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => {
                          setFolderPath(book.custom_folder_path || '')
                          setIsEditingFolderPath(true)
                        }}
                        title="Edit custom folder path"
                      >
                        <FiEdit2 className="w-4 h-4" />
                      </button>
                    </div>
                    {/* Scan button - visible when custom path is set */}
                    {book.custom_folder_path && (
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
                            Scan Files & Match Chapters
                          </div>
                        )}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Action Buttons - desktop */}
          <div className="hidden md:flex flex-wrap gap-2 mt-6">
            {chaptersWithFile > 0 && hasProgress && (
              <>
                <button
                  className="btn btn-primary"
                  title={`Resume from Chapter ${bookProgress.chapter_number}: ${bookProgress.chapter_title}`}
                  onClick={() => handlePlayBook(false)}
                >
                  <FiPlay className="w-4 h-4 mr-2" />
                  Resume
                </button>
                <button
                  className="btn btn-secondary"
                  title="Start over from chapter 1"
                  onClick={() => handlePlayBook(true)}
                >
                  <FiBookOpen className="w-4 h-4 mr-2" />
                  Play from Beginning
                </button>
              </>
            )}
            {chaptersWithFile > 0 && !hasProgress && (
              <button
                className="btn btn-primary"
                title="Play all available chapters in order"
                onClick={() => handlePlayBook(false)}
              >
                <FiPlay className="w-4 h-4 mr-2" />
                Play Book
              </button>
            )}

            {isDjOrAbove && (
            <button
              className="btn btn-primary"
              onClick={() => setOrganizeDialogOpen(true)}
              title="Organize book files into standardized folder structure"
            >
              <FiFolder className="w-4 h-4 mr-2" />
              Organize Files
            </button>
            )}

            {isDjOrAbove && (
            <button
              className={`btn ${book.monitored ? 'btn-secondary' : 'btn-primary'}`}
              onClick={() => updateMonitoringMutation.mutate(!book.monitored)}
              disabled={updateMonitoringMutation.isPending}
              title={book.monitored ? 'Stop monitoring this book for downloads' : 'Monitor this book for automatic downloads'}
            >
              {updateMonitoringMutation.isPending ? (
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
              ) : (
                <div className="flex items-center">
                  {book.monitored ? (
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
              title="Search for this audiobook download"
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

            {isDjOrAbove && !book.related_series && !isEditingRelatedSeries && (
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setRelatedSeriesText('')
                  setIsEditingRelatedSeries(true)
                }}
                title="Add related series info"
              >
                <FiLink className="w-4 h-4 mr-2" />
                Add Related Series
              </button>
            )}

            <button className="btn btn-secondary" onClick={() => refetch()} title="Refresh book data">
              <FiRefreshCw className="w-4 h-4 mr-2" />
              Refresh
            </button>
          </div>

          {/* Mobile action menu */}
          <div className="md:hidden mt-4 relative">
            <div className="flex items-center gap-2">
              {chaptersWithFile > 0 && hasProgress && (
                <button
                  className="btn btn-primary btn-sm flex-1"
                  onClick={() => handlePlayBook(false)}
                >
                  <FiPlay className="w-4 h-4 mr-1" />
                  Resume
                </button>
              )}
              {chaptersWithFile > 0 && !hasProgress && (
                <button
                  className="btn btn-primary btn-sm flex-1"
                  onClick={() => handlePlayBook(false)}
                >
                  <FiPlay className="w-4 h-4 mr-1" />
                  Play Book
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
                  {hasProgress && chaptersWithFile > 0 && (
                  <button
                    className="w-full px-4 py-2.5 text-left text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#1C2128] flex items-center"
                    onClick={() => { handlePlayBook(true); setShowMobileActions(false) }}
                  >
                    <FiBookOpen className="w-4 h-4 mr-3" />
                    Play from Beginning
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
                    onClick={() => { updateMonitoringMutation.mutate(!book.monitored); setShowMobileActions(false) }}
                    disabled={updateMonitoringMutation.isPending}
                  >
                    {book.monitored ? <FiX className="w-4 h-4 mr-3" /> : <FiCheck className="w-4 h-4 mr-3" />}
                    {book.monitored ? 'Unmonitor' : 'Monitor'}
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

        {/* Book Cover - desktop only (shown to the left via order) */}
        <CoverArtUploader
          entityType="book"
          entityId={id!}
          currentUrl={book.cover_art_url}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ['book', id] })}
          uploadFn={booksApi.uploadCoverArt}
          uploadFromUrlFn={booksApi.uploadCoverArtFromUrl}
          fallback={<img src={S54.defaultBookCover} alt={book.title} className="w-full h-full rounded-lg object-contain" />}
          alt={book.title}
          className="hidden md:flex order-1 w-64 h-64 bg-gradient-to-br from-gray-600 to-gray-800 rounded-lg items-center justify-center flex-shrink-0 shadow-lg overflow-hidden"
        />
      </div>

      {/* Download Status Banner */}
      {book.downloads && book.downloads.length > 0 && (
        <div className="space-y-2">
          {book.downloads
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
                          {status === 'QUEUED' ? 'Queued' :
                           status === 'DOWNLOADING' ? 'Downloading...' :
                           status === 'POST_PROCESSING' ? 'Extracting...' :
                           status === 'IMPORTING' ? 'Importing...' :
                           status === 'FAILED' ? 'Download Failed' :
                           status}
                        </span>
                        {dl.size_bytes > 0 && (
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                            isFailed ? 'bg-red-100 text-red-700 dark:bg-red-800 dark:text-red-200' :
                            isActive ? 'bg-amber-100 text-amber-700 dark:bg-amber-800 dark:text-amber-200' :
                            'bg-gray-100 text-gray-700 dark:bg-[#0D1117] dark:text-gray-200'
                          }`}>
                            {(dl.size_bytes / (1024 * 1024)).toFixed(1)} MB
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5" title={dl.nzb_title || dl.release_title}>
                        {dl.nzb_title || dl.release_title}
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
                    {job.job_type === 'book_search' ? 'Book Search' : job.job_type.replace(/_/g, ' ')}
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

      {/* Chapters Table */}
      <div className="card">
        <div className="p-4 border-b border-gray-200 dark:border-[#30363D]">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">Chapters</h2>
            {isDjOrAbove && book.chapters.length > 0 && (
              <button
                className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                  bulkChapterMode
                    ? 'bg-orange-600 text-white hover:bg-orange-700'
                    : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                }`}
                onClick={() => {
                  setBulkChapterMode(!bulkChapterMode)
                  if (bulkChapterMode) setSelectedChapterIds(new Set())
                }}
                title={bulkChapterMode ? 'Exit selection mode' : 'Enable bulk selection'}
              >
                {bulkChapterMode ? 'Cancel Selection' : 'Select Mode'}
              </button>
            )}
          </div>
          {/* Bulk Chapter Actions Bar */}
          {bulkChapterMode && selectedChapterIds.size > 0 && (
            <div className="mt-3 p-3 bg-orange-50 dark:bg-orange-900/20 rounded-lg border border-orange-200 dark:border-orange-800">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {selectedChapterIds.size} chapter{selectedChapterIds.size !== 1 ? 's' : ''} selected
                </span>
                <div className="flex space-x-2">
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => {
                      if (window.confirm(`Delete ${selectedChapterIds.size} selected chapter(s)? This cannot be undone.`)) {
                        bulkDeleteChaptersMutation.mutate(Array.from(selectedChapterIds))
                      }
                    }}
                    disabled={bulkDeleteChaptersMutation.isPending}
                    title="Delete selected chapters"
                  >
                    Delete Selected
                  </button>
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={() => toggleSelectAllChapters(book.chapters)}
                    title={selectedChapterIds.size === book.chapters.length ? 'Deselect all' : 'Select all'}
                  >
                    {selectedChapterIds.size === book.chapters.length ? 'Deselect All' : 'Select All'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {(() => {
          const isMultiDisc = book.chapters.some(ch => ch.disc_number > 1)
          const discNumbers = isMultiDisc ? [...new Set(book.chapters.map(ch => ch.disc_number))].sort((a, b) => a - b) : [1]
          const chaptersByDisc = (disc: number) => book.chapters.filter(ch => ch.disc_number === disc)

          return book.chapters.length > 0 ? (
          <>
          {/* Desktop table */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 dark:bg-[#161B22]">
                <tr>
                  {bulkChapterMode && (
                    <th className="px-4 py-3 w-10">
                      <input
                        type="checkbox"
                        checked={selectedChapterIds.size === book.chapters.length && book.chapters.length > 0}
                        onChange={() => toggleSelectAllChapters(book.chapters)}
                        className="w-4 h-4"
                      />
                    </th>
                  )}
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-16">
                    #
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                    Title
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-24">
                    Duration
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
                      <td colSpan={bulkChapterMode ? 6 : 5} className="px-4 py-2">
                        <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">Disc {disc}</span>
                        <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">{chaptersByDisc(disc).length} chapters</span>
                      </td>
                    </tr>
                  ] : []),
                  ...chaptersByDisc(disc).map((chapter) => (
                  <tr
                    key={chapter.id}
                    className={`hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors ${
                      bulkChapterMode && selectedChapterIds.has(chapter.id) ? 'bg-orange-50 dark:bg-orange-900/10' : ''
                    }`}
                  >
                    {bulkChapterMode && (
                      <td className="px-4 py-3 w-10">
                        <input
                          type="checkbox"
                          checked={selectedChapterIds.has(chapter.id)}
                          onChange={() => toggleChapterSelection(chapter.id)}
                          className="w-4 h-4"
                        />
                      </td>
                    )}
                    <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      <div className="flex items-center gap-1.5">
                        {chapter.chapter_number}
                        {hasProgress && progressChapterIndex >= 0 && (() => {
                          const chIdx = book.chapters.findIndex(c => c.id === chapter.id)
                          if (chIdx < progressChapterIndex) return <FiCheck className="w-3 h-3 text-success-500" title="Listened" />
                          if (chIdx === progressChapterIndex) return <FiPlay className="w-3 h-3 text-[#FF1493]" title="In progress" />
                          return null
                        })()}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className={`text-sm font-medium ${
                        chapter.has_file
                          ? 'text-gray-900 dark:text-white'
                          : 'text-gray-500 dark:text-gray-600'
                      }`}>
                        {chapter.title}
                      </div>
                      {chapter.has_file && chapter.file_path && (
                        <div className="text-xs text-gray-500 dark:text-gray-400 font-mono mt-1 truncate max-w-md" title={chapter.file_path}>
                          {chapter.file_path}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                      {formatDuration(chapter.duration_ms)}
                    </td>
                    <td className="px-4 py-3">
                      {chapter.has_file ? (
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
                        {chapter.has_file && (
                          <>
                            <button
                              className="text-[#FF1493] hover:text-[#d10f7a]"
                              title="Play this chapter"
                              onClick={() => player.play({
                                id: chapter.id,
                                title: chapter.title,
                                track_number: chapter.chapter_number,
                                duration_ms: chapter.duration_ms,
                                has_file: chapter.has_file,
                                file_path: chapter.file_path,
                                artist_name: book.author_name,
                                artist_id: book.author_id,
                                album_id: book.id,
                                album_title: book.title,
                                album_cover_art_url: book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : null,
                                isBookChapter: true,
                              })}
                            >
                              <FiPlay className="w-4 h-4" />
                            </button>
                            <button
                              className="text-gray-500 dark:text-gray-400 hover:text-[#FF1493]"
                              title="Add to the play queue"
                              onClick={() => player.addToQueue({
                                id: chapter.id,
                                title: chapter.title,
                                track_number: chapter.chapter_number,
                                duration_ms: chapter.duration_ms,
                                has_file: chapter.has_file,
                                file_path: chapter.file_path,
                                artist_name: book.author_name,
                                artist_id: book.author_id,
                                album_id: book.id,
                                album_title: book.title,
                                album_cover_art_url: book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : null,
                                isBookChapter: true,
                              })}
                            >
                              <FiPlus className="w-4 h-4" />
                            </button>
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

          {/* Mobile chapter list */}
          <div className="md:hidden divide-y divide-gray-200 dark:divide-[#30363D]">
            {discNumbers.flatMap((disc) => [
              ...(isMultiDisc ? [
                <div key={`disc-header-mobile-${disc}`} className="bg-gray-100 dark:bg-[#161B22] px-3 py-2">
                  <span className="text-sm font-semibold text-gray-700 dark:text-gray-300">Disc {disc}</span>
                  <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">{chaptersByDisc(disc).length} chapters</span>
                </div>
              ] : []),
              ...chaptersByDisc(disc).map((chapter) => (
              <div key={chapter.id}>
                <div
                  className={`flex items-center px-3 py-3 active:bg-gray-50 dark:active:bg-gray-800 ${
                    bulkChapterMode && selectedChapterIds.has(chapter.id) ? 'bg-orange-50 dark:bg-orange-900/10' : ''
                  }`}
                  onClick={() => {
                    if (bulkChapterMode) {
                      toggleChapterSelection(chapter.id)
                    } else {
                      setExpandedChapterId(expandedChapterId === chapter.id ? null : chapter.id)
                    }
                  }}
                >
                  {bulkChapterMode && (
                    <div className="mr-2 flex-shrink-0">
                      <input
                        type="checkbox"
                        checked={selectedChapterIds.has(chapter.id)}
                        onChange={() => toggleChapterSelection(chapter.id)}
                        className="w-4 h-4"
                        onClick={(e) => e.stopPropagation()}
                      />
                    </div>
                  )}
                  <div className="flex-1 min-w-0 mr-2">
                    <div className="flex items-center">
                      <span className="text-xs text-gray-400 dark:text-gray-500 w-8 flex-shrink-0 flex items-center gap-0.5">
                        {chapter.chapter_number}.
                        {hasProgress && progressChapterIndex >= 0 && (() => {
                          const chIdx = book.chapters.findIndex(c => c.id === chapter.id)
                          if (chIdx < progressChapterIndex) return <FiCheck className="w-2.5 h-2.5 text-success-500" />
                          if (chIdx === progressChapterIndex) return <FiPlay className="w-2.5 h-2.5 text-[#FF1493]" />
                          return null
                        })()}
                      </span>
                      <span className={`text-sm font-medium truncate ${
                        chapter.has_file ? 'text-gray-900 dark:text-white' : 'text-gray-400 dark:text-gray-600'
                      }`}>
                        {chapter.title}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <div className="flex items-center space-x-1">
                      {chapter.has_file && (
                        <button
                          className="p-1.5 text-[#FF1493] hover:text-[#d10f7a]"
                          title="Play"
                          onClick={(e) => {
                            e.stopPropagation()
                            player.play({
                              id: chapter.id,
                              title: chapter.title,
                              track_number: chapter.chapter_number,
                              duration_ms: chapter.duration_ms,
                              has_file: chapter.has_file,
                              file_path: chapter.file_path,
                              artist_name: book.author_name,
                              artist_id: book.author_id,
                              album_id: book.id,
                              album_title: book.title,
                              album_cover_art_url: book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : null,
                              isBookChapter: true,
                            })
                          }}
                        >
                          <FiPlay className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                    {expandedChapterId === chapter.id ? (
                      <FiChevronUp className="w-4 h-4 text-gray-400" />
                    ) : (
                      <FiChevronDown className="w-4 h-4 text-gray-400" />
                    )}
                  </div>
                </div>

                {/* Expanded detail panel */}
                {expandedChapterId === chapter.id && (
                  <div className="px-3 pb-3 bg-gray-50 dark:bg-[#161B22]/50 space-y-2">
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div>
                        <span className="text-gray-500 dark:text-gray-400">Duration</span>
                        <p className="text-gray-900 dark:text-white font-medium">{formatDuration(chapter.duration_ms)}</p>
                      </div>
                      <div>
                        <span className="text-gray-500 dark:text-gray-400">Status</span>
                        <p>
                          {chapter.has_file ? (
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
                    {chapter.has_file && chapter.file_path && (
                      <div className="text-xs">
                        <span className="text-gray-500 dark:text-gray-400">Path</span>
                        <p className="text-gray-700 dark:text-gray-300 font-mono break-all">{chapter.file_path}</p>
                      </div>
                    )}
                    <div className="flex items-center gap-2 pt-1 flex-wrap">
                      {chapter.has_file && (
                        <button
                          className="text-xs px-2 py-1 bg-[#FF1493]/10 dark:bg-[#FF1493]/15 text-[#d10f7a] dark:text-[#ff4da6] rounded hover:bg-[#FF1493]/15 dark:hover:bg-[#FF1493]/20"
                          onClick={() => player.addToQueue({
                            id: chapter.id, title: chapter.title, track_number: chapter.chapter_number, duration_ms: chapter.duration_ms,
                            has_file: chapter.has_file, file_path: chapter.file_path, artist_name: book.author_name,
                            artist_id: book.author_id, album_id: book.id, album_title: book.title, album_cover_art_url: book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : null,
                            isBookChapter: true,
                          })}
                        >
                          <FiPlus className="w-3 h-3 inline mr-1" />Queue
                        </button>
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
            <FiBook className="w-16 h-16 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
            <p className="text-gray-500 dark:text-gray-400 mb-4">
              No chapters found for this book
            </p>
          </div>
        )
        })()}
      </div>

      {/* Download History (if any) */}
      {book.downloads && book.downloads.length > 0 && (
        <div className="card">
          <div className="p-4 border-b border-gray-200 dark:border-[#30363D] flex items-center justify-between">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">Download History</h2>
          </div>
          <div className="p-4 space-y-3">
            {book.downloads.map((download: any, index: number) => (
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
                      {download.queued_at && ` - ${new Date(download.queued_at).toLocaleString()}`}
                      {download.completed_at && ` - Completed: ${new Date(download.completed_at).toLocaleString()}`}
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
        initialPath={folderPath || '/audiobooks'}
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
                  {scanResults.files_found} files found - {scanResults.matches} auto-matched - {scanResults.potential_matches?.length || 0} need review
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
              {/* Auto-matched chapters */}
              {scanResults.matches > 0 && (
                <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4">
                  <h3 className="font-semibold text-green-900 dark:text-green-100 mb-2">
                    <FiCheck className="inline w-5 h-5 mr-2" />
                    {scanResults.matches} Chapter{scanResults.matches > 1 ? 's' : ''} Matched Automatically
                  </h3>
                </div>
              )}

              {/* Unmatched chapters */}
              {scanResults.unmatched_tracks && scanResults.unmatched_tracks.length > 0 && (
                <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4">
                  <h3 className="font-semibold text-yellow-900 dark:text-yellow-100 mb-2">
                    {scanResults.unmatched_tracks.length} Unmatched Chapter{scanResults.unmatched_tracks.length > 1 ? 's' : ''}
                  </h3>
                  <ul className="text-sm text-yellow-800 dark:text-yellow-200 ml-4 list-disc">
                    {scanResults.unmatched_tracks.map((ch: any) => (
                      <li key={ch.id}>#{ch.track_number || ch.chapter_number}: {ch.title}</li>
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
                Organize Book Files
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Organize files for <strong>{book.title}</strong> by <strong>{book.author_name}</strong> into standardized folder structure.
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
                    <p className="text-xs text-gray-500">Create .mbid.json file in book directory</p>
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

      {/* Edit Metadata Modal */}
      {showEditMetadataModal && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl w-full max-w-md border border-gray-200 dark:border-[#30363D]">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Edit Book Details</h2>
              <button
                onClick={() => { setShowEditMetadataModal(false); setEditAuthorSearch(''); setEditAuthorResults([]); setEditSelectedAuthor(null) }}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
              >
                <FiX className="w-5 h-5" />
              </button>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault()
                const payload: { title?: string; author_name?: string; author_id?: string } = {}
                if (editMetaTitle.trim() && editMetaTitle.trim() !== book.title) payload.title = editMetaTitle.trim()
                if (editMetaAuthor.trim() && editMetaAuthor.trim() !== (book.credit_name || book.author_name)) payload.author_name = editMetaAuthor.trim()
                if (editSelectedAuthor && editSelectedAuthor.id !== book.author_id) payload.author_id = editSelectedAuthor.id
                if (!payload.title && !payload.author_name && !payload.author_id) {
                  toast('No changes detected', { icon: 'ℹ️' })
                  return
                }
                editMetadataMutation.mutate(payload)
              }}
              className="px-6 py-5 space-y-4"
            >
              {/* Book Title */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Book Title</label>
                <input
                  type="text"
                  value={editMetaTitle}
                  onChange={(e) => setEditMetaTitle(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:border-[#FF1493]"
                  placeholder="Book title"
                />
              </div>

              {/* Reassign Author */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Reassign Author</label>
                {editSelectedAuthor ? (
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-[#FF1493] bg-[#FF1493]/5 text-sm">
                    <span className="flex-1 font-medium text-gray-900 dark:text-white">{editSelectedAuthor.name}</span>
                    <button type="button" onClick={() => { setEditSelectedAuthor(null); setEditAuthorSearch('') }} className="text-gray-400 hover:text-red-500">
                      <FiX className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <div className="relative">
                    <input
                      type="text"
                      value={editAuthorSearch}
                      onChange={(e) => setEditAuthorSearch(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:border-[#FF1493]"
                      placeholder={`Current: ${book.credit_name || book.author_name} — search to reassign`}
                    />
                    {editAuthorResults.length > 0 && (
                      <div className="absolute z-10 left-0 right-0 mt-1 bg-white dark:bg-[#161B22] border border-gray-200 dark:border-[#30363D] rounded-lg shadow-xl max-h-48 overflow-y-auto">
                        {editAuthorResults.map((a) => (
                          <button
                            key={a.id}
                            type="button"
                            onClick={() => { setEditSelectedAuthor(a); setEditMetaAuthor(a.name); setEditAuthorSearch(''); setEditAuthorResults([]) }}
                            className="w-full text-left px-4 py-2.5 text-sm text-gray-900 dark:text-white hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors"
                          >
                            {a.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Moves this book under a different author in the library.
                </p>
              </div>

              {/* File Tag Author Override */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Author name in file tags
                  <span className="ml-1 font-normal text-gray-400">(optional override)</span>
                </label>
                <input
                  type="text"
                  value={editMetaAuthor}
                  onChange={(e) => setEditMetaAuthor(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white px-3 py-2 text-sm focus:outline-none focus:border-[#FF1493]"
                  placeholder="Leave blank to use the author's name"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Written to artist &amp; album-artist tags in every chapter file.
                </p>
              </div>

              <div className="flex gap-3 pt-1">
                <button
                  type="submit"
                  disabled={editMetadataMutation.isPending}
                  className="flex-1 flex items-center justify-center gap-2 bg-[#FF1493] hover:bg-[#d10f7a] disabled:opacity-50 text-white rounded-lg py-2 text-sm font-medium transition-colors"
                >
                  {editMetadataMutation.isPending ? <FiLoader className="w-4 h-4 animate-spin" /> : <FiSave className="w-4 h-4" />}
                  Save &amp; Update Files
                </button>
                <button
                  type="button"
                  onClick={() => { setShowEditMetadataModal(false); setEditAuthorSearch(''); setEditAuthorResults([]); setEditSelectedAuthor(null) }}
                  className="flex-1 rounded-lg border border-gray-300 dark:border-[#30363D] text-gray-700 dark:text-gray-300 py-2 text-sm hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default BookDetail
