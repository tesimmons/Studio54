import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useSearchParamState } from '../hooks/useSearchParamState'
import { FiSearch, FiPlus, FiRefreshCw, FiX, FiBook, FiDownload, FiCheck, FiLoader, FiFileText, FiChevronUp, FiChevronDown, FiEdit2, FiSave, FiTrash2, FiMoreVertical } from 'react-icons/fi'
import Pagination from '../components/Pagination'
import toast, { Toaster } from 'react-hot-toast'
import LibraryScanner from './LibraryScanner'
import { S54 } from '../assets/graphics'
import { useAuth } from '../contexts/AuthContext'
import { authorsApi, booksApi, seriesApi, fileOrganizationApi, jobsApi, authFetch } from '../api/client'
import type { Author, Book, Series, UnlinkedFile, UnorganizedFile } from '../types'

type TabMode = 'browse' | 'scanner' | 'import' | 'unlinked' | 'unorganized'
type SortMode = 'author' | 'book' | 'series'
type FilterMode = 'all' | 'monitored' | 'unmonitored'
type AuthorSortBy = 'name' | 'files_desc' | 'files_asc' | 'added_at'
type BookSortBy = 'release_date' | 'title' | 'author' | 'files_desc' | 'files_asc' | 'added_at'
type SeriesSortBy = 'name' | 'book_count' | 'added_at'

function ReadingRoom() {
  const { isDirector, isDjOrAbove } = useAuth()
  const [activeTab, setActiveTab] = useSearchParamState('tab', 'browse') as [TabMode, (v: string) => void]
  const [sortMode, setSortMode] = useSearchParamState('sort', 'author') as [SortMode, (v: string) => void]
  const [searchQuery, setSearchQuery] = useSearchParamState('q', '')
  const [filterMode, setFilterMode] = useSearchParamState('filter', 'all') as [FilterMode, (v: string) => void]
  const [pageStr, setPageStr] = useSearchParamState('page', '1')
  const page = parseInt(pageStr, 10) || 1
  const setPage = useCallback((p: number) => setPageStr(String(p)), [setPageStr])
  const [itemsPerPage, setItemsPerPage] = useState(100)
  const [bulkMode, setBulkMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showAddAuthorModal, setShowAddAuthorModal] = useState(false)
  const [actionsMenuOpen, setActionsMenuOpen] = useState(false)
  const [genreFilter, setGenreFilter] = useSearchParamState('genre', '')
  const [authorSortBy, setAuthorSortBy] = useSearchParamState('authorSort', 'name') as [AuthorSortBy, (v: string) => void]
  const [bookSortBy, setBookSortBy] = useSearchParamState('bookSort', 'release_date') as [BookSortBy, (v: string) => void]
  const [seriesSortBy, setSeriesSortBy] = useSearchParamState('seriesSort', 'name') as [SeriesSortBy, (v: string) => void]
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false)
  const [bulkDeleteFiles, setBulkDeleteFiles] = useState(false)
  const [mbSearchQuery, setMbSearchQuery] = useState('')
  const [mbResults, setMbResults] = useState<any[]>([])
  const [mbSearching, setMbSearching] = useState(false)
  const [unlinkedReasonFilter, setUnlinkedReasonFilter] = useState<string>('')
  const [unlinkedSearch, setUnlinkedSearch] = useState('')
  const [unlinkedPage, setUnlinkedPage] = useState(1)
  const [unlinkedSortBy, setUnlinkedSortBy] = useState<string>('')
  const [unlinkedSortDir, setUnlinkedSortDir] = useState<'asc' | 'desc'>('asc')
  const [editingUnlinkedId, setEditingUnlinkedId] = useState<string | null>(null)
  const [editFields, setEditFields] = useState<{ artist: string; album: string; title: string }>({ artist: '', album: '', title: '' })
  const [unorganizedSearch, setUnorganizedSearch] = useState('')
  const [unorganizedFormatFilter, setUnorganizedFormatFilter] = useState('')
  const [unorganizedPage, setUnorganizedPage] = useState(1)
  const [unorganizedSortBy, setUnorganizedSortBy] = useState<string>('')
  const [unorganizedSortDir, setUnorganizedSortDir] = useState<'asc' | 'desc'>('asc')
  const [metadataRefreshState, setMetadataRefreshState] = useState<{ totalAuthors: number; startedAt: Date } | null>(null)

  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Poll running metadata refresh jobs while a refresh is active
  const { data: runningRefreshJobs } = useQuery({
    queryKey: ['metadata-refresh-running'],
    queryFn: () => jobsApi.list({ job_type: 'metadata_refresh', status: 'running', limit: 200 }),
    enabled: !!metadataRefreshState,
    refetchInterval: metadataRefreshState ? 4000 : false,
    select: (data) => data.total_count,
  })

  // When running count drops to 0, clear refresh state and notify
  useEffect(() => {
    if (metadataRefreshState && runningRefreshJobs === 0) {
      setMetadataRefreshState(null)
      toast.success('Metadata refresh complete')
      queryClient.invalidateQueries({ queryKey: ['reading-room-authors'] })
    }
  }, [metadataRefreshState, runningRefreshJobs, queryClient])

  // Fetch genre list for filter dropdown
  const { data: genresData } = useQuery({
    queryKey: ['author-genres'],
    queryFn: async () => {
      return authorsApi.genres()
    },
  })

  // Fetch authors when sort mode is 'author'
  const { data: authorsData, isLoading: authorsLoading } = useQuery({
    queryKey: ['reading-room-authors', filterMode, authorSortBy, genreFilter, searchQuery, page, itemsPerPage],
    queryFn: async () => {
      const params: Record<string, any> = {
        monitored_only: filterMode === 'monitored' ? true : undefined,
        search_query: searchQuery || undefined,
        limit: itemsPerPage,
        offset: (page - 1) * itemsPerPage,
      }
      if (filterMode === 'unmonitored') {
        // authorsApi.list may not support unmonitored_only directly, fetch all and we rely on backend
        params.monitored_only = false
      }
      if (authorSortBy !== 'name') params.sort_by = authorSortBy
      if (genreFilter) params.genre = genreFilter
      return authorsApi.list(params)
    },
    enabled: activeTab === 'browse' && sortMode === 'author',
  })

  // Fetch books when sort mode is 'book'
  const { data: booksData, isLoading: booksLoading } = useQuery({
    queryKey: ['reading-room-books', filterMode, bookSortBy, searchQuery, page, itemsPerPage],
    queryFn: async () => {
      const params: Record<string, any> = {
        monitored_only: filterMode === 'monitored' ? true : undefined,
        limit: itemsPerPage,
        offset: (page - 1) * itemsPerPage,
      }
      if (searchQuery) params.search_query = searchQuery
      if (bookSortBy !== 'release_date') params.sort_by = bookSortBy
      return booksApi.list(params)
    },
    enabled: activeTab === 'browse' && sortMode === 'book',
  })

  // Fetch series when sort mode is 'series'
  const { data: seriesData, isLoading: seriesLoading } = useQuery({
    queryKey: ['reading-room-series', filterMode, seriesSortBy, searchQuery, page, itemsPerPage],
    queryFn: async () => {
      const params: Record<string, any> = {
        monitored_only: filterMode === 'monitored' ? true : undefined,
        limit: itemsPerPage,
        offset: (page - 1) * itemsPerPage,
      }
      if (searchQuery) params.search_query = searchQuery
      if (seriesSortBy !== 'name') params.sort_by = seriesSortBy
      return seriesApi.list(params)
    },
    enabled: activeTab === 'browse' && sortMode === 'series',
  })

  const authors = authorsData?.authors || []
  const books = booksData?.books || []
  const seriesList: Series[] = seriesData?.series || []

  const totalCount = sortMode === 'author'
    ? (authorsData?.total_count || 0)
    : sortMode === 'book'
    ? (booksData?.total_count || 0)
    : sortMode === 'series'
    ? (seriesData?.total_count || 0)
    : 0

  const isLoading = sortMode === 'author' ? authorsLoading : sortMode === 'book' ? booksLoading : seriesLoading

  // Fetch unlinked files when on unlinked tab (audiobook library type filtered)
  const { data: unlinkedData, isLoading: unlinkedLoading, refetch: refetchUnlinked } = useQuery({
    queryKey: ['reading-room-unlinked-files', unlinkedReasonFilter, unlinkedSearch, unlinkedPage, unlinkedSortBy, unlinkedSortDir],
    queryFn: () => fileOrganizationApi.getUnlinkedFiles({
      reason: unlinkedReasonFilter || undefined,
      search: unlinkedSearch || undefined,
      library_type: 'audiobook',
      page: unlinkedPage,
      per_page: 50,
      sort_by: unlinkedSortBy || undefined,
      sort_dir: unlinkedSortDir,
    }),
    enabled: activeTab === 'unlinked',
  })

  const { data: unlinkedSummary } = useQuery({
    queryKey: ['reading-room-unlinked-summary'],
    queryFn: () => fileOrganizationApi.getUnlinkedSummary({ library_type: 'audiobook' }),
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
    queryKey: ['reading-room-unorganized-files', unorganizedSearch, unorganizedFormatFilter, unorganizedPage, unorganizedSortBy, unorganizedSortDir],
    queryFn: () => fileOrganizationApi.getUnorganizedFiles({
      search: unorganizedSearch || undefined,
      format: unorganizedFormatFilter || undefined,
      library_type: 'audiobook',
      page: unorganizedPage,
      per_page: 50,
      sort_by: unorganizedSortBy || undefined,
      sort_dir: unorganizedSortDir,
    }),
    enabled: activeTab === 'unorganized',
  })

  const { data: unorganizedSummary } = useQuery({
    queryKey: ['reading-room-unorganized-summary'],
    queryFn: () => fileOrganizationApi.getUnorganizedSummary({ library_type: 'audiobook' }),
    enabled: activeTab === 'unorganized',
  })

  // Search MusicBrainz for adding authors
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

  // Add author mutation
  const addAuthorMutation = useMutation({
    mutationFn: async (mbid: string) => {
      const response = await authFetch('/api/v1/authors', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ musicbrainz_id: mbid, is_monitored: true })
      })
      if (!response.ok) throw new Error('Failed to add author')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reading-room-authors'] })
      setShowAddAuthorModal(false)
      setMbSearchQuery('')
      setMbResults([])
      toast.success('Author added successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to add author: ${error.message}`)
    }
  })

  // Fetch all author metadata mutation
  const fetchAllMetadataMutation = useMutation({
    mutationFn: (force: boolean) => authorsApi.refreshAllMetadata(force),
    onSuccess: (data) => {
      setActionsMenuOpen(false)
      if (data.total_authors > 0) {
        setMetadataRefreshState({ totalAuthors: data.total_authors, startedAt: new Date() })
        toast.success(`Metadata refresh started for ${data.total_authors} author${data.total_authors !== 1 ? 's' : ''}`)
      } else {
        toast('No authors to refresh', { icon: 'ℹ️' })
      }
    },
    onError: () => toast.error('Failed to queue metadata refresh'),
  })

  // Bulk update mutation
  const bulkUpdateMutation = useMutation({
    mutationFn: async (monitored: boolean) => {
      if (sortMode !== 'author') return
      return authorsApi.bulkUpdate(Array.from(selectedIds), { is_monitored: monitored })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reading-room-authors'] })
      setSelectedIds(new Set())
      setBulkMode(false)
      toast.success('Authors updated')
    },
    onError: (error: Error) => {
      toast.error(`Bulk update failed: ${error.message}`)
    },
  })

  // Bulk delete mutation
  const bulkDeleteMutation = useMutation({
    mutationFn: async ({ authorIds, deleteFiles }: { authorIds: string[]; deleteFiles: boolean }) => {
      const deletePromises = authorIds.map(id =>
        authorsApi.delete(id, deleteFiles)
      )
      return Promise.all(deletePromises)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reading-room-authors'] })
      setSelectedIds(new Set())
      setBulkMode(false)
      setBulkDeleteDialogOpen(false)
      setBulkDeleteFiles(false)
      toast.success('Authors removed')
    },
    onError: (error: Error) => {
      toast.error(`Error deleting authors: ${error.message}`)
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
    const items: any[] = sortMode === 'author' ? authors : sortMode === 'book' ? books : seriesList
    if (selectedIds.size === items.length) {
      setSelectedIds(new Set())
    } else {
      const allIds = new Set<string>(items.map((item: any) => item.id as string))
      setSelectedIds(allIds)
    }
  }

  // Render author card
  const renderAuthorCard = (author: Author) => (
    <div
      key={author.id}
      className={`card p-0 hover:shadow-lg transition-shadow group ${
        bulkMode ? 'cursor-pointer' : ''
      } ${selectedIds.has(author.id) ? 'ring-2 ring-[#FF1493]' : ''}`}
      onClick={() => {
        if (bulkMode) {
          toggleSelection(author.id)
        } else {
          navigate(`/reading-room/authors/${author.id}`)
        }
      }}
    >
      {/* Author Image */}
      <div className="relative bg-gradient-to-br from-[#FF1493] to-[#FF8C00] h-32 flex items-center justify-center overflow-hidden">
        {author.image_url ? (
          <img
            src={`/api/v1/authors/${author.id}/cover-art`}
            alt={author.name}
            loading="lazy"
            className="w-full h-full object-cover"
            onError={(e) => {
              e.currentTarget.style.display = 'none'
            }}
          />
        ) : (
          <FiBook className="w-12 h-12 text-white/30" />
        )}
        {bulkMode && (
          <div className="absolute top-2 left-2">
            <input
              type="checkbox"
              checked={selectedIds.has(author.id)}
              onChange={() => toggleSelection(author.id)}
              className="w-5 h-5"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        )}
      </div>

      {/* Author Info */}
      <div className="p-3">
        <h3 className="font-semibold text-gray-900 dark:text-white truncate text-sm">
          {author.name}
        </h3>
        <div className="flex items-center justify-between mt-1">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {author.book_count || 0} book{(author.book_count || 0) !== 1 ? 's' : ''}
          </span>
          {author.is_monitored && (
            <span className="badge badge-sm badge-primary">
              <FiCheck className="w-3 h-3" />
            </span>
          )}
        </div>
      </div>
    </div>
  )

  // Render book card
  const renderBookCard = (book: Book) => (
    <div
      key={book.id}
      className="card p-0 hover:shadow-lg transition-shadow cursor-pointer"
      onClick={() => navigate(`/reading-room/books/${book.id}`)}
    >
      {/* Book Cover - square aspect ratio */}
      <div className="relative bg-gradient-to-br from-purple-600 to-purple-800 aspect-square flex items-center justify-center">
        <img
          src={book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : S54.defaultBookCover}
          alt={book.title}
          loading="lazy"
          className="w-full h-full object-contain"
        />
      </div>

      {/* Book Info */}
      <div className="p-3">
        <h3 className="font-semibold text-gray-900 dark:text-white truncate text-sm">
          {book.title}
        </h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-1">
          {book.author_name}
        </p>
        <div className="flex items-center justify-between mt-1">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {book.chapter_count || 0} chapter{(book.chapter_count || 0) !== 1 ? 's' : ''}
          </span>
          <div className="flex items-center gap-1">
            {book.status && (
              <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${
                book.status === 'downloaded'
                  ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
                  : book.status === 'wanted'
                  ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300'
                  : book.status === 'searching'
                  ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300'
                  : book.status === 'downloading'
                  ? 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300'
                  : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300'
              }`}>
                {book.status}
              </span>
            )}
            {book.monitored && (
              <span className="badge badge-sm badge-primary">
                <FiCheck className="w-3 h-3" />
              </span>
            )}
          </div>
        </div>
        {book.series_name && (
          <p className="text-[10px] text-gray-400 dark:text-gray-500 truncate mt-1">
            {book.series_name}{book.series_position ? ` #${book.series_position}` : ''}
          </p>
        )}
      </div>
    </div>
  )

  // Render series card
  const renderSeriesCard = (series: Series) => (
    <div
      key={series.id}
      className="card p-0 hover:shadow-lg transition-shadow cursor-pointer"
      onClick={() => navigate(`/reading-room/series/${series.id}`)}
    >
      {/* Series Cover */}
      <div className="relative bg-gradient-to-br from-teal-600 to-teal-800 aspect-square flex items-center justify-center">
        {series.cover_art_url ? (
          <img
            src={`/api/v1/series/${series.id}/cover-art`}
            alt={series.name}
            loading="lazy"
            className="w-full h-full object-contain"
          />
        ) : (
          <FiBook className="w-12 h-12 text-white/30" />
        )}
      </div>

      {/* Series Info */}
      <div className="p-3">
        <h3 className="font-semibold text-gray-900 dark:text-white truncate text-sm">
          {series.name}
        </h3>
        <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-1">
          {series.author_name}
        </p>
        <div className="flex items-center justify-between mt-1">
          <span className="text-xs text-gray-500 dark:text-gray-400">
            {series.book_count || 0} book{(series.book_count || 0) !== 1 ? 's' : ''}
          </span>
          {series.monitored && (
            <span className="badge badge-sm badge-primary">
              <FiCheck className="w-3 h-3" />
            </span>
          )}
        </div>
      </div>
    </div>
  )

  const items: any[] = sortMode === 'author' ? authors : sortMode === 'book' ? books : seriesList

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

  // =========================================================================
  // Book Import Tab Component
  // =========================================================================
  function BookImportTab() {
    const [bookImportJobId, setBookImportJobId] = useState<string | null>(null)
    const [isStarting, setIsStarting] = useState(false)

    // Fetch audiobook library paths
    const { data: libraryPathsData } = useQuery({
      queryKey: ['library-paths'],
      queryFn: async () => {
        const res = await authFetch('/api/v1/library/paths')
        if (!res.ok) throw new Error('Failed to fetch library paths')
        return res.json()
      },
    })

    const audiobookPaths = (libraryPathsData?.library_paths || []).filter(
      (p: any) => p.library_type === 'audiobook'
    )

    // Fetch latest import job for each path to show status
    const { data: importsData, refetch: refetchImports } = useQuery({
      queryKey: ['book-imports'],
      queryFn: async () => {
        const res = await authFetch('/api/v1/library/imports?limit=20')
        if (!res.ok) throw new Error('Failed to fetch imports')
        return res.json()
      },
      refetchInterval: bookImportJobId ? 3000 : false,
    })

    // Poll active job details
    const { data: activeJobData } = useQuery({
      queryKey: ['book-import-job', bookImportJobId],
      queryFn: async () => {
        const res = await authFetch(`/api/v1/library/imports/${bookImportJobId}`)
        if (!res.ok) throw new Error('Failed to fetch import status')
        return res.json()
      },
      enabled: !!bookImportJobId,
      refetchInterval: 3000,
    })

    // Stop polling when job completes
    useEffect(() => {
      if (activeJobData && ['completed', 'failed', 'cancelled'].includes(activeJobData.status)) {
        // Keep job ID visible but stop polling by clearing after a delay
        const timer = setTimeout(() => {
          refetchImports()
        }, 1000)
        return () => clearTimeout(timer)
      }
    }, [activeJobData?.status, refetchImports])

    // Auto-detect running job on mount
    useEffect(() => {
      if (importsData?.imports) {
        const running = importsData.imports.find(
          (imp: any) => imp.status === 'running' || imp.status === 'pending'
        )
        if (running && !bookImportJobId) {
          setBookImportJobId(running.id)
        }
      }
    }, [importsData, bookImportJobId])

    const startBookImport = useCallback(async (pathId: string) => {
      setIsStarting(true)
      try {
        const res = await authFetch(`/api/v1/library/paths/${pathId}/book-import`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Failed to start import' }))
          throw new Error(err.detail || 'Failed to start import')
        }
        const data = await res.json()
        setBookImportJobId(data.import_job_id)
        toast.success('Book import started')
        refetchImports()
      } catch (err: any) {
        toast.error(err.message || 'Failed to start book import')
      } finally {
        setIsStarting(false)
      }
    }, [refetchImports])

    const cancelImport = useCallback(async (jobId: string) => {
      try {
        const res = await authFetch(`/api/v1/library/imports/${jobId}/cancel`, {
          method: 'POST',
        })
        if (!res.ok) throw new Error('Failed to cancel import')
        toast.success('Import cancellation requested')
        refetchImports()
      } catch (err: any) {
        toast.error(err.message || 'Failed to cancel import')
      }
    }, [refetchImports])

    const getLatestImport = (pathId: string) => {
      if (!importsData?.imports) return null
      return importsData.imports.find((imp: any) => imp.library_path_id === pathId)
    }

    const getStatusColor = (status: string) => {
      switch (status) {
        case 'completed': return 'text-green-600 dark:text-green-400'
        case 'running': return 'text-blue-600 dark:text-blue-400'
        case 'pending': return 'text-yellow-600 dark:text-yellow-400'
        case 'failed': return 'text-red-600 dark:text-red-400'
        case 'cancelled': return 'text-gray-500 dark:text-gray-400'
        default: return 'text-gray-600 dark:text-gray-400'
      }
    }

    const getStatusBg = (status: string) => {
      switch (status) {
        case 'completed': return 'bg-green-100 dark:bg-green-900/30'
        case 'running': return 'bg-blue-100 dark:bg-blue-900/30'
        case 'pending': return 'bg-yellow-100 dark:bg-yellow-900/30'
        case 'failed': return 'bg-red-100 dark:bg-red-900/30'
        case 'cancelled': return 'bg-gray-100 dark:bg-gray-800'
        default: return 'bg-gray-100 dark:bg-gray-800'
      }
    }

    // Determine the active job to display progress for
    const activeJob = activeJobData || (bookImportJobId
      ? importsData?.imports?.find((imp: any) => imp.id === bookImportJobId)
      : null)

    if (audiobookPaths.length === 0) {
      return (
        <div className="card p-6">
          <div className="text-center py-12">
            <FiBook className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
              No Audiobook Libraries
            </h2>
            <p className="text-gray-600 dark:text-gray-400 mb-6">
              Add an audiobook library path in the Scanner tab to get started with book imports.
            </p>
          </div>
        </div>
      )
    }

    return (
      <div className="space-y-6">
        {/* Active Job Progress */}
        {activeJob && ['running', 'pending'].includes(activeJob.status) && (
          <div className="card p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                <FiLoader className="w-5 h-5 animate-spin text-blue-500" />
                Book Import In Progress
              </h3>
              <button
                className="btn btn-secondary text-sm"
                onClick={() => cancelImport(activeJob.id)}
              >
                <FiX className="w-4 h-4 mr-1" />
                Cancel
              </button>
            </div>

            {/* Progress Bar */}
            <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-3 mb-3">
              <div
                className="bg-[#FF1493] h-3 rounded-full transition-all duration-500"
                style={{ width: `${activeJob.progress_percent || 0}%` }}
              />
            </div>
            <div className="flex justify-between text-sm text-gray-600 dark:text-gray-400 mb-4">
              <span>{activeJob.current_action || 'Starting...'}</span>
              <span>{Math.round(activeJob.progress_percent || 0)}%</span>
            </div>

            {/* Statistics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-white">
                  {activeJob.files_scanned || 0}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">Files Scanned</div>
              </div>
              <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-white">
                  {activeJob.artists_found || 0}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">Authors Found</div>
              </div>
              <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-white">
                  {activeJob.albums_synced || 0}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">Books Created</div>
              </div>
              <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-gray-900 dark:text-white">
                  {activeJob.tracks_matched || 0}
                </div>
                <div className="text-xs text-gray-500 dark:text-gray-400">Chapters Created</div>
              </div>
            </div>
          </div>
        )}

        {/* Completed/Failed Job Summary */}
        {activeJob && ['completed', 'failed', 'cancelled'].includes(activeJob.status) && (
          <div className={`card p-6 ${activeJob.status === 'failed' ? 'border-red-200 dark:border-red-800' : ''}`}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
                {activeJob.status === 'completed' && <FiCheck className="w-5 h-5 text-green-500" />}
                {activeJob.status === 'failed' && <FiX className="w-5 h-5 text-red-500" />}
                {activeJob.status === 'cancelled' && <FiX className="w-5 h-5 text-gray-500" />}
                Book Import {activeJob.status.charAt(0).toUpperCase() + activeJob.status.slice(1)}
              </h3>
              <button
                className="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                onClick={() => setBookImportJobId(null)}
              >
                Dismiss
              </button>
            </div>

            {activeJob.status === 'failed' && activeJob.error_message && (
              <div className="bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 rounded-lg p-3 mb-4 text-sm">
                {activeJob.error_message}
              </div>
            )}

            {activeJob.status === 'completed' && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {activeJob.files_scanned || 0}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Files Scanned</div>
                </div>
                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {activeJob.artists_found || 0}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Authors Found</div>
                </div>
                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {activeJob.albums_synced || 0}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Books Created</div>
                </div>
                <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {activeJob.tracks_matched || 0}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Chapters Created</div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Library Paths */}
        <div className="space-y-4">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
            Audiobook Libraries
          </h3>
          {audiobookPaths.map((path: any) => {
            const latestImport = getLatestImport(path.id)
            const isActive = latestImport && ['running', 'pending'].includes(latestImport.status)

            return (
              <div key={path.id} className="card p-5">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <h4 className="font-medium text-gray-900 dark:text-white truncate">
                      {path.name}
                    </h4>
                    <p className="text-sm text-gray-500 dark:text-gray-400 truncate">
                      {path.path}
                    </p>
                    <div className="flex items-center gap-4 mt-1 text-xs text-gray-500 dark:text-gray-400">
                      <span>{(path.total_files || 0).toLocaleString()} files</span>
                      {path.total_size_bytes > 0 && (
                        <span>{(path.total_size_bytes / (1024 ** 3)).toFixed(1)} GB</span>
                      )}
                      {path.last_scan_at && (
                        <span>Last scan: {new Date(path.last_scan_at).toLocaleDateString()}</span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    {latestImport && (
                      <span className={`text-xs font-medium px-2 py-1 rounded-full ${getStatusBg(latestImport.status)} ${getStatusColor(latestImport.status)}`}>
                        {latestImport.status === 'completed' && <FiCheck className="w-3 h-3 inline mr-1" />}
                        {latestImport.status}
                      </span>
                    )}
                    <button
                      className="btn btn-primary text-sm"
                      onClick={() => startBookImport(path.id)}
                      disabled={isStarting || !!isActive}
                    >
                      {isStarting ? (
                        <>
                          <FiLoader className="w-4 h-4 mr-2 animate-spin" />
                          Starting...
                        </>
                      ) : isActive ? (
                        <>
                          <FiLoader className="w-4 h-4 mr-2 animate-spin" />
                          Running...
                        </>
                      ) : (
                        <>
                          <FiDownload className="w-4 h-4 mr-2" />
                          Start Book Import
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Previous Imports History */}
        {importsData?.imports && importsData.imports.length > 0 && (
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">
              Import History
            </h3>
            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800">
                  <tr>
                    <th className="text-left px-4 py-2 text-gray-600 dark:text-gray-400">Status</th>
                    <th className="text-left px-4 py-2 text-gray-600 dark:text-gray-400">Files</th>
                    <th className="text-left px-4 py-2 text-gray-600 dark:text-gray-400">Authors</th>
                    <th className="text-left px-4 py-2 text-gray-600 dark:text-gray-400">Books</th>
                    <th className="text-left px-4 py-2 text-gray-600 dark:text-gray-400">Chapters</th>
                    <th className="text-left px-4 py-2 text-gray-600 dark:text-gray-400">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                  {importsData.imports.slice(0, 10).map((imp: any) => (
                    <tr key={imp.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                      <td className="px-4 py-2">
                        <span className={`font-medium ${getStatusColor(imp.status)}`}>
                          {imp.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-gray-700 dark:text-gray-300">{imp.files_scanned || 0}</td>
                      <td className="px-4 py-2 text-gray-700 dark:text-gray-300">{imp.artists_found || 0}</td>
                      <td className="px-4 py-2 text-gray-700 dark:text-gray-300">{imp.albums_synced || 0}</td>
                      <td className="px-4 py-2 text-gray-700 dark:text-gray-300">{imp.tracks_matched || 0}</td>
                      <td className="px-4 py-2 text-gray-500 dark:text-gray-400">
                        {imp.created_at ? new Date(imp.created_at).toLocaleString() : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6 overflow-x-hidden">
      <Toaster position="top-right" />
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">
            Reading Room {activeTab === 'browse' && totalCount > 0 && (
              <span className="text-gray-500 dark:text-gray-400">({totalCount.toLocaleString()})</span>
            )}
          </h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            {activeTab === 'browse' && 'Browse and manage your audiobook collection'}
            {activeTab === 'scanner' && 'Index and search your audiobook files'}
            {activeTab === 'import' && 'Import books from your audiobook library'}
            {activeTab === 'unlinked' && 'Audiobook files that could not be linked to book chapters'}
            {activeTab === 'unorganized' && 'Audiobook files that have not been organized into the standard folder structure'}
          </p>
        </div>
        {activeTab === 'browse' && (
          <div className="flex items-center gap-2">
            {/* Desktop buttons */}
            <div className="hidden lg:flex flex-wrap gap-2">
              <button className="btn btn-secondary" onClick={() => queryClient.invalidateQueries({ queryKey: ['reading-room-authors', 'reading-room-books', 'reading-room-series'] })} title="Refresh library data">
                <FiRefreshCw className="w-4 h-4 mr-2" />
                Refresh
              </button>
              {isDjOrAbove && (
                <button
                  className="btn btn-secondary"
                  onClick={() => fetchAllMetadataMutation.mutate(false)}
                  disabled={fetchAllMetadataMutation.isPending || !!metadataRefreshState}
                  title="Fetch author images, biographies and book cover art for the whole library"
                >
                  {(fetchAllMetadataMutation.isPending || metadataRefreshState)
                    ? <FiLoader className="w-4 h-4 mr-2 animate-spin" />
                    : <FiDownload className="w-4 h-4 mr-2" />
                  }
                  {metadataRefreshState ? 'Fetching…' : 'Fetch Metadata'}
                </button>
              )}
              {isDjOrAbove && (
                <button className="btn btn-primary" onClick={() => setShowAddAuthorModal(true)} title="Add a new author from MusicBrainz">
                  <FiPlus className="w-4 h-4 mr-2" />
                  Add Author
                </button>
              )}
            </div>

            {/* Mobile/Tablet: Add Author button + actions menu */}
            <div className="flex lg:hidden items-center gap-2">
              {isDjOrAbove && (
                <button className="btn btn-primary" onClick={() => setShowAddAuthorModal(true)} title="Add a new author from MusicBrainz">
                  <FiPlus className="w-4 h-4 mr-2" />
                  Add Author
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
                        onClick={() => { queryClient.invalidateQueries({ queryKey: ['reading-room-authors', 'reading-room-books', 'reading-room-series'] }); setActionsMenuOpen(false) }}
                      >
                        <FiRefreshCw className="w-4 h-4 mr-3 text-gray-500" />
                        Refresh
                      </button>
                      {isDjOrAbove && (
                        <button
                          className="w-full flex items-center px-4 py-2.5 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-[#1C2128] disabled:opacity-50"
                          onClick={() => fetchAllMetadataMutation.mutate(false)}
                          disabled={fetchAllMetadataMutation.isPending || !!metadataRefreshState}
                        >
                          {(fetchAllMetadataMutation.isPending || metadataRefreshState)
                            ? <FiLoader className="w-4 h-4 mr-3 text-gray-500 animate-spin" />
                            : <FiDownload className="w-4 h-4 mr-3 text-gray-500" />
                          }
                          {metadataRefreshState ? 'Fetching…' : 'Fetch Metadata'}
                        </button>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Metadata refresh progress banner */}
      {metadataRefreshState && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-[#FF1493]/10 border border-[#FF1493]/30 text-sm">
          <FiLoader className="w-4 h-4 text-[#FF1493] animate-spin flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="font-medium text-gray-900 dark:text-white">Fetching metadata</span>
            <span className="text-gray-600 dark:text-gray-400 ml-2">
              {runningRefreshJobs != null && runningRefreshJobs > 0
                ? `${runningRefreshJobs} of ${metadataRefreshState.totalAuthors} authors remaining…`
                : `Processing ${metadataRefreshState.totalAuthors} authors…`}
            </span>
          </div>
          <button
            onClick={() => setMetadataRefreshState(null)}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 flex-shrink-0"
            title="Dismiss (refresh continues in background)"
          >
            <FiX className="w-4 h-4" />
          </button>
        </div>
      )}

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
            Book Import
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
                  <option value="author">Authors</option>
                  <option value="book">Books</option>
                  <option value="series">Series</option>
                </select>
              </div>

              {/* Order By Dropdown */}
              {sortMode === 'author' && (
                <>
                  <div className="relative">
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                      Order by
                    </label>
                    <select
                      value={authorSortBy}
                      onChange={(e) => { setAuthorSortBy(e.target.value as AuthorSortBy); setPage(1) }}
                      className="px-4 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#161B22] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                      title="Sort authors"
                    >
                      <option value="name">Name</option>
                      <option value="files_desc">Most Files</option>
                      <option value="files_asc">Least Files</option>
                      <option value="added_at">Recently Added</option>
                    </select>
                  </div>
                  {(genresData?.genres?.length ?? 0) > 0 && (
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
                        {genresData?.genres?.map((g: string) => (
                          <option key={g} value={g}>{g}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </>
              )}
              {sortMode === 'book' && (
                <div className="relative">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Order by
                  </label>
                  <select
                    value={bookSortBy}
                    onChange={(e) => { setBookSortBy(e.target.value as BookSortBy); setPage(1) }}
                    className="px-4 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#161B22] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                    title="Sort books"
                  >
                    <option value="release_date">Release Date</option>
                    <option value="title">Title</option>
                    <option value="author">Author</option>
                    <option value="files_desc">Most Files</option>
                    <option value="files_asc">Least Files</option>
                    <option value="added_at">Recently Added</option>
                  </select>
                </div>
              )}
              {sortMode === 'series' && (
                <div className="relative">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Order by
                  </label>
                  <select
                    value={seriesSortBy}
                    onChange={(e) => { setSeriesSortBy(e.target.value as SeriesSortBy); setPage(1) }}
                    className="px-4 py-2 border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#161B22] text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-[#FF1493]"
                    title="Sort series"
                  >
                    <option value="name">Name</option>
                    <option value="book_count">Most Books</option>
                    <option value="added_at">Recently Added</option>
                  </select>
                </div>
              )}

              {/* Filter Toggles */}
              <div className="flex flex-wrap items-end gap-2">
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
              </div>

              {/* Bulk Mode (Authors only, DJ+ for monitor, Director for delete) */}
              {sortMode === 'author' && isDjOrAbove && (
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
                placeholder={`Search ${sortMode === 'author' ? 'authors' : sortMode === 'book' ? 'books' : 'series'}...`}
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
          {bulkMode && selectedIds.size > 0 && sortMode === 'author' && (
            <div className="card p-4 bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {selectedIds.size} author{selectedIds.size !== 1 ? 's' : ''} selected
                </span>
                <div className="flex space-x-2">
                  <button
                    className="btn btn-sm btn-primary"
                    onClick={() => bulkUpdateMutation.mutate(true)}
                    disabled={bulkUpdateMutation.isPending}
                    title="Monitor all selected authors"
                  >
                    Monitor Selected
                  </button>
                  <button
                    className="btn btn-sm btn-secondary"
                    onClick={() => bulkUpdateMutation.mutate(false)}
                    disabled={bulkUpdateMutation.isPending}
                    title="Unmonitor all selected authors"
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
                    title="Delete all selected authors"
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
              <FiBook className="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <p className="text-gray-500 dark:text-gray-400">
                No {sortMode === 'author' ? 'authors' : sortMode === 'book' ? 'books' : 'series'} found
              </p>
            </div>
          ) : (
            /* Author/Book/Series Grid */
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 2xl:grid-cols-10 gap-3">
              {sortMode === 'author' && authors.map((author: Author) => renderAuthorCard(author))}
              {sortMode === 'book' && books.map((book: Book) => renderBookCard(book))}
              {sortMode === 'series' && seriesList.map((s: Series) => renderSeriesCard(s))}
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
        <LibraryScanner libraryType="audiobook" />
      )}

      {activeTab === 'import' && (
        <BookImportTab />
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
                    no_matching_track: { color: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300', label: 'No Matching Chapter' },
                    artist_not_in_db: { color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300', label: 'Author Not Imported' },
                    album_not_in_db: { color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300', label: 'Book Not Imported' },
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
                  placeholder="Search files, authors, books..."
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
                <option value="no_matching_track">No Matching Chapter</option>
                <option value="artist_not_in_db">Author Not Imported</option>
                <option value="album_not_in_db">Book Not Imported</option>
              </select>
              <button
                className="btn btn-sm btn-secondary"
                onClick={() => {
                  refetchUnlinked()
                  queryClient.invalidateQueries({ queryKey: ['reading-room-unlinked-summary'] })
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
                    a.download = 'unlinked_audiobook_files.csv'
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
                    : 'All audiobook files are linked!'}
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
                          { key: 'artist', label: 'Author' },
                          { key: 'album', label: 'Book' },
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
                          artist_not_in_db: { color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300', label: 'No Author' },
                          album_not_in_db: { color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300', label: 'No Book' },
                        }
                        const badge = reasonBadges[file.reason] || { color: 'bg-gray-100 text-gray-800', label: file.reason }
                        const fileName = file.file_path.split('/').pop() || file.file_path
                        const isEditing = editingUnlinkedId === file.id
                        return (
                          <tr key={file.id} className="hover:bg-gray-50 dark:hover:bg-[#1C2128]/30">
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
                                      onClick={async () => {
                                        const filename = file.file_path.split('/').pop() || file.file_path
                                        if (!window.confirm(`Delete "${filename}" from disk? This cannot be undone.`)) return
                                        try {
                                          await fileOrganizationApi.deleteUnlinkedFile(file.id)
                                          toast.success(`Deleted ${filename}`)
                                          queryClient.invalidateQueries({ queryKey: ['reading-room-unlinked-files'] })
                                          queryClient.invalidateQueries({ queryKey: ['reading-room-unlinked-summary'] })
                                        } catch (err: any) {
                                          toast.error(err?.response?.data?.detail || 'Failed to delete file')
                                        }
                                      }}
                                      className="p-1.5 rounded text-gray-400 hover:text-red-400 hover:bg-red-500/20 transition-colors"
                                      title="Delete file from disk"
                                    >
                                      <FiTrash2 size={14} />
                                    </button>
                                  </>
                                )}
                              </div>
                            </td>
                          </tr>
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
                  placeholder="Search files, authors, books..."
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
                  queryClient.invalidateQueries({ queryKey: ['reading-room-unorganized-summary'] })
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
                    : 'All audiobook files are organized!'}
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
                          { key: 'artist', label: 'Author', width: '' },
                          { key: 'album', label: 'Book', width: '' },
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
                Remove {selectedIds.size} Author{selectedIds.size !== 1 ? 's' : ''}
              </h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
                This will delete all associated books, chapters, and download history for the selected authors.
              </p>

              {(() => {
                const totalLinked = authors
                  .filter((a: Author) => selectedIds.has(a.id))
                  .reduce((sum: number, a: Author) => sum + (a.linked_files_count || 0), 0)
                return totalLinked > 0 ? (
                  <>
                    <div className="mb-4 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                      <p className="text-sm text-amber-800 dark:text-amber-200 mb-3">
                        The selected authors have <strong>{totalLinked}</strong> linked file{totalLinked !== 1 ? 's' : ''} on disk.
                      </p>
                      <label className="flex items-center space-x-3 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={bulkDeleteFiles}
                          onChange={(e) => setBulkDeleteFiles(e.target.checked)}
                          className="rounded border-gray-300 text-red-600 focus:ring-red-500"
                        />
                        <span className="text-sm font-medium text-amber-900 dark:text-amber-100">
                          Also delete audiobook files from disk
                        </span>
                      </label>
                    </div>
                    {bulkDeleteFiles && (
                      <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
                        <p className="text-sm text-red-800 dark:text-red-200">
                          <strong>Warning:</strong> This will permanently delete {totalLinked} audiobook file{totalLinked !== 1 ? 's' : ''} from disk.
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
                onClick={() => bulkDeleteMutation.mutate({ authorIds: Array.from(selectedIds), deleteFiles: bulkDeleteFiles })}
                disabled={bulkDeleteMutation.isPending}
              >
                {bulkDeleteMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Removing...
                  </>
                ) : (
                  bulkDeleteFiles ? 'Remove & Delete Files' : `Remove ${selectedIds.size} Author${selectedIds.size !== 1 ? 's' : ''}`
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Author Modal */}
      {showAddAuthorModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Add Author</h2>
                <button
                  onClick={() => {
                    setShowAddAuthorModal(false)
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
                    placeholder="Search MusicBrainz for author..."
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
                          <p className="text-xs text-gray-400">{result.country} {result.type && `\u2022 ${result.type}`}</p>
                        </div>
                        <button
                          onClick={() => addAuthorMutation.mutate(result.id)}
                          disabled={addAuthorMutation.isPending}
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

export default ReadingRoom
