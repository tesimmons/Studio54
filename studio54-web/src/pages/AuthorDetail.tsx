import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useSearchParamState } from '../hooks/useSearchParamState'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authorsApi, booksApi, bookProgressApi, fileOrganizationApi, jobsApi, searchApi, seriesApi, authFetch } from '../api/client'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import CoverArtUploader from '../components/CoverArtUploader'
import type { Job } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import {
  FiArrowLeft,
  FiRefreshCw,
  FiSearch,
  FiCheck,
  FiX,
  FiBook,
  FiCalendar,
  FiBookOpen,
  FiFolder,
  FiDownload,
  FiAlertCircle,
  FiCheckCircle,
  FiLoader,
  FiTrash2,
  FiMoreVertical,
  FiList,
  FiChevronDown,
  FiChevronUp,
  FiImage,
  FiUser,
  FiTag,
  FiEdit2,
  FiMenu,
  FiMinus,
  FiPlus,
  FiExternalLink,
} from 'react-icons/fi'
import { S54 } from '../assets/graphics'

interface BookItem {
  id: string
  title: string
  musicbrainz_id: string | null
  release_date: string | null
  album_type: string | null
  secondary_types: string | null
  status: string
  monitored: boolean
  chapter_count: number
  linked_files_count: number
  cover_art_url: string | null
  series_id: string | null
  series_name: string | null
  series_position: number | null
}

interface AuthorWithBooks {
  id: string
  name: string
  musicbrainz_id: string | null
  is_monitored: boolean
  overview: string | null
  genre: string | null
  country: string | null
  image_url: string | null
  book_count: number
  series_count: number
  chapter_count: number
  linked_files_count: number
  monitor_type: string | null
  added_at: string
  last_sync_at: string | null
  books: BookItem[]
  series?: Array<{ id: string; name: string; book_count: number; monitored: boolean }>
}

// ---------------------------------------------------------------------------
// Sortable book row for the manage-series modal
// ---------------------------------------------------------------------------
interface ModalSeriesBook {
  id: string
  title: string
  series_position: number | null
  cover_art_url: string | null
  status: string
  chapter_count: number
  linked_files_count: number
}

function SortableSeriesBook({
  book,
  onRemove,
}: {
  book: ModalSeriesBook
  onRemove: (id: string) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: book.id })
  const style = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.4 : 1 }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-2 p-2 rounded-lg bg-gray-50 dark:bg-[#1C2128] ${isDragging ? 'shadow-lg ring-1 ring-[#FF1493]' : ''}`}
    >
      <button
        className="cursor-grab active:cursor-grabbing touch-none p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 flex-shrink-0"
        onClick={(e) => e.stopPropagation()}
        {...attributes}
        {...listeners}
      >
        <FiMenu className="w-4 h-4" />
      </button>
      <div className="flex-shrink-0 w-8 text-center text-sm font-bold text-gray-400">
        {book.series_position != null ? `#${book.series_position}` : '--'}
      </div>
      <div className="w-10 h-10 flex-shrink-0 bg-gray-200 dark:bg-gray-700 rounded overflow-hidden">
        <img
          src={book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : ''}
          alt={book.title}
          className="w-full h-full object-cover"
          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
        />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{book.title}</p>
        <p className="text-xs text-gray-500">{book.linked_files_count}/{book.chapter_count} chapters</p>
      </div>
      <button
        className="flex-shrink-0 p-1 text-gray-400 hover:text-red-500 transition-colors"
        onClick={() => onRemove(book.id)}
        title="Remove from series"
      >
        <FiMinus className="w-4 h-4" />
      </button>
    </div>
  )
}

function AuthorDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useSearchParamState('q', '')

  // Book type filter state
  const ALL_BOOK_TYPES = ['Audiobook', 'Album', 'EP', 'Single', 'Compilation']
  const [typesParam, setTypesParam] = useSearchParamState('types', '')
  const enabledTypes: Set<string> = typesParam ? new Set(typesParam.split(',')) : new Set(ALL_BOOK_TYPES)
  const setEnabledTypes = useCallback((next: Set<string>) => {
    // Store as empty param when all types selected (default)
    if (next.size === ALL_BOOK_TYPES.length && ALL_BOOK_TYPES.every(t => next.has(t))) {
      setTypesParam('')
    } else {
      setTypesParam([...next].join(','))
    }
  }, [setTypesParam])
  const [filterDropdownOpen, setFilterDropdownOpen] = useState(false)
  const [showAllParam, setShowAllParam] = useSearchParamState('showAll', '')
  const showAllBooks = showAllParam === 'true'
  const setShowAllBooks = useCallback((v: boolean) => setShowAllParam(v ? 'true' : ''), [setShowAllParam])

  // Bulk selection state for books
  const [bulkBookMode, setBulkBookMode] = useState(false)
  const [selectedBookIds, setSelectedBookIds] = useState<Set<string>>(new Set())

  // Toast notification state
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null)

  // Active job tracking for this author
  const [activeJobId, setActiveJobId] = useState<string | null>(null)

  // Edit bio modal state
  const [editBioOpen, setEditBioOpen] = useState(false)
  const [editBioOverview, setEditBioOverview] = useState('')
  const [editBioGenre, setEditBioGenre] = useState('')
  const [editBioCountry, setEditBioCountry] = useState('')

  // Metadata refresh job tracking
  const [metadataRefreshJobId, setMetadataRefreshJobId] = useState<string | null>(null)
  const [metadataRefreshResult, setMetadataRefreshResult] = useState<Record<string, unknown> | null>(null)
  const [metadataResultExpanded, setMetadataResultExpanded] = useState(true)

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 5000)
  }, [])

  // Mobile actions menu
  const [actionsMenuOpen, setActionsMenuOpen] = useState(false)

  // Delete dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteFiles, setDeleteFiles] = useState(false)

  // Create Series dialog state
  const [createSeriesDialogOpen, setCreateSeriesDialogOpen] = useState(false)
  const [newSeriesName, setNewSeriesName] = useState('')
  const [newSeriesBooks, setNewSeriesBooks] = useState<{ bookId: string; position: number }[]>([])

  // Add to Series menu state
  const [addToSeriesBookId, setAddToSeriesBookId] = useState<string | null>(null)

  // Series delete state
  const [bulkSeriesMode, setBulkSeriesMode] = useState(false)
  const [selectedSeriesIds, setSelectedSeriesIds] = useState<Set<string>>(new Set())
  const [deleteSeriesTarget, setDeleteSeriesTarget] = useState<{ id: string; name: string } | null>(null)
  const [bulkDeleteSeriesOpen, setBulkDeleteSeriesOpen] = useState(false)

  // Manage series modal state
  const [manageSeriesId, setManageSeriesId] = useState<string | null>(null)

  // Organize dialog state
  const [organizeDialogOpen, setOrganizeDialogOpen] = useState(false)
  const [organizeOptions, setOrganizeOptions] = useState({
    dry_run: true,
    create_metadata_files: true,
    only_with_mbid: true,
    only_unorganized: true,
  })

  const { isDjOrAbove } = useAuth()

  // Fetch author details
  const { data: author, isLoading, refetch } = useQuery({
    queryKey: ['author', id],
    queryFn: async (): Promise<AuthorWithBooks> => {
      const data = await authorsApi.get(id!)
      return data as unknown as AuthorWithBooks
    },
    enabled: !!id,
  })

  // Fetch batch progress for all books
  const { data: progressData } = useQuery({
    queryKey: ['book-progress-batch', id],
    queryFn: () => bookProgressApi.batchGet(author!.books.map(b => b.id)),
    enabled: !!author?.books?.length,
  })

  // Poll for active jobs for this author
  const { data: activeJobs } = useQuery({
    queryKey: ['author-jobs', id],
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
      showToast(`Job completed: ${trackedJob.current_step || trackedJob.job_type}`, 'success')
      setActiveJobId(null)
      queryClient.invalidateQueries({ queryKey: ['author', id] })
      queryClient.invalidateQueries({ queryKey: ['author-jobs', id] })
    } else if (trackedJob.status === 'failed') {
      showToast(`Job failed: ${trackedJob.error_message || 'Unknown error'}`, 'error')
      setActiveJobId(null)
      queryClient.invalidateQueries({ queryKey: ['author-jobs', id] })
    }
  }, [trackedJob?.status])

  // Update author monitoring
  const updateMonitoringMutation = useMutation({
    mutationFn: async (isMonitored: boolean) => {
      const response = await authFetch(`/api/v1/authors/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_monitored: isMonitored })
      })
      if (!response.ok) throw new Error('Failed to update monitoring')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['author', id] })
      queryClient.invalidateQueries({ queryKey: ['authors'] })
    }
  })

  // Edit bio mutation
  const editBioMutation = useMutation({
    mutationFn: async (payload: { overview?: string; genre?: string; country?: string }) => {
      const response = await authFetch(`/api/v1/authors/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (!response.ok) throw new Error('Failed to update author info')
      return response.json()
    },
    onSuccess: () => {
      showToast('Author info updated', 'success')
      setEditBioOpen(false)
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to update: ${error.message}`, 'error')
    }
  })

  // Sync books mutation
  const syncBooksMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch(`/api/v1/authors/${id}/sync`, {
        method: 'POST'
      })
      if (!response.ok) throw new Error('Failed to sync books')
      return response.json()
    },
    onSuccess: (data) => {
      showToast(`Book sync started for ${author?.name || 'author'}. Tracking progress...`, 'info')
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
      queryClient.invalidateQueries({ queryKey: ['author-jobs', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to sync books: ${error.message}`, 'error')
    }
  })

  // Search missing books mutation
  const searchMissingMutation = useMutation({
    mutationFn: async () => {
      return searchApi.searchMissing(id!)
    },
    onSuccess: (data) => {
      showToast(data.message || 'Search for missing books started', 'info')
    },
    onError: (error: Error) => {
      showToast(`Failed to search missing: ${error.message}`, 'error')
    }
  })

  // Refresh metadata mutation
  const refreshMetadataMutation = useMutation({
    mutationFn: async () => {
      // Use authFetch directly since authorsApi may not have refreshMetadata
      const response = await authFetch(`/api/v1/authors/${id}/refresh-metadata?force=true`, {
        method: 'POST'
      })
      if (!response.ok) throw new Error('Failed to refresh metadata')
      return response.json()
    },
    onSuccess: (data) => {
      showToast(`Metadata refresh started for ${data.author_name || author?.name}`, 'info')
      setMetadataRefreshResult(null)
      // Poll for the job that was just started
      const findJob = async () => {
        try {
          const result = await jobsApi.list({ entity_id: id!, job_type: 'metadata_refresh', limit: 5 })
          const jobs = result.jobs || []
          const running = jobs.find((j: Job) => j.status === 'running' || j.status === 'pending')
          if (running) {
            setMetadataRefreshJobId(running.id)
          } else if (data.task_id) {
            // fallback: find by celery task id
            const any = jobs.find((j: Job) => j.celery_task_id === data.task_id)
            if (any) setMetadataRefreshJobId(any.id)
          }
        } catch { /* ignore */ }
      }
      setTimeout(findJob, 1500)
    },
    onError: (error: Error) => {
      showToast(`Failed to refresh metadata: ${error.message}`, 'error')
    }
  })

  // Poll specific metadata refresh job
  const { data: metadataRefreshJob } = useQuery({
    queryKey: ['metadata-refresh-job', metadataRefreshJobId],
    queryFn: async (): Promise<Job> => jobsApi.get(metadataRefreshJobId!),
    enabled: !!metadataRefreshJobId,
    refetchInterval: (query) => {
      const job = query.state.data
      if (job && (job.status === 'completed' || job.status === 'failed')) return false
      return 2000
    },
  })

  // Capture result data when metadata refresh job completes
  useEffect(() => {
    if (!metadataRefreshJob) return
    if (metadataRefreshJob.status === 'completed') {
      setMetadataRefreshResult(metadataRefreshJob.result_data || {})
      setMetadataResultExpanded(true)
      setMetadataRefreshJobId(null)
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    } else if (metadataRefreshJob.status === 'failed') {
      setMetadataRefreshResult({ error: metadataRefreshJob.error_message || 'Job failed' })
      setMetadataResultExpanded(true)
      setMetadataRefreshJobId(null)
    }
  }, [metadataRefreshJob?.status])

  // Detect series mutation
  const detectSeriesMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch(`/api/v1/authors/${id}/detect-series`, {
        method: 'POST'
      })
      if (!response.ok) throw new Error('Failed to detect series')
      return response.json()
    },
    onSuccess: (data) => {
      showToast(`Series detection started for ${data.author_name || author?.name}`, 'info')
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['author', id] })
      }, 5000)
    },
    onError: (error: Error) => {
      showToast(`Failed to detect series: ${error.message}`, 'error')
    }
  })

  // Create series mutation
  const createSeriesMutation = useMutation({
    mutationFn: async () => {
      const series = await seriesApi.create({
        author_id: id!,
        name: newSeriesName.trim(),
      })
      // Add books to the series
      for (const entry of newSeriesBooks) {
        await seriesApi.addBook(series.id, entry.bookId, entry.position)
      }
      return series
    },
    onSuccess: (data) => {
      showToast(`Series "${data.name}" created successfully`, 'success')
      setCreateSeriesDialogOpen(false)
      setNewSeriesName('')
      setNewSeriesBooks([])
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to create series: ${error.message}`, 'error')
    }
  })

  // Add book to existing series mutation
  const addBookToSeriesMutation = useMutation({
    mutationFn: async ({ seriesId, bookId }: { seriesId: string; bookId: string }) => {
      return seriesApi.addBook(seriesId, bookId)
    },
    onSuccess: () => {
      showToast('Book added to series', 'success')
      setAddToSeriesBookId(null)
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to add book to series: ${error.message}`, 'error')
    }
  })

  // Delete single series mutation
  const deleteSeriesMutation = useMutation({
    mutationFn: async (seriesId: string) => {
      return seriesApi.delete(seriesId)
    },
    onSuccess: () => {
      showToast('Series deleted. Books have been unlinked.', 'success')
      setDeleteSeriesTarget(null)
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to delete series: ${error.message}`, 'error')
    }
  })

  // Bulk delete series mutation
  const bulkDeleteSeriesMutation = useMutation({
    mutationFn: async (seriesIds: string[]) => {
      return seriesApi.bulkDelete(seriesIds)
    },
    onSuccess: (data) => {
      showToast(`Deleted ${data.deleted_count} series. Books have been unlinked.`, 'success')
      setBulkDeleteSeriesOpen(false)
      setSelectedSeriesIds(new Set())
      setBulkSeriesMode(false)
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to bulk delete series: ${error.message}`, 'error')
    }
  })

  // Manage series modal: fetch series detail
  const { data: manageSeriesData, isLoading: manageSeriesLoading } = useQuery({
    queryKey: ['series', manageSeriesId],
    queryFn: async () => {
      const response = await authFetch(`/api/v1/series/${manageSeriesId}`)
      if (!response.ok) throw new Error('Failed to fetch series')
      return response.json() as Promise<{
        id: string; name: string; books: ModalSeriesBook[]
        author_id: string; total_expected_books: number | null
      }>
    },
    enabled: !!manageSeriesId,
  })

  // Sorted books for manage modal (by series_position)
  const manageSortedBooks: ModalSeriesBook[] = (manageSeriesData?.books || []).slice().sort((a, b) => {
    if (a.series_position == null && b.series_position == null) return 0
    if (a.series_position == null) return 1
    if (b.series_position == null) return -1
    return a.series_position - b.series_position
  })

  const manageSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleManageDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id || !manageSeriesId) return
    const oldIndex = manageSortedBooks.findIndex(b => b.id === active.id)
    const newIndex = manageSortedBooks.findIndex(b => b.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const newOrder = arrayMove(manageSortedBooks.map(b => b.id), oldIndex, newIndex)
    manageReorderMutation.mutate(newOrder)
  }, [manageSortedBooks, manageSeriesId])

  const manageReorderMutation = useMutation({
    mutationFn: async (bookIds: string[]) => seriesApi.reorder(manageSeriesId!, bookIds),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['series', manageSeriesId] }),
    onError: (error: Error) => showToast(`Failed to reorder: ${error.message}`, 'error'),
  })

  const manageRemoveBookMutation = useMutation({
    mutationFn: async (bookId: string) => seriesApi.removeBook(manageSeriesId!, bookId),
    onSuccess: () => {
      showToast('Book removed from series', 'success')
      queryClient.invalidateQueries({ queryKey: ['series', manageSeriesId] })
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    },
    onError: (error: Error) => showToast(`Failed to remove book: ${error.message}`, 'error'),
  })

  const manageAddBookMutation = useMutation({
    mutationFn: async (bookId: string) => seriesApi.addBook(manageSeriesId!, bookId),
    onSuccess: () => {
      showToast('Book added to series', 'success')
      queryClient.invalidateQueries({ queryKey: ['series', manageSeriesId] })
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    },
    onError: (error: Error) => showToast(`Failed to add book: ${error.message}`, 'error'),
  })

  // Organize author files mutation
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

  // Delete author mutation
  const deleteAuthorMutation = useMutation({
    mutationFn: async (shouldDeleteFiles: boolean) => {
      const response = await authFetch(`/api/v1/authors/${id}?delete_files=${shouldDeleteFiles}`, {
        method: 'DELETE'
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Failed to delete author' }))
        throw new Error(error.detail || 'Failed to delete author')
      }
      return response.json()
    },
    onSuccess: () => {
      setDeleteDialogOpen(false)
      queryClient.invalidateQueries({ queryKey: ['authors'] })
      navigate('/reading-room')
    },
    onError: (error: Error) => {
      showToast(`Failed to delete author: ${error.message}`, 'error')
    }
  })

  // Monitor all books and start downloading
  const monitorAllAndDownloadMutation = useMutation({
    mutationFn: async () => {
      // Step 1: Monitor all books
      await booksApi.monitorByAuthor(id!, true)
      // Step 2: Trigger search for missing (downloads)
      const result = await searchApi.searchMissing(id!)
      return result
    },
    onSuccess: (data) => {
      showToast(data.message || 'All books monitored and search started', 'info')
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to monitor and download: ${error.message}`, 'error')
    }
  })

  // Toggle book monitoring
  const toggleBookMonitoringMutation = useMutation({
    mutationFn: async ({ bookId, monitored }: { bookId: string; monitored: boolean }) => {
      const response = await authFetch(`/api/v1/books/${bookId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ monitored })
      })
      if (!response.ok) throw new Error('Failed to update book')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['author', id] })
    }
  })

  // Bulk update book monitoring
  const bulkUpdateBooksMutation = useMutation({
    mutationFn: async (monitored: boolean) => {
      return booksApi.bulkUpdate(Array.from(selectedBookIds), monitored)
    },
    onSuccess: () => {
      showToast(`Updated ${selectedBookIds.size} books`, 'success')
      queryClient.invalidateQueries({ queryKey: ['author', id] })
      setSelectedBookIds(new Set())
      setBulkBookMode(false)
    },
    onError: (error: Error) => {
      showToast(`Bulk update failed: ${error.message}`, 'error')
    }
  })

  // Bulk delete books
  const bulkDeleteBooksMutation = useMutation({
    mutationFn: async (bookIds: string[]) => {
      const deletePromises = bookIds.map(bookId =>
        authFetch(`/api/v1/books/${bookId}`, { method: 'DELETE' })
      )
      return Promise.all(deletePromises)
    },
    onSuccess: () => {
      showToast(`Deleted ${selectedBookIds.size} books`, 'success')
      queryClient.invalidateQueries({ queryKey: ['author', id] })
      setSelectedBookIds(new Set())
      setBulkBookMode(false)
    },
    onError: (error: Error) => {
      showToast(`Bulk delete failed: ${error.message}`, 'error')
    }
  })

  const toggleBookSelection = useCallback((bookId: string) => {
    setSelectedBookIds(prev => {
      const next = new Set(prev)
      if (next.has(bookId)) next.delete(bookId)
      else next.add(bookId)
      return next
    })
  }, [])

  const toggleSelectAllBooks = useCallback((allBooks: BookItem[]) => {
    setSelectedBookIds(prev => {
      if (prev.size === allBooks.length) return new Set()
      return new Set(allBooks.map(b => b.id))
    })
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
      </div>
    )
  }

  if (!author) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen">
        <p className="text-gray-500 dark:text-gray-400 mb-4">Author not found</p>
        <button className="btn btn-primary" onClick={() => navigate('/reading-room')}>
          Back to Reading Room
        </button>
      </div>
    )
  }

  // Helper to get secondary types as array
  const getSecondaryTypes = (book: BookItem): string[] =>
    book.secondary_types ? book.secondary_types.split(',').map(s => s.trim()).filter(Boolean) : []

  // Filter books by search query and enabled types
  const filteredBooks = (author.books || []).filter(book => {
    if (!showAllBooks && (book.linked_files_count || 0) === 0) return false
    if (!book.title.toLowerCase().includes(searchQuery.toLowerCase())) return false
    const secondaryTypes = getSecondaryTypes(book)
    const primaryMatch = enabledTypes.has(book.album_type || 'Audiobook')
    const secondaryMatch = secondaryTypes.some(st => enabledTypes.has(st))
    return primaryMatch || secondaryMatch
  })

  // Categorize into sections
  const audiobooksSection = filteredBooks.filter(book => {
    const st = getSecondaryTypes(book)
    return (book.album_type === 'Audiobook' || st.includes('Audiobook')) &&
      !st.some(s => ['Compilation'].includes(s))
  })
  const albumsSection = filteredBooks.filter(book => {
    const st = getSecondaryTypes(book)
    return book.album_type === 'Album' && !st.includes('Audiobook') &&
      !st.some(s => ['Compilation'].includes(s))
  })
  const compilationsSection = filteredBooks.filter(book => getSecondaryTypes(book).includes('Compilation'))
  const otherSection = filteredBooks.filter(book => {
    const st = getSecondaryTypes(book)
    const type = book.album_type || ''
    return !['Audiobook', 'Album'].includes(type) &&
      !st.includes('Audiobook') &&
      !st.includes('Compilation')
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

  // Helper to render book grid
  const renderBookGrid = (books: BookItem[]) => {
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8 gap-4">
        {books.map((book) => {
          const progress = progressData?.progress?.[book.id]
          const playStatus = !progress ? 'new' : progress.completed ? 'finished' : 'started'
          return (
          <div
            key={book.id}
            className={`card p-0 hover:shadow-lg transition-shadow cursor-pointer group ${
              bulkBookMode && selectedBookIds.has(book.id) ? 'ring-2 ring-[#FF1493]' : ''
            }`}
            onClick={() => {
              if (bulkBookMode) {
                toggleBookSelection(book.id)
              } else {
                navigate(`/reading-room/books/${book.id}`)
              }
            }}
          >
            {/* Book Cover - square aspect ratio, centered, no crop */}
            <div className="relative aspect-square bg-gradient-to-br from-gray-600 to-gray-800 flex items-center justify-center">
              <img
                src={book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : S54.defaultBookCover}
                alt={book.title}
                className="w-full h-full object-contain"
              />

              {/* Bulk selection checkbox */}
              {bulkBookMode && (
                <div className="absolute top-2 left-2 z-10">
                  <input
                    type="checkbox"
                    checked={selectedBookIds.has(book.id)}
                    onChange={() => toggleBookSelection(book.id)}
                    className="w-5 h-5"
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>
              )}

              {/* Status Badge */}
              <div className="absolute top-2 right-2">
                <span className={`badge ${getStatusColor(book.status)}`}>
                  {book.status}
                </span>
              </div>

              {/* Monitoring Badge */}
              {!bulkBookMode && book.monitored && (
                <div className="absolute top-2 left-2">
                  <span className="badge badge-primary">
                    <FiCheck className="w-3 h-3" />
                  </span>
                </div>
              )}

              {/* Play Status Badge */}
              {playStatus === 'started' && (
                <div className="absolute bottom-2 left-2">
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-600/90 text-white">
                    <FiBookOpen className="w-3 h-3" />
                    Reading
                  </span>
                </div>
              )}
              {playStatus === 'finished' && (
                <div className="absolute bottom-2 left-2">
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-green-600/90 text-white">
                    <FiCheckCircle className="w-3 h-3" />
                    Finished
                  </span>
                </div>
              )}
            </div>

            {/* Book Info */}
            <div className="p-3">
              <h3 className="font-semibold text-gray-900 dark:text-white text-sm line-clamp-2 group-hover:text-[#FF1493] transition-colors min-h-[2.5rem]">
                {book.title}
              </h3>

              {/* Series info */}
              {book.series_name && (
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 truncate">
                  {book.series_name}{book.series_position != null ? ` #${book.series_position}` : ''}
                </p>
              )}

              <div className="mt-2 space-y-1 text-xs text-gray-600 dark:text-gray-400">
                {book.release_date && (
                  <div className="flex items-center space-x-1">
                    <FiCalendar className="w-3 h-3" />
                    <span>{new Date(book.release_date).getFullYear()}</span>
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-1">
                    <FiBookOpen className="w-3 h-3" />
                    <span>{book.linked_files_count || 0} / {book.chapter_count || 0} linked</span>
                  </div>
                  <span className="text-xs text-gray-500 dark:text-gray-500">
                    {book.secondary_types ? book.secondary_types.split(',').join(', ') : book.album_type}
                  </span>
                </div>
                {(book.chapter_count || 0) > 0 && (
                  <div className="w-full bg-gray-200 dark:bg-[#0D1117] rounded-full h-1.5 mt-1">
                    <div
                      className={`h-1.5 rounded-full transition-all ${
                        (book.linked_files_count || 0) >= (book.chapter_count || 0)
                          ? 'bg-green-500'
                          : (book.linked_files_count || 0) > 0
                            ? 'bg-amber-500'
                            : 'bg-gray-400 dark:bg-gray-600'
                      }`}
                      style={{ width: `${Math.min(100, Math.round(((book.linked_files_count || 0) / (book.chapter_count || 1)) * 100))}%` }}
                    />
                  </div>
                )}
              </div>

              {/* Monitor Toggle Button */}
              {isDjOrAbove && (
                <button
                  className={`mt-3 w-full py-1.5 px-3 rounded text-xs font-medium transition-colors ${
                    book.monitored
                      ? 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                      : 'bg-[#FF1493] text-white hover:bg-[#d10f7a]'
                  }`}
                  onClick={(e) => {
                    e.stopPropagation()
                    toggleBookMonitoringMutation.mutate({
                      bookId: book.id,
                      monitored: !book.monitored
                    })
                  }}
                  disabled={toggleBookMonitoringMutation.isPending}
                  title={book.monitored ? 'Unmonitor this book' : 'Monitor this book'}
                >
                  {book.monitored ? (
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

              {/* Add to Series */}
              {isDjOrAbove && !book.series_id && (
                <div className="relative mt-1">
                  <button
                    className="w-full py-1 px-3 rounded text-xs font-medium transition-colors bg-gray-100 dark:bg-[#0D1117] text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-[#30363D]"
                    onClick={(e) => {
                      e.stopPropagation()
                      setAddToSeriesBookId(addToSeriesBookId === book.id ? null : book.id)
                    }}
                    title="Add to series"
                  >
                    <div className="flex items-center justify-center">
                      <FiList className="w-3 h-3 mr-1" />
                      Add to Series
                    </div>
                  </button>
                  {addToSeriesBookId === book.id && (
                    <>
                      <div className="fixed inset-0 z-30" onClick={(e) => { e.stopPropagation(); setAddToSeriesBookId(null) }} />
                      <div className="absolute left-0 right-0 top-full mt-1 bg-white dark:bg-[#161B22] rounded-lg shadow-xl border border-gray-200 dark:border-[#30363D] z-40 py-1 max-h-48 overflow-y-auto">
                        {(author.series || []).map((s) => (
                          <button
                            key={s.id}
                            className="w-full text-left px-3 py-2 text-xs text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                            onClick={(e) => {
                              e.stopPropagation()
                              addBookToSeriesMutation.mutate({ seriesId: s.id, bookId: book.id })
                            }}
                          >
                            {s.name}
                          </button>
                        ))}
                        <div className="border-t border-gray-200 dark:border-[#30363D] mt-1 pt-1">
                          <button
                            className="w-full text-left px-3 py-2 text-xs text-[#FF1493] hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                            onClick={(e) => {
                              e.stopPropagation()
                              setAddToSeriesBookId(null)
                              setNewSeriesName('')
                              setNewSeriesBooks([{ bookId: book.id, position: 1 }])
                              setCreateSeriesDialogOpen(true)
                            }}
                          >
                            + Create New Series
                          </button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col sm:flex-row items-start gap-4 sm:gap-6 min-w-0">
          {/* Author Image */}
          <CoverArtUploader
            entityType="author"
            entityId={id!}
            currentUrl={author.image_url}
            onSuccess={() => queryClient.invalidateQueries({ queryKey: ['author', id] })}
            uploadFn={authorsApi.uploadCoverArt}
            uploadFromUrlFn={authorsApi.uploadCoverArtFromUrl}
            fallback={
              <div className="w-full h-full bg-gradient-to-br from-[#FF1493] to-[#FF8C00] flex items-center justify-center">
                <FiBook className="w-24 h-24 text-white/30" />
              </div>
            }
            alt={author.name}
            className="w-28 h-28 sm:w-48 sm:h-48 rounded-lg overflow-hidden flex-shrink-0"
          />

          {/* Author Info */}
          <div className="flex-1">
            <div className="flex items-center space-x-3 mb-2">
              <button
                className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                onClick={() => window.history.length > 1 ? navigate(-1) : navigate('/reading-room')}
                title="Back to Reading Room"
              >
                <FiArrowLeft className="w-5 h-5" />
              </button>
              <h1 className="text-xl sm:text-4xl font-bold text-gray-900 dark:text-white">{author.name}</h1>
            </div>

            {/* Stats */}
            <div className="flex flex-wrap items-center gap-3 sm:gap-6 mt-4 text-sm">
              <div className="flex items-center space-x-2">
                <FiBook className="w-4 h-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">
                  {author.book_count || 0} Books
                </span>
              </div>
              <div className="flex items-center space-x-2">
                <FiList className="w-4 h-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">
                  {author.series_count || 0} Series
                </span>
              </div>
              <div className="flex items-center space-x-2">
                <FiBookOpen className="w-4 h-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">
                  {author.chapter_count || 0} Chapters
                </span>
              </div>
              {author.genre && (
                <div className="flex items-center space-x-2">
                  <span className="text-xs px-2 py-0.5 bg-gray-100 dark:bg-[#0D1117] text-gray-600 dark:text-gray-400 rounded">
                    {author.genre}
                  </span>
                </div>
              )}
              {author.country && (
                <div className="flex items-center space-x-2">
                  <span className="text-xs px-2 py-0.5 bg-gray-100 dark:bg-[#0D1117] text-gray-600 dark:text-gray-400 rounded">
                    {author.country}
                  </span>
                </div>
              )}
              {author.added_at && (
                <div className="flex items-center space-x-2">
                  <FiCalendar className="w-4 h-4 text-gray-400" />
                  <span className="text-gray-600 dark:text-gray-400">
                    Added {new Date(author.added_at).toLocaleDateString()}
                  </span>
                </div>
              )}
            </div>

            {/* Biography / Overview */}
            <div className="mt-4 max-w-3xl group/bio relative">
              {author.overview ? (
                <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-4">{author.overview}</p>
              ) : isDjOrAbove ? (
                <p className="text-sm text-gray-400 dark:text-gray-600 italic">No biography — click edit to add one</p>
              ) : null}
              {isDjOrAbove && (
                <button
                  className="absolute -top-1 -right-1 opacity-0 group-hover/bio:opacity-100 p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#30363D] transition-all"
                  title="Edit author info"
                  onClick={() => {
                    setEditBioOverview(author.overview || '')
                    setEditBioGenre(author.genre || '')
                    setEditBioCountry(author.country || '')
                    setEditBioOpen(true)
                  }}
                >
                  <FiEdit2 className="w-3.5 h-3.5" />
                </button>
              )}
            </div>

            {/* Monitoring Toggle */}
            <div className="mt-4 flex items-center space-x-4">
              {isDjOrAbove ? (
                <button
                  className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                    author.is_monitored
                      ? 'bg-success-600 text-white hover:bg-success-700'
                      : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                  }`}
                  onClick={() => updateMonitoringMutation.mutate(!author.is_monitored)}
                  disabled={updateMonitoringMutation.isPending}
                  title={author.is_monitored ? 'Unmonitor this author' : 'Monitor this author'}
                >
                  {updateMonitoringMutation.isPending ? (
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                  ) : (
                    <div className="flex items-center">
                      {author.is_monitored ? (
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
                  author.is_monitored
                    ? 'bg-success-600/20 text-success-700 dark:text-success-400'
                    : 'bg-gray-200 dark:bg-[#0D1117] text-gray-500 dark:text-gray-400'
                }`}>
                  {author.is_monitored ? 'Monitored' : 'Not Monitored'}
                </span>
              )}

              {author.last_sync_at && (
                <span className="text-sm text-gray-500 dark:text-gray-400">
                  Last synced: {new Date(author.last_sync_at).toLocaleString()}
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
              title="Monitor all books and search for missing downloads"
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
              title="Organize author files into standardized folder structure"
            >
              <FiFolder className="w-4 h-4 mr-2" />
              Organize Files
            </button>
          )}
          {isDjOrAbove && (
            <button
              className="btn btn-secondary"
              onClick={() => syncBooksMutation.mutate()}
              disabled={syncBooksMutation.isPending}
              title="Sync book list from MusicBrainz"
            >
              {syncBooksMutation.isPending ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                  Syncing...
                </>
              ) : (
                <>
                  <FiRefreshCw className="w-4 h-4 mr-2" />
                  Sync Books
                </>
              )}
            </button>
          )}
          {isDjOrAbove && (
            <button
              className="btn btn-secondary"
              onClick={() => searchMissingMutation.mutate()}
              disabled={searchMissingMutation.isPending}
              title="Search for missing books"
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
              title="Refresh author images and metadata from MusicBrainz"
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
              onClick={() => detectSeriesMutation.mutate()}
              disabled={detectSeriesMutation.isPending}
              title="Detect series from file metadata tags"
            >
              {detectSeriesMutation.isPending ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>
                  Detecting...
                </>
              ) : (
                <>
                  <FiList className="w-4 h-4 mr-2" />
                  Detect Series
                </>
              )}
            </button>
          )}
          {isDjOrAbove && (
            <button
              className="btn btn-secondary"
              onClick={() => {
                setNewSeriesName('')
                setNewSeriesBooks([])
                setCreateSeriesDialogOpen(true)
              }}
              title="Manually create a new series"
            >
              <FiList className="w-4 h-4 mr-2" />
              Create Series
            </button>
          )}
          <button className="btn btn-secondary" onClick={() => refetch()} title="Refresh author data">
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
              title="Remove this author and all associated books"
            >
              <FiTrash2 className="w-4 h-4 mr-2" />
              Remove Author
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
                    onClick={() => { syncBooksMutation.mutate(); setActionsMenuOpen(false) }}
                    disabled={syncBooksMutation.isPending}
                  >
                    <FiRefreshCw className="w-4 h-4 mr-3 text-gray-500" />
                    Sync Books
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
                    onClick={() => { detectSeriesMutation.mutate(); setActionsMenuOpen(false) }}
                    disabled={detectSeriesMutation.isPending}
                  >
                    <FiList className="w-4 h-4 mr-3 text-gray-500" />
                    Detect Series
                  </button>
                )}
                {isDjOrAbove && (
                  <button
                    className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128]"
                    onClick={() => {
                      setNewSeriesName('')
                      setNewSeriesBooks([])
                      setCreateSeriesDialogOpen(true)
                      setActionsMenuOpen(false)
                    }}
                  >
                    <FiList className="w-4 h-4 mr-3 text-gray-500" />
                    Create Series
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
                      Remove Author
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
                    {job.job_type === 'author_sync' ? 'Book Sync' : job.job_type.replace(/_/g, ' ')}
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

      {/* Metadata Refresh Progress Panel */}
      {metadataRefreshJob && (metadataRefreshJob.status === 'running' || metadataRefreshJob.status === 'pending') && (
        <div className="bg-purple-50 dark:bg-purple-900/20 border border-purple-200 dark:border-purple-800 rounded-lg px-4 py-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <FiLoader className="w-4 h-4 text-purple-600 dark:text-purple-400 animate-spin" />
              <span className="text-sm font-medium text-purple-800 dark:text-purple-200">Refreshing Metadata</span>
            </div>
            <div className="flex items-center space-x-3">
              {metadataRefreshJob.items_total && metadataRefreshJob.items_total > 0 ? (
                <span className="text-xs text-purple-600 dark:text-purple-400">
                  {metadataRefreshJob.items_processed || 0}/{metadataRefreshJob.items_total} books
                </span>
              ) : null}
              <div className="w-32 bg-purple-200 dark:bg-purple-800 rounded-full h-2">
                <div
                  className="bg-purple-600 dark:bg-purple-400 h-2 rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, metadataRefreshJob.progress_percent || 0)}%` }}
                />
              </div>
              <span className="text-xs font-medium text-purple-800 dark:text-purple-200 w-10 text-right">
                {Math.round(metadataRefreshJob.progress_percent || 0)}%
              </span>
            </div>
          </div>
          {metadataRefreshJob.current_step && (
            <p className="text-xs text-purple-600 dark:text-purple-400 pl-7 italic">{metadataRefreshJob.current_step}</p>
          )}
        </div>
      )}

      {/* Metadata Refresh Results Panel */}
      {metadataRefreshResult && (
        <div className="border border-gray-200 dark:border-[#30363D] rounded-lg overflow-hidden">
          <button
            className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 dark:bg-[#161B22] hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors"
            onClick={() => setMetadataResultExpanded(prev => !prev)}
          >
            <div className="flex items-center space-x-2">
              {(metadataRefreshResult.error as string | undefined) ? (
                <FiAlertCircle className="w-4 h-4 text-red-500" />
              ) : (
                <FiCheckCircle className="w-4 h-4 text-green-500" />
              )}
              <span className="text-sm font-medium text-gray-800 dark:text-gray-200">
                Metadata Refresh Results
              </span>
              {!(metadataRefreshResult.error as string | undefined) && (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  — {[
                    metadataRefreshResult.author_image_updated && 'image',
                    metadataRefreshResult.biography_updated && 'bio',
                    metadataRefreshResult.genre_updated && 'genre',
                  ].filter(Boolean).join(', ') || 'no new data'}
                  {(metadataRefreshResult.books_updated as number) > 0 && `, ${metadataRefreshResult.books_updated} book covers`}
                </span>
              )}
            </div>
            <div className="flex items-center space-x-2">
              <button
                className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 px-2 py-0.5 rounded hover:bg-gray-200 dark:hover:bg-[#30363D]"
                onClick={(e) => { e.stopPropagation(); setMetadataRefreshResult(null) }}
              >
                Dismiss
              </button>
              {metadataResultExpanded ? <FiChevronUp className="w-4 h-4 text-gray-500" /> : <FiChevronDown className="w-4 h-4 text-gray-500" />}
            </div>
          </button>
          {metadataResultExpanded && (
            <div className="px-4 py-3 space-y-3 bg-white dark:bg-[#0D1117]">
              {(metadataRefreshResult.error as string | undefined) ? (
                <p className="text-sm text-red-600 dark:text-red-400">{metadataRefreshResult.error as string}</p>
              ) : (
                <>
                  {/* Image */}
                  <div className="flex items-center space-x-3">
                    <FiImage className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <span className="text-sm text-gray-700 dark:text-gray-300 w-20 flex-shrink-0">Photo</span>
                    {metadataRefreshResult.author_image_updated ? (
                      <span className="flex items-center space-x-1.5 text-sm text-green-600 dark:text-green-400">
                        <FiCheckCircle className="w-3.5 h-3.5" />
                        <span>Found via {metadataRefreshResult.image_source as string || 'unknown'}</span>
                      </span>
                    ) : (
                      <span className="flex items-center space-x-1.5 text-sm text-gray-400 dark:text-gray-500">
                        <FiX className="w-3.5 h-3.5" />
                        <span>No photo found</span>
                      </span>
                    )}
                  </div>
                  {/* Biography */}
                  <div className="flex items-center space-x-3">
                    <FiUser className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <span className="text-sm text-gray-700 dark:text-gray-300 w-20 flex-shrink-0">Biography</span>
                    {metadataRefreshResult.biography_updated ? (
                      <span className="flex items-center space-x-1.5 text-sm text-green-600 dark:text-green-400">
                        <FiCheckCircle className="w-3.5 h-3.5" />
                        <span>Found ({(metadataRefreshResult.bio_chars as number || 0).toLocaleString()} chars)</span>
                      </span>
                    ) : (
                      <span className="flex items-center space-x-1.5 text-sm text-gray-400 dark:text-gray-500">
                        <FiX className="w-3.5 h-3.5" />
                        <span>No biography found</span>
                      </span>
                    )}
                  </div>
                  {/* Genre */}
                  <div className="flex items-center space-x-3">
                    <FiTag className="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <span className="text-sm text-gray-700 dark:text-gray-300 w-20 flex-shrink-0">Genre</span>
                    {metadataRefreshResult.genre_updated ? (
                      <span className="flex items-center space-x-1.5 text-sm text-green-600 dark:text-green-400">
                        <FiCheckCircle className="w-3.5 h-3.5" />
                        <span>{metadataRefreshResult.genre_name as string || 'set'}</span>
                      </span>
                    ) : (
                      <span className="flex items-center space-x-1.5 text-sm text-gray-400 dark:text-gray-500">
                        <FiX className="w-3.5 h-3.5" />
                        <span>No genre found</span>
                      </span>
                    )}
                  </div>
                  {/* Book covers */}
                  {((metadataRefreshResult.books_processed as number) > 0 || (metadataRefreshResult.books_found as unknown[])?.length > 0 || (metadataRefreshResult.books_not_found as unknown[])?.length > 0) && (
                    <div className="space-y-1.5 pt-1 border-t border-gray-100 dark:border-[#30363D]">
                      <div className="flex items-center space-x-3">
                        <FiBook className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                          Book Covers: {metadataRefreshResult.books_updated as number}/{metadataRefreshResult.books_processed as number} found
                        </span>
                      </div>
                      {((metadataRefreshResult.books_found as Array<{id: string; title: string; source?: string}>)?.length > 0) && (
                        <div className="pl-7 space-y-0.5 max-h-40 overflow-y-auto">
                          {(metadataRefreshResult.books_found as Array<{id: string; title: string; source?: string}>).map(b => (
                            <div key={b.id} className="flex items-center space-x-1.5 text-xs text-green-600 dark:text-green-400">
                              <FiCheckCircle className="w-3 h-3 flex-shrink-0" />
                              <span className="truncate">{b.title}</span>
                              {b.source && <span className="text-green-400 dark:text-green-500 flex-shrink-0">({b.source})</span>}
                            </div>
                          ))}
                        </div>
                      )}
                      {((metadataRefreshResult.books_not_found as Array<{id: string; title: string}>)?.length > 0) && (
                        <div className="pl-7 space-y-0.5 max-h-40 overflow-y-auto">
                          {(metadataRefreshResult.books_not_found as Array<{id: string; title: string}>).map(b => (
                            <div key={b.id} className="flex items-center space-x-1.5 text-xs text-gray-400 dark:text-gray-500">
                              <FiX className="w-3 h-3 flex-shrink-0" />
                              <span className="truncate">{b.title}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
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

      {/* Series Section */}
      {author.series && author.series.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Series ({author.series.length})</h2>
            {isDjOrAbove && (
              <div className="flex items-center gap-2">
                {bulkSeriesMode && selectedSeriesIds.size > 0 && (
                  <button
                    className="btn btn-danger text-sm flex items-center gap-1"
                    onClick={() => setBulkDeleteSeriesOpen(true)}
                  >
                    <FiTrash2 className="w-3.5 h-3.5" />
                    Delete Selected ({selectedSeriesIds.size})
                  </button>
                )}
                {bulkSeriesMode && (
                  <button
                    className="btn btn-secondary text-sm"
                    onClick={() => {
                      if (selectedSeriesIds.size === author.series!.length) {
                        setSelectedSeriesIds(new Set())
                      } else {
                        setSelectedSeriesIds(new Set(author.series!.map(s => s.id)))
                      }
                    }}
                  >
                    {selectedSeriesIds.size === author.series!.length ? 'Deselect All' : 'Select All'}
                  </button>
                )}
                <button
                  className={`btn text-sm flex items-center gap-1 ${bulkSeriesMode ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => {
                    setBulkSeriesMode(!bulkSeriesMode)
                    setSelectedSeriesIds(new Set())
                  }}
                  title={bulkSeriesMode ? 'Exit bulk select' : 'Bulk select series'}
                >
                  <FiList className="w-3.5 h-3.5" />
                  {bulkSeriesMode ? 'Done' : 'Select'}
                </button>
              </div>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {author.series.map((series) => (
              <div
                key={series.id}
                className="card p-4 hover:shadow-lg transition-shadow cursor-pointer group relative"
                onClick={() => {
                  if (bulkSeriesMode) {
                    setSelectedSeriesIds(prev => {
                      const next = new Set(prev)
                      if (next.has(series.id)) next.delete(series.id)
                      else next.add(series.id)
                      return next
                    })
                  } else {
                    setManageSeriesId(series.id)
                  }
                }}
              >
                <div className="flex items-center justify-between">
                  {bulkSeriesMode && (
                    <input
                      type="checkbox"
                      className="checkbox mr-2 flex-shrink-0"
                      checked={selectedSeriesIds.has(series.id)}
                      onChange={() => {}}
                      onClick={(e) => e.stopPropagation()}
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-gray-900 dark:text-white text-sm group-hover:text-[#FF1493] transition-colors truncate">
                      {series.name}
                    </h3>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                      {series.book_count} book{series.book_count !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                    {series.monitored && (
                      <span className="badge badge-primary">
                        <FiCheck className="w-3 h-3" />
                      </span>
                    )}
                    {isDjOrAbove && !bulkSeriesMode && (
                      <button
                        className="p-1 text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity"
                        title="Delete series"
                        onClick={(e) => {
                          e.stopPropagation()
                          setDeleteSeriesTarget({ id: series.id, name: series.name })
                        }}
                      >
                        <FiTrash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Single Series Delete Confirmation Dialog */}
      {deleteSeriesTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setDeleteSeriesTarget(null)}>
          <div className="bg-white dark:bg-[#161B22] rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-2">Delete Series</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">
              Are you sure you want to delete <strong>"{deleteSeriesTarget.name}"</strong>?
            </p>
            <p className="text-xs text-amber-600 dark:text-amber-400 mb-4">
              Books will be unlinked from this series but not deleted.
            </p>
            <div className="flex justify-end gap-2">
              <button className="btn btn-secondary" onClick={() => setDeleteSeriesTarget(null)}>Cancel</button>
              <button
                className="btn btn-danger"
                disabled={deleteSeriesMutation.isPending}
                onClick={() => deleteSeriesMutation.mutate(deleteSeriesTarget.id)}
              >
                {deleteSeriesMutation.isPending ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Series Delete Confirmation Dialog */}
      {bulkDeleteSeriesOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setBulkDeleteSeriesOpen(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-2">Delete {selectedSeriesIds.size} Series</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">
              Are you sure you want to delete {selectedSeriesIds.size} selected series?
            </p>
            <p className="text-xs text-amber-600 dark:text-amber-400 mb-4">
              Books will be unlinked from these series but not deleted.
            </p>
            <div className="flex justify-end gap-2">
              <button className="btn btn-secondary" onClick={() => setBulkDeleteSeriesOpen(false)}>Cancel</button>
              <button
                className="btn btn-danger"
                disabled={bulkDeleteSeriesMutation.isPending}
                onClick={() => bulkDeleteSeriesMutation.mutate([...selectedSeriesIds])}
              >
                {bulkDeleteSeriesMutation.isPending ? 'Deleting...' : `Delete ${selectedSeriesIds.size} Series`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Book Actions Bar */}
      {bulkBookMode && selectedBookIds.size > 0 && (
        <div className="card p-4 bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-900 dark:text-white">
              {selectedBookIds.size} book{selectedBookIds.size !== 1 ? 's' : ''} selected
            </span>
            <div className="flex space-x-2">
              <button
                className="btn btn-sm btn-primary"
                onClick={() => bulkUpdateBooksMutation.mutate(true)}
                disabled={bulkUpdateBooksMutation.isPending}
                title="Monitor all selected books"
              >
                Monitor Selected
              </button>
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => bulkUpdateBooksMutation.mutate(false)}
                disabled={bulkUpdateBooksMutation.isPending}
                title="Unmonitor all selected books"
              >
                Unmonitor Selected
              </button>
              <button
                className="btn btn-sm btn-danger"
                onClick={() => {
                  if (window.confirm(`Delete ${selectedBookIds.size} selected book(s)? This cannot be undone.`)) {
                    bulkDeleteBooksMutation.mutate(Array.from(selectedBookIds))
                  }
                }}
                disabled={bulkDeleteBooksMutation.isPending}
                title="Delete all selected books"
              >
                Delete Selected
              </button>
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => toggleSelectAllBooks(filteredBooks)}
                title={selectedBookIds.size === filteredBooks.length ? 'Deselect all' : 'Select all'}
              >
                {selectedBookIds.size === filteredBooks.length ? 'Deselect All' : 'Select All'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Search Bar + Filter Dropdown */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          {/* Show All Books Toggle */}
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showAllBooks}
              onChange={(e) => setShowAllBooks(e.target.checked)}
              className="checkbox"
            />
            <span className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">Show all books</span>
          </label>

          {/* Bulk Book Mode Toggle */}
          {isDjOrAbove && (
            <button
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                bulkBookMode
                  ? 'bg-orange-600 text-white hover:bg-orange-700'
                  : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
              }`}
              onClick={() => {
                setBulkBookMode(!bulkBookMode)
                if (bulkBookMode) setSelectedBookIds(new Set())
              }}
              title={bulkBookMode ? 'Exit selection mode' : 'Enable bulk selection'}
            >
              {bulkBookMode ? 'Cancel Selection' : 'Select Mode'}
            </button>
          )}

          {/* Book Type Filter */}
          <div className="relative">
            <button
              onClick={() => setFilterDropdownOpen(!filterDropdownOpen)}
              className="btn btn-secondary text-sm flex items-center gap-2"
            >
              <FiBook className="w-4 h-4" />
              Filter Types
              {enabledTypes.size < ALL_BOOK_TYPES.length && (
                <span className="bg-[#FF1493] text-white text-xs rounded-full px-1.5 py-0.5 ml-1">
                  {enabledTypes.size}
                </span>
              )}
            </button>
            {filterDropdownOpen && (
              <div className="absolute z-50 mt-1 w-56 bg-white dark:bg-[#161B22] border border-gray-200 dark:border-[#30363D] rounded-lg shadow-lg p-2">
                {ALL_BOOK_TYPES.map(type => (
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
                    onClick={() => setEnabledTypes(new Set(ALL_BOOK_TYPES))}
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
              placeholder="Search books..."
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

      {/* Audiobooks Section */}
      {audiobooksSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Audiobooks ({audiobooksSection.length})
          </h2>
          {renderBookGrid(audiobooksSection)}
        </div>
      )}

      {/* Albums Section */}
      {albumsSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Albums ({albumsSection.length})
          </h2>
          {renderBookGrid(albumsSection)}
        </div>
      )}

      {/* Compilations Section */}
      {compilationsSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Compilations ({compilationsSection.length})
          </h2>
          {renderBookGrid(compilationsSection)}
        </div>
      )}

      {/* Other Releases Section */}
      {otherSection.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            Other ({otherSection.length})
          </h2>
          {renderBookGrid(otherSection)}
        </div>
      )}

      {/* Empty State */}
      {filteredBooks.length === 0 && (
        <div className="card p-12 text-center">
          <p className="text-gray-500 dark:text-gray-400">
            {searchQuery ? 'No books match your search' : 'No books found for this author'}
          </p>
          {!author.books?.length && (
            <button
              className="btn btn-primary mt-4"
              onClick={() => syncBooksMutation.mutate()}
              disabled={syncBooksMutation.isPending}
            >
              {syncBooksMutation.isPending ? 'Syncing...' : 'Sync Books from MusicBrainz'}
            </button>
          )}
        </div>
      )}

      {/* Edit Bio Modal */}
      {editBioOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setEditBioOpen(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Edit Author Info</h3>
                <button onClick={() => setEditBioOpen(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
                  <FiX className="w-5 h-5" />
                </button>
              </div>

              {/* Overview */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Biography</label>
                <textarea
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-[#FF1493] resize-y"
                  rows={8}
                  placeholder="Enter biography..."
                  value={editBioOverview}
                  onChange={e => setEditBioOverview(e.target.value)}
                />
              </div>

              {/* Genre + Country row */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Genre</label>
                  <input
                    type="text"
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                    placeholder="e.g. Fiction, Thriller"
                    value={editBioGenre}
                    onChange={e => setEditBioGenre(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Country</label>
                  <input
                    type="text"
                    className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-gray-100 text-sm focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                    placeholder="e.g. United States"
                    value={editBioCountry}
                    onChange={e => setEditBioCountry(e.target.value)}
                  />
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <button className="btn btn-secondary" onClick={() => setEditBioOpen(false)}>Cancel</button>
                <button
                  className="btn btn-primary"
                  disabled={editBioMutation.isPending}
                  onClick={() => editBioMutation.mutate({
                    overview: editBioOverview,
                    genre: editBioGenre,
                    country: editBioCountry,
                  })}
                >
                  {editBioMutation.isPending ? (
                    <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2" />Saving...</>
                  ) : 'Save'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Delete Author Confirmation Dialog */}
      {deleteDialogOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="p-6">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-2">
                Remove Author
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Are you sure you want to remove <strong>{author.name}</strong>? This will delete all associated books, chapters, and download history.
              </p>

              {(author.linked_files_count || 0) > 0 && (
                <div className="mb-4 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                  <p className="text-sm text-amber-800 dark:text-amber-200 mb-3">
                    This author has <strong>{author.linked_files_count}</strong> linked file{author.linked_files_count !== 1 ? 's' : ''} on disk.
                  </p>
                  <label className="flex items-center space-x-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={deleteFiles}
                      onChange={(e) => setDeleteFiles(e.target.checked)}
                      className="rounded border-gray-300 text-red-600 focus:ring-red-500"
                    />
                    <span className="text-sm font-medium text-amber-900 dark:text-amber-100">
                      Also delete audiobook files from disk
                    </span>
                  </label>
                </div>
              )}

              {deleteFiles && (
                <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                  <p className="text-sm text-red-800 dark:text-red-200">
                    <strong>Warning:</strong> This will permanently delete {author.linked_files_count} audiobook file{(author.linked_files_count || 0) !== 1 ? 's' : ''} from disk. This cannot be undone.
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
                onClick={() => deleteAuthorMutation.mutate(deleteFiles)}
                disabled={deleteAuthorMutation.isPending}
              >
                {deleteAuthorMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Removing...
                  </>
                ) : (
                  <>
                    <FiTrash2 className="w-4 h-4 mr-2" />
                    {deleteFiles ? 'Remove & Delete Files' : 'Remove Author'}
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
                Organize Author Files
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                Organize files for <strong>{author.name}</strong> into standardized folder structure with MBID-based naming.
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
                    <p className="text-xs text-gray-500">Create .mbid.json files in book directories</p>
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
      {/* Manage Series Modal */}
      {manageSeriesId && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setManageSeriesId(null)}>
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between p-5 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              <div className="min-w-0">
                <h3 className="text-lg font-bold text-gray-900 dark:text-white truncate">
                  {manageSeriesData?.name || 'Series'}
                </h3>
                <p className="text-xs text-gray-500 mt-0.5">
                  {manageSortedBooks.length} book{manageSortedBooks.length !== 1 ? 's' : ''} · Drag to reorder
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0 ml-3">
                <button
                  className="btn btn-secondary text-xs flex items-center gap-1"
                  onClick={() => { setManageSeriesId(null); navigate(`/reading-room/series/${manageSeriesId}`) }}
                  title="Open full series page"
                >
                  <FiExternalLink className="w-3.5 h-3.5" />
                  Full Page
                </button>
                <button className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 p-1" onClick={() => setManageSeriesId(null)}>
                  <FiX className="w-5 h-5" />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-5 min-h-0">
              {/* Current books */}
              {manageSeriesLoading ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]"></div>
                </div>
              ) : manageSortedBooks.length === 0 ? (
                <p className="text-sm text-gray-500 text-center py-4">No books in this series yet.</p>
              ) : (
                <DndContext sensors={manageSensors} collisionDetection={closestCenter} onDragEnd={handleManageDragEnd}>
                  <SortableContext items={manageSortedBooks.map(b => b.id)} strategy={verticalListSortingStrategy}>
                    <div className="space-y-2">
                      {manageSortedBooks.map(book => (
                        <SortableSeriesBook
                          key={book.id}
                          book={book}
                          onRemove={(bookId) => manageRemoveBookMutation.mutate(bookId)}
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DndContext>
              )}

              {/* Add books from author */}
              {(() => {
                const inSeriesIds = new Set(manageSortedBooks.map(b => b.id))
                const available = (author?.books || []).filter(b => !inSeriesIds.has(b.id))
                if (!available.length) return null
                return (
                  <div>
                    <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-1">
                      <FiPlus className="w-4 h-4" /> Add Books
                    </h4>
                    <div className="space-y-1 max-h-48 overflow-y-auto">
                      {available.map(book => (
                        <div key={book.id} className="flex items-center gap-2 p-2 rounded-lg hover:bg-gray-50 dark:hover:bg-[#1C2128]">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-gray-900 dark:text-white truncate">{book.title}</p>
                          </div>
                          <button
                            className="flex-shrink-0 btn btn-secondary text-xs py-1 px-2 flex items-center gap-1"
                            onClick={() => manageAddBookMutation.mutate(book.id)}
                            disabled={manageAddBookMutation.isPending}
                          >
                            <FiPlus className="w-3 h-3" /> Add
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })()}
            </div>

            <div className="flex justify-end p-4 border-t border-gray-200 dark:border-gray-700 flex-shrink-0">
              <button className="btn btn-secondary" onClick={() => setManageSeriesId(null)}>Done</button>
            </div>
          </div>
        </div>
      )}

      {/* Create Series Dialog */}
      {createSeriesDialogOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-lg w-full mx-4 max-h-[80vh] flex flex-col">
            <div className="p-6 flex-shrink-0">
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white mb-4">
                Create Series
              </h3>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Series Name
                  </label>
                  <input
                    type="text"
                    className="input w-full"
                    placeholder="e.g. The Wheel of Time"
                    value={newSeriesName}
                    onChange={(e) => setNewSeriesName(e.target.value)}
                    autoFocus
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Books in Series
                  </label>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
                    Select books and set their position. You can add more later.
                  </p>
                  <div className="space-y-2 max-h-60 overflow-y-auto">
                    {(author.books || [])
                      .filter(b => !b.series_id)
                      .map((book) => {
                        const entry = newSeriesBooks.find(e => e.bookId === book.id)
                        return (
                          <label key={book.id} className="flex items-center gap-2 p-2 rounded hover:bg-gray-50 dark:hover:bg-[#1C2128] cursor-pointer">
                            <input
                              type="checkbox"
                              className="checkbox"
                              checked={!!entry}
                              onChange={() => {
                                if (entry) {
                                  setNewSeriesBooks(prev => prev.filter(e => e.bookId !== book.id))
                                } else {
                                  setNewSeriesBooks(prev => [...prev, { bookId: book.id, position: prev.length + 1 }])
                                }
                              }}
                            />
                            <span className="text-sm text-gray-900 dark:text-white flex-1 truncate">{book.title}</span>
                            {entry && (
                              <input
                                type="number"
                                min={1}
                                className="input w-16 text-center text-sm"
                                value={entry.position}
                                onChange={(e) => {
                                  const pos = parseInt(e.target.value) || 1
                                  setNewSeriesBooks(prev => prev.map(eb =>
                                    eb.bookId === book.id ? { ...eb, position: pos } : eb
                                  ))
                                }}
                                onClick={(e) => e.stopPropagation()}
                                title="Position in series"
                              />
                            )}
                          </label>
                        )
                      })}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex justify-end space-x-3 p-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-lg flex-shrink-0">
              <button
                className="btn btn-secondary"
                onClick={() => setCreateSeriesDialogOpen(false)}
              >
                Cancel
              </button>
              <button
                className="btn btn-primary"
                onClick={() => createSeriesMutation.mutate()}
                disabled={createSeriesMutation.isPending || !newSeriesName.trim()}
              >
                {createSeriesMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Creating...
                  </>
                ) : (
                  'Create Series'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default AuthorDetail
