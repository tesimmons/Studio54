import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FiSearch, FiX, FiUserPlus, FiLoader, FiUsers } from 'react-icons/fi'
import { authorsApi } from '../api/client'
import type { Author } from '../types'

interface Props {
  bookCount: number
  onClose: () => void
  onConfirm: (opts: { authorId?: string; newAuthorName?: string; coAuthorName?: string }) => void
  isPending: boolean
}

export default function MoveToAuthorModal({ bookCount, onClose, onConfirm, isPending }: Props) {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selected, setSelected] = useState<Author | null>(null)
  const [createNew, setCreateNew] = useState(false)
  const [coAuthorName, setCoAuthorName] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query.trim()), 300)
    return () => clearTimeout(t)
  }, [query])

  // Reset selection when query changes
  useEffect(() => {
    setSelected(null)
    setCreateNew(false)
  }, [query])

  const { data, isFetching } = useQuery({
    queryKey: ['move-author-search', debouncedQuery],
    queryFn: () =>
      authorsApi.list({ search_query: debouncedQuery, limit: 8 }),
    enabled: debouncedQuery.length > 0,
    staleTime: 10_000,
  })

  const results: Author[] = data?.authors ?? []
  const noResults = debouncedQuery.length > 0 && !isFetching && results.length === 0

  // Focus input on open
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const handleConfirm = () => {
    const co = coAuthorName.trim() || undefined
    if (createNew && query.trim()) {
      onConfirm({ newAuthorName: query.trim(), coAuthorName: co })
    } else if (selected) {
      onConfirm({ authorId: selected.id, coAuthorName: co })
    }
  }

  const canConfirm = (selected !== null || (createNew && query.trim().length > 0)) && !isPending

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl w-full max-w-md mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Move to Author</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
              Moving {bookCount} book{bookCount !== 1 ? 's' : ''}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <FiX className="w-5 h-5" />
          </button>
        </div>

        {/* Primary author search */}
        <div className="px-6 pb-3">
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">Lead Author</label>
          <div className="relative">
            <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search existing authors…"
              className="input w-full pl-9 pr-4"
            />
            {isFetching && (
              <FiLoader className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 animate-spin" />
            )}
          </div>
        </div>

        {/* Results */}
        <div className="px-6 pb-4 space-y-1 max-h-52 overflow-y-auto">
          {results.map((author) => (
            <button
              key={author.id}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                selected?.id === author.id
                  ? 'bg-[#FF1493]/10 border border-[#FF1493]/40'
                  : 'hover:bg-gray-100 dark:hover:bg-[#1C2128] border border-transparent'
              }`}
              onClick={() => { setSelected(author); setCreateNew(false) }}
            >
              {author.image_url ? (
                <img
                  src={`/api/v1/authors/${author.id}/cover-art`}
                  alt={author.name}
                  className="w-8 h-8 rounded-full object-cover shrink-0"
                  onError={(e) => { e.currentTarget.style.display = 'none' }}
                />
              ) : (
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#FF1493] to-[#FF8C00] shrink-0" />
              )}
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{author.name}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {author.book_count ?? 0} book{(author.book_count ?? 0) !== 1 ? 's' : ''}
                </p>
              </div>
            </button>
          ))}

          {/* Create new author option — shown when no results */}
          {noResults && query.trim() && (
            <button
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${
                createNew
                  ? 'bg-[#FF1493]/10 border border-[#FF1493]/40'
                  : 'hover:bg-gray-100 dark:hover:bg-[#1C2128] border border-transparent'
              }`}
              onClick={() => { setCreateNew(true); setSelected(null) }}
            >
              <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-[#30363D] flex items-center justify-center shrink-0">
                <FiUserPlus className="w-4 h-4 text-gray-500 dark:text-gray-400" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white">
                  Create "<span className="text-[#FF1493]">{query.trim()}</span>"
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">New author — metadata fetch will be queued</p>
              </div>
            </button>
          )}

          {/* Also offer create when results exist but user wants something different */}
          {results.length > 0 && query.trim() && (
            <button
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors border-t border-gray-100 dark:border-gray-800 mt-1 pt-2 ${
                createNew
                  ? 'bg-[#FF1493]/10 border border-[#FF1493]/40'
                  : 'hover:bg-gray-100 dark:hover:bg-[#1C2128] border-transparent'
              }`}
              onClick={() => { setCreateNew(true); setSelected(null) }}
            >
              <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-[#30363D] flex items-center justify-center shrink-0">
                <FiUserPlus className="w-4 h-4 text-gray-500 dark:text-gray-400" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white">
                  Create "<span className="text-[#FF1493]">{query.trim()}</span>"
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">New author — metadata fetch will be queued</p>
              </div>
            </button>
          )}
        </div>

        {/* Secondary / co-author */}
        <div className="px-6 pb-4 border-t border-gray-100 dark:border-[#30363D] pt-4">
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
            Secondary Author <span className="text-gray-400">(optional)</span>
          </label>
          <div className="relative">
            <FiUsers className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
            <input
              type="text"
              value={coAuthorName}
              onChange={(e) => setCoAuthorName(e.target.value)}
              placeholder="Add co-author to moved books…"
              className="input w-full pl-9 pr-4"
            />
          </div>
          {coAuthorName.trim() && (
            <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
              "<span className="font-medium text-gray-700 dark:text-gray-300">{coAuthorName.trim()}</span>" will be added to co_authors on each moved book and saved for future searches.
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-6 py-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-xl border-t border-gray-100 dark:border-[#30363D]">
          <button className="btn btn-secondary" onClick={onClose} disabled={isPending}>
            Cancel
          </button>
          <button
            className="btn btn-primary flex items-center gap-2"
            onClick={handleConfirm}
            disabled={!canConfirm}
          >
            {isPending ? (
              <>
                <FiLoader className="w-4 h-4 animate-spin" />
                Moving…
              </>
            ) : (
              <>
                <FiUserPlus className="w-4 h-4" />
                Move Books
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
