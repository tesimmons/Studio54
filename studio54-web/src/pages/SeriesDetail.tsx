import { useState, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authFetch, bookPlaylistsApi, seriesApi, booksApi } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import {
  FiArrowLeft,
  FiCheck,
  FiX,
  FiBook,
  FiBookOpen,
  FiTrash2,
  FiUser,
  FiHash,
  FiList,
  FiPlay,
  FiRefreshCw,
  FiPlus,
  FiMinus,
  FiMenu,
} from 'react-icons/fi'
import type { BookPlaylistDetail } from '../types'
import { S54 } from '../assets/graphics'
import CoverArtUploader from '../components/CoverArtUploader'
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

// ---------------------------------------------------------------------------
// Local interfaces (series detail payload)
// ---------------------------------------------------------------------------

interface SeriesBook {
  id: string
  title: string
  series_position: number | null
  status: string
  monitored: boolean
  chapter_count: number
  linked_files_count: number
  cover_art_url: string | null
  release_date: string | null
}

interface SeriesWithBooks {
  id: string
  name: string
  author_id: string
  author_name: string
  description: string | null
  total_expected_books: number | null
  book_count: number
  monitored: boolean
  cover_art_url: string | null
  added_at: string | null
  updated_at: string | null
  books: SeriesBook[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const getStatusColor = (status: string) => {
  switch (status.toLowerCase()) {
    case 'downloaded':
      return 'badge-success'
    case 'wanted':
      return 'badge-warning'
    case 'searching':
    case 'downloading':
      return 'badge-info'
    case 'failed':
      return 'badge-danger'
    default:
      return 'badge-secondary'
  }
}

// ---------------------------------------------------------------------------
// Sortable Book Row (drag-and-drop)
// ---------------------------------------------------------------------------

function SortableBookRow({
  book,
  isDjOrAbove,
  onNavigate,
  onRemove,
  removeIsPending,
  removeBookId,
}: {
  book: SeriesBook
  isDjOrAbove: boolean
  onNavigate: (id: string) => void
  onRemove: (book: { id: string; title: string }) => void
  removeIsPending: boolean
  removeBookId: string | undefined
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: book.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : undefined,
  }

  const chapterProgress =
    book.chapter_count > 0
      ? Math.round((book.linked_files_count / book.chapter_count) * 100)
      : 0

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`card p-0 hover:shadow-lg transition-shadow cursor-pointer group flex items-center ${isDragging ? 'bg-[#FF1493]/5 dark:bg-[#FF1493]/15 shadow-lg' : ''}`}
      onClick={() => onNavigate(book.id)}
    >
      {/* Drag handle (DJ+ only) */}
      {isDjOrAbove && (
        <div className="flex-shrink-0 w-8 flex items-center justify-center">
          <button
            className="cursor-grab active:cursor-grabbing touch-none p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            onClick={(e) => e.stopPropagation()}
            {...attributes}
            {...listeners}
          >
            <FiMenu className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Position number */}
      <div className="flex-shrink-0 w-12 h-full flex items-center justify-center text-lg font-bold text-gray-400 dark:text-gray-500">
        {book.series_position != null ? `#${book.series_position}` : '--'}
      </div>

      {/* Cover thumbnail */}
      <div className="flex-shrink-0 w-14 h-14 sm:w-16 sm:h-16 bg-gradient-to-br from-gray-600 to-gray-800 flex items-center justify-center overflow-hidden">
        <img
          src={book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : S54.defaultBookCover}
          alt={book.title}
          className="w-full h-full object-contain"
        />
      </div>

      {/* Book info */}
      <div className="flex-1 min-w-0 px-4 py-3">
        <div className="flex items-center gap-2 mb-1">
          <h3 className="font-semibold text-gray-900 dark:text-white text-sm truncate group-hover:text-[#FF1493] transition-colors">
            {book.title}
          </h3>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
          <span>{book.linked_files_count} / {book.chapter_count} chapters linked</span>
          {book.release_date && (
            <span>{new Date(book.release_date).getFullYear()}</span>
          )}
        </div>

        {/* Chapter progress bar */}
        {book.chapter_count > 0 && (
          <div className="w-full max-w-xs bg-gray-200 dark:bg-[#0D1117] rounded-full h-1.5 mt-2">
            <div
              className={`h-1.5 rounded-full transition-all ${
                book.linked_files_count >= book.chapter_count
                  ? 'bg-green-500'
                  : book.linked_files_count > 0
                    ? 'bg-amber-500'
                    : 'bg-gray-400 dark:bg-gray-600'
              }`}
              style={{ width: `${Math.min(100, chapterProgress)}%` }}
            />
          </div>
        )}
      </div>

      {/* Right side: status badge + monitored + actions */}
      <div className="flex-shrink-0 flex items-center gap-2 pr-4">
        <span className={`badge ${getStatusColor(book.status)}`}>
          {book.status}
        </span>
        {book.monitored ? (
          <FiCheck className="w-4 h-4 text-green-500" title="Monitored" />
        ) : (
          <FiX className="w-4 h-4 text-gray-400" title="Not monitored" />
        )}
        {isDjOrAbove && (
          <button
            className="p-1 text-gray-400 hover:text-red-500 transition-colors"
            onClick={(e) => {
              e.stopPropagation()
              onRemove({ id: book.id, title: book.title })
            }}
            disabled={removeIsPending}
            title="Remove from series"
          >
            {removeIsPending && removeBookId === book.id ? (
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-red-500"></div>
            ) : (
              <FiMinus className="w-4 h-4" />
            )}
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function SeriesDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { isDjOrAbove } = useAuth()

  // Toast notification state
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null)

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 5000)
  }, [])

  // Delete confirmation dialog
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)

  // Remove book confirmation dialog
  const [removeBookTarget, setRemoveBookTarget] = useState<{ id: string; title: string } | null>(null)

  // Add book dialog
  const [addBookDialogOpen, setAddBookDialogOpen] = useState(false)

  // ---------------------------------------------------------------------------
  // Queries
  // ---------------------------------------------------------------------------

  const { data: series, isLoading } = useQuery({
    queryKey: ['series', id],
    queryFn: async (): Promise<SeriesWithBooks> => {
      const response = await authFetch(`/api/v1/series/${id}`)
      if (!response.ok) throw new Error('Failed to fetch series')
      return response.json()
    },
    enabled: !!id,
  })

  // Fetch series playlist
  const { data: playlist } = useQuery({
    queryKey: ['series-playlist', id],
    queryFn: async (): Promise<BookPlaylistDetail> => {
      return bookPlaylistsApi.get(id!)
    },
    enabled: !!id,
    retry: false,
  })

  // ---------------------------------------------------------------------------
  // Mutations
  // ---------------------------------------------------------------------------

  // Create/refresh series playlist
  const createPlaylistMutation = useMutation({
    mutationFn: async () => {
      return bookPlaylistsApi.create(id!)
    },
    onSuccess: (data) => {
      showToast(data.message || 'Playlist creation started', 'success')
      // Refetch after a short delay to allow the task to complete
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['series-playlist', id] })
      }, 3000)
    },
    onError: (error: Error) => {
      showToast(`Failed to create playlist: ${error.message}`, 'error')
    },
  })

  // Toggle series monitoring (cascades to all books)
  const updateMonitoringMutation = useMutation({
    mutationFn: async (monitored: boolean) => {
      const response = await authFetch(`/api/v1/series/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ monitored }),
      })
      if (!response.ok) throw new Error('Failed to update monitoring')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['series', id] })
      queryClient.invalidateQueries({ queryKey: ['series'] })
    },
    onError: (error: Error) => {
      showToast(`Failed to update monitoring: ${error.message}`, 'error')
    },
  })

  // Delete series
  const deleteSeriesMutation = useMutation({
    mutationFn: async () => {
      const response = await authFetch(`/api/v1/series/${id}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Failed to delete series' }))
        throw new Error(err.detail || 'Failed to delete series')
      }
      return response.json()
    },
    onSuccess: () => {
      setDeleteDialogOpen(false)
      queryClient.invalidateQueries({ queryKey: ['series'] })
      navigate('/reading-room')
    },
    onError: (error: Error) => {
      showToast(`Failed to delete series: ${error.message}`, 'error')
    },
  })

  // Fetch author's unlinked books (for add-book dialog)
  const { data: authorBooks } = useQuery({
    queryKey: ['author-books-unlinked', series?.author_id],
    queryFn: async () => {
      const result = await booksApi.list({ author_id: series!.author_id, limit: 500 })
      return result.books || []
    },
    enabled: !!series?.author_id && addBookDialogOpen,
  })

  // Add book to series mutation
  const addBookMutation = useMutation({
    mutationFn: async ({ bookId, position }: { bookId: string; position?: number }) => {
      return seriesApi.addBook(id!, bookId, position)
    },
    onSuccess: () => {
      showToast('Book added to series', 'success')
      queryClient.invalidateQueries({ queryKey: ['series', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to add book: ${error.message}`, 'error')
    },
  })

  // Remove book from series mutation
  const removeBookMutation = useMutation({
    mutationFn: async (bookId: string) => {
      return seriesApi.removeBook(id!, bookId)
    },
    onSuccess: (data) => {
      showToast(data.message || 'Book removed from series', 'success')
      queryClient.invalidateQueries({ queryKey: ['series', id] })
    },
    onError: (error: any) => {
      const detail = error?.response?.data?.detail || error?.message || 'Unknown error'
      console.error('Remove book from series failed:', detail, error)
      showToast(`Failed to remove book: ${detail}`, 'error')
    },
  })

  // Reorder (move book up/down)
  const reorderMutation = useMutation({
    mutationFn: async (bookIds: string[]) => {
      return seriesApi.reorder(id!, bookIds)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['series', id] })
    },
    onError: (error: Error) => {
      showToast(`Failed to reorder: ${error.message}`, 'error')
    },
  })

  // ---------------------------------------------------------------------------
  // Derived data
  // ---------------------------------------------------------------------------

  const sortedBooks = (series?.books || []).slice().sort((a, b) => {
    if (a.series_position == null && b.series_position == null) return 0
    if (a.series_position == null) return 1
    if (b.series_position == null) return -1
    return a.series_position - b.series_position
  })

  const downloadedCount = sortedBooks.filter(
    (b) => b.status.toLowerCase() === 'downloaded'
  ).length

  // ---------------------------------------------------------------------------
  // Drag-and-drop sensors + handler
  // ---------------------------------------------------------------------------

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return

    const oldIndex = sortedBooks.findIndex(b => b.id === active.id)
    const newIndex = sortedBooks.findIndex(b => b.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return

    const newOrder = arrayMove(sortedBooks.map(b => b.id), oldIndex, newIndex)
    reorderMutation.mutate(newOrder)
  }, [sortedBooks, reorderMutation])

  // ---------------------------------------------------------------------------
  // Render: Loading / Not found states
  // ---------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
      </div>
    )
  }

  if (!series) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen">
        <p className="text-gray-500 dark:text-gray-400 mb-4">Series not found</p>
        <button className="btn btn-primary" onClick={() => navigate('/reading-room')}>
          Back to Reading Room
        </button>
      </div>
    )
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      {/* Toast Notification */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium transition-all ${
            toast.type === 'success'
              ? 'bg-green-600 text-white'
              : toast.type === 'error'
                ? 'bg-red-600 text-white'
                : 'bg-blue-600 text-white'
          }`}
        >
          {toast.message}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Header                                                              */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col sm:flex-row items-start gap-4 sm:gap-6 min-w-0">
          {/* Cover Art */}
          <CoverArtUploader
            entityType="series"
            entityId={id!}
            currentUrl={series.cover_art_url}
            onSuccess={() => queryClient.invalidateQueries({ queryKey: ['series', id] })}
            uploadFn={seriesApi.uploadCoverArt}
            uploadFromUrlFn={seriesApi.uploadCoverArtFromUrl}
            fallback={
              <div className="w-full h-full bg-gradient-to-br from-[#FF1493] to-[#FF8C00] flex items-center justify-center">
                <FiBookOpen className="w-24 h-24 text-white/30" />
              </div>
            }
            alt={series.name}
            className="w-28 h-28 sm:w-48 sm:h-48 rounded-lg overflow-hidden flex-shrink-0"
          />

          {/* Series Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center space-x-3 mb-2">
              <button
                className="text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
                onClick={() => window.history.length > 1 ? navigate(-1) : navigate('/reading-room')}
                title="Back to Reading Room"
              >
                <FiArrowLeft className="w-5 h-5" />
              </button>
              <h1 className="text-xl sm:text-4xl font-bold text-gray-900 dark:text-white truncate">
                {series.name}
              </h1>
            </div>

            {/* Author link */}
            <div className="flex items-center space-x-2 mt-1">
              <FiUser className="w-4 h-4 text-gray-400" />
              <Link
                to={`/reading-room/authors/${series.author_id}`}
                className="text-sm text-[#FF1493] hover:underline"
              >
                {series.author_name}
              </Link>
            </div>

            {/* Stats row */}
            <div className="flex flex-wrap items-center gap-3 sm:gap-6 mt-4 text-sm">
              <div className="flex items-center space-x-2">
                <FiBook className="w-4 h-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">
                  {series.book_count || sortedBooks.length} Book{(series.book_count || sortedBooks.length) !== 1 ? 's' : ''}
                </span>
              </div>
              <div className="flex items-center space-x-2">
                <FiCheck className="w-4 h-4 text-gray-400" />
                <span className="text-gray-600 dark:text-gray-400">
                  {downloadedCount} of {sortedBooks.length} books downloaded
                </span>
              </div>
              {series.total_expected_books != null && (
                <div className="flex items-center space-x-2">
                  <FiHash className="w-4 h-4 text-gray-400" />
                  <span className="text-gray-600 dark:text-gray-400">
                    {series.total_expected_books} expected
                  </span>
                </div>
              )}
            </div>

            {/* Description */}
            {series.description && (
              <div className="mt-4 text-sm text-gray-600 dark:text-gray-400 max-w-3xl">
                <p className="line-clamp-4">{series.description}</p>
              </div>
            )}

            {/* Playlist Info + Actions */}
            {playlist && (
              <div className="mt-3 flex items-center gap-3 text-sm text-gray-500 dark:text-gray-400">
                <FiList className="w-4 h-4" />
                <span>
                  {playlist.chapter_count} chapters
                  {playlist.total_duration_ms > 0 && (
                    <> &middot; {Math.round(playlist.total_duration_ms / 60000)} min</>
                  )}
                </span>
              </div>
            )}

            {/* Monitoring Toggle + Playlist Actions */}
            <div className="mt-4 flex items-center space-x-4">
              {isDjOrAbove ? (
                <button
                  className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                    series.monitored
                      ? 'bg-success-600 text-white hover:bg-success-700'
                      : 'bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                  }`}
                  onClick={() => updateMonitoringMutation.mutate(!series.monitored)}
                  disabled={updateMonitoringMutation.isPending}
                  title={
                    series.monitored
                      ? 'Unmonitor this series (cascades to all books)'
                      : 'Monitor this series (cascades to all books)'
                  }
                >
                  {updateMonitoringMutation.isPending ? (
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                  ) : (
                    <div className="flex items-center">
                      {series.monitored ? (
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
                <span
                  className={`px-4 py-2 rounded-lg font-medium ${
                    series.monitored
                      ? 'bg-success-600/20 text-success-700 dark:text-success-400'
                      : 'bg-gray-200 dark:bg-[#0D1117] text-gray-500 dark:text-gray-400'
                  }`}
                >
                  {series.monitored ? 'Monitored' : 'Not Monitored'}
                </span>
              )}

              {/* Playlist buttons */}
              {isDjOrAbove && (
                <button
                  className="px-4 py-2 rounded-lg font-medium transition-colors bg-[#FF1493]/10 text-[#FF1493] hover:bg-[#FF1493]/20"
                  onClick={() => createPlaylistMutation.mutate()}
                  disabled={createPlaylistMutation.isPending}
                  title={playlist ? 'Refresh series playlist' : 'Create series playlist'}
                >
                  <div className="flex items-center">
                    {createPlaylistMutation.isPending ? (
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-[#FF1493] mr-2"></div>
                    ) : playlist ? (
                      <FiRefreshCw className="w-4 h-4 mr-2" />
                    ) : (
                      <FiList className="w-4 h-4 mr-2" />
                    )}
                    {playlist ? 'Refresh Playlist' : 'Create Playlist'}
                  </div>
                </button>
              )}

              {playlist && playlist.chapter_count > 0 && (
                <button
                  className="px-4 py-2 rounded-lg font-medium transition-colors bg-[#FF1493] text-white hover:bg-[#FF1493]/80"
                  onClick={() => {
                    const firstChapter = playlist.chapters?.[0]
                    if (firstChapter?.file_path) {
                      window.dispatchEvent(new CustomEvent('play-book-playlist', {
                        detail: { seriesId: id, playlistId: playlist.id }
                      }))
                    }
                  }}
                  title="Play entire series from chapter 1"
                >
                  <div className="flex items-center">
                    <FiPlay className="w-4 h-4 mr-2" />
                    Play Series
                  </div>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Delete button (top-right) */}
        {isDjOrAbove && (
          <button
            className="text-gray-400 hover:text-red-500 transition-colors p-2"
            onClick={() => setDeleteDialogOpen(true)}
            title="Delete series"
          >
            <FiTrash2 className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Books List                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Books
          </h2>
          {isDjOrAbove && (
            <button
              className="btn btn-secondary text-sm"
              onClick={() => setAddBookDialogOpen(true)}
              title="Add a book to this series"
            >
              <FiPlus className="w-4 h-4 mr-1" />
              Add Book
            </button>
          )}
        </div>

        {sortedBooks.length === 0 ? (
          <div className="card p-8 text-center">
            <FiBook className="w-12 h-12 mx-auto text-gray-400 mb-3" />
            <p className="text-gray-500 dark:text-gray-400">
              No books in this series yet.
            </p>
          </div>
        ) : (
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext
              items={sortedBooks.map(b => b.id)}
              strategy={verticalListSortingStrategy}
            >
              <div className="space-y-2">
                {sortedBooks.map((book) => (
                  <SortableBookRow
                    key={book.id}
                    book={book}
                    isDjOrAbove={isDjOrAbove}
                    onNavigate={(bookId) => navigate(`/reading-room/books/${bookId}`)}
                    onRemove={(b) => setRemoveBookTarget(b)}
                    removeIsPending={removeBookMutation.isPending}
                    removeBookId={removeBookMutation.variables as string | undefined}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Delete Confirmation Dialog                                          */}
      {/* ------------------------------------------------------------------ */}
      {deleteDialogOpen && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">
              Delete Series
            </h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Are you sure you want to delete <strong>{series.name}</strong>? This action
              cannot be undone. Books in the series will be unlinked but not deleted.
            </p>
            <div className="flex justify-end space-x-3 pt-2">
              <button
                className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D] transition-colors"
                onClick={() => setDeleteDialogOpen(false)}
              >
                Cancel
              </button>
              <button
                className="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-colors"
                onClick={() => deleteSeriesMutation.mutate()}
                disabled={deleteSeriesMutation.isPending}
              >
                {deleteSeriesMutation.isPending ? 'Deleting...' : 'Delete Series'}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Remove Book Confirmation Dialog */}
      {removeBookTarget && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-6 space-y-4">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white">
              Remove Book from Series
            </h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Remove <strong>{removeBookTarget.title}</strong> from{' '}
              <strong>{series.name}</strong>? The book will not be deleted.
            </p>
            <div className="flex justify-end space-x-3 pt-2">
              <button
                className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D] transition-colors"
                onClick={() => setRemoveBookTarget(null)}
              >
                Cancel
              </button>
              <button
                className="px-4 py-2 rounded-lg text-sm font-medium bg-red-600 text-white hover:bg-red-700 transition-colors"
                onClick={() => {
                  removeBookMutation.mutate(removeBookTarget.id)
                  setRemoveBookTarget(null)
                }}
                disabled={removeBookMutation.isPending}
              >
                {removeBookMutation.isPending ? 'Removing...' : 'Remove'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add Book Dialog */}
      {addBookDialogOpen && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="card max-w-md w-full p-0 max-h-[70vh] flex flex-col">
            <div className="p-6 flex-shrink-0">
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">
                Add Book to Series
              </h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Select a book to add to "{series.name}"
              </p>
            </div>
            <div className="flex-1 overflow-y-auto px-6 pb-2">
              {(authorBooks || [])
                .filter(b => !b.series_id)
                .map((book: any) => (
                  <button
                    key={book.id}
                    className="w-full text-left flex items-center gap-3 p-3 rounded-lg hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors"
                    onClick={() => {
                      addBookMutation.mutate({ bookId: book.id })
                      setAddBookDialogOpen(false)
                    }}
                    disabled={addBookMutation.isPending}
                  >
                    <div className="w-10 h-10 flex-shrink-0 bg-gradient-to-br from-gray-600 to-gray-800 rounded overflow-hidden">
                      <img
                        src={book.cover_art_url ? `/api/v1/books/${book.id}/cover-art` : S54.defaultBookCover}
                        alt={book.title}
                        className="w-full h-full object-contain"
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{book.title}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {book.chapter_count || 0} chapters
                      </p>
                    </div>
                  </button>
                ))}
              {(authorBooks || []).filter(b => !b.series_id).length === 0 && (
                <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
                  No unlinked books available
                </p>
              )}
            </div>
            <div className="flex justify-end p-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-lg flex-shrink-0">
              <button
                className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-200 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-[#30363D] transition-colors"
                onClick={() => setAddBookDialogOpen(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default SeriesDetail
