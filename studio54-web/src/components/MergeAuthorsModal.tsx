/**
 * MergeAuthorsModal
 *
 * Lets the user pick which of the selected authors is the "lead" to keep,
 * or search for a different existing author entirely.
 * All other selected authors' books are moved to the lead, then those
 * authors are deleted.
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FiSearch, FiX, FiLoader, FiCheck, FiUsers } from 'react-icons/fi'
import { authorsApi } from '../api/client'
import type { Author } from '../types'

interface Props {
  /** The authors the user has already selected in bulk mode */
  selectedAuthors: Author[]
  onClose: () => void
  onConfirm: (sourceIds: string[], targetId: string) => void
  isPending: boolean
}

export default function MergeAuthorsModal({ selectedAuthors, onClose, onConfirm, isPending }: Props) {
  const [targetId, setTargetId] = useState<string | null>(
    selectedAuthors.length > 0 ? selectedAuthors[0].id : null
  )
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(searchQuery.trim()), 300)
    return () => clearTimeout(t)
  }, [searchQuery])

  // Search for authors outside the current selection
  const { data: searchData, isFetching } = useQuery({
    queryKey: ['merge-author-search', debouncedQuery],
    queryFn: () => authorsApi.list({ search_query: debouncedQuery, limit: 8 }),
    enabled: debouncedQuery.length > 0,
    staleTime: 10_000,
  })

  const searchResults: Author[] = (searchData?.authors ?? []).filter(
    (a) => !selectedAuthors.some((s) => s.id === a.id)
  )

  // Extra target (from search) if it's not in the selection
  const [extraTarget, setExtraTarget] = useState<Author | null>(null)

  const selectedTarget =
    extraTarget ??
    selectedAuthors.find((a) => a.id === targetId) ??
    null

  const sourceIds = selectedAuthors
    .filter((a) => a.id !== selectedTarget?.id)
    .map((a) => a.id)

  // If an extra (searched) author is chosen as target, all selected authors become sources
  const sourceAuthors = extraTarget
    ? selectedAuthors
    : selectedAuthors.filter((a) => a.id !== targetId)

  const canConfirm =
    selectedTarget !== null &&
    sourceIds.length > 0 &&
    !isPending

  const handleConfirm = () => {
    if (!selectedTarget) return
    const sources = extraTarget
      ? selectedAuthors.map((a) => a.id)
      : selectedAuthors.filter((a) => a.id !== targetId).map((a) => a.id)
    onConfirm(sources, selectedTarget.id)
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl w-full max-w-lg mx-4 flex flex-col max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-6 pb-4 shrink-0">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <FiUsers className="w-5 h-5 text-[#FF1493]" />
              Merge Authors
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Choose the <span className="font-semibold text-gray-700 dark:text-gray-300">lead author</span> to keep.
              All books from the others will be moved to the lead, and the other entries will be removed.
            </p>
          </div>
          <button onClick={onClose} className="ml-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 shrink-0">
            <FiX className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 overflow-y-auto flex-1 space-y-5 pb-4">
          {/* Step 1: pick the lead from the selection */}
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Selected authors — pick the lead
            </p>
            <div className="space-y-1">
              {selectedAuthors.map((author) => {
                const isLead = !extraTarget && targetId === author.id
                return (
                  <button
                    key={author.id}
                    className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors border ${
                      isLead
                        ? 'bg-[#FF1493]/10 border-[#FF1493]/40'
                        : 'hover:bg-gray-100 dark:hover:bg-[#1C2128] border-transparent'
                    }`}
                    onClick={() => { setTargetId(author.id); setExtraTarget(null) }}
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
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{author.name}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {author.book_count ?? 0} book{(author.book_count ?? 0) !== 1 ? 's' : ''}
                      </p>
                    </div>
                    {isLead && (
                      <span className="shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[#FF1493]/20 text-[#FF1493]">
                        Lead
                      </span>
                    )}
                    {!isLead && (
                      <span className="shrink-0 text-[11px] text-gray-400 dark:text-gray-500">
                        will merge in
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Step 2: optionally use a different author as lead */}
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Or merge all into a different existing author
            </p>
            <div className="relative">
              <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
              <input
                ref={inputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search other authors…"
                className="input w-full pl-9 pr-4"
              />
              {isFetching && (
                <FiLoader className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 animate-spin" />
              )}
            </div>

            {searchResults.length > 0 && (
              <div className="mt-1 space-y-1">
                {searchResults.map((author) => {
                  const isLead = extraTarget?.id === author.id
                  return (
                    <button
                      key={author.id}
                      className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors border ${
                        isLead
                          ? 'bg-[#FF1493]/10 border-[#FF1493]/40'
                          : 'hover:bg-gray-100 dark:hover:bg-[#1C2128] border-transparent'
                      }`}
                      onClick={() => { setExtraTarget(author); setTargetId(null) }}
                    >
                      {author.image_url ? (
                        <img
                          src={`/api/v1/authors/${author.id}/cover-art`}
                          alt={author.name}
                          className="w-8 h-8 rounded-full object-cover shrink-0"
                          onError={(e) => { e.currentTarget.style.display = 'none' }}
                        />
                      ) : (
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-indigo-600 shrink-0" />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{author.name}</p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {author.book_count ?? 0} book{(author.book_count ?? 0) !== 1 ? 's' : ''}
                        </p>
                      </div>
                      {isLead && (
                        <span className="shrink-0 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[#FF1493]/20 text-[#FF1493]">
                          Lead
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Summary */}
          {selectedTarget && sourceAuthors.length > 0 && (
            <div className="rounded-lg bg-gray-50 dark:bg-[#0D1117] border border-gray-200 dark:border-[#30363D] p-3 text-sm space-y-1">
              <p className="font-medium text-gray-900 dark:text-white">Summary</p>
              <p className="text-gray-600 dark:text-gray-400">
                Books from{' '}
                <span className="font-medium text-gray-800 dark:text-gray-200">
                  {sourceAuthors.map((a) => a.name).join(', ')}
                </span>{' '}
                will be moved to{' '}
                <span className="font-medium text-[#FF1493]">{selectedTarget.name}</span>.
              </p>
              <p className="text-gray-500 dark:text-gray-500 text-xs">
                {sourceAuthors.length} author{sourceAuthors.length !== 1 ? 's' : ''} will be removed after the merge.
                Audio file tags will be updated automatically.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-6 py-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-xl border-t border-gray-100 dark:border-[#30363D] shrink-0">
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
                Merging…
              </>
            ) : (
              <>
                <FiCheck className="w-4 h-4" />
                Merge {sourceAuthors.length > 0 ? `${sourceAuthors.length + 1} Authors` : 'Authors'}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
