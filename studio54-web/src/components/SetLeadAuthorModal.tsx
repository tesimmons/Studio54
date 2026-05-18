/**
 * SetLeadAuthorModal
 *
 * Shown when a book has co-authors. Lets the user pick which name becomes
 * the sole lead author. The current author and all co-authors are listed as
 * radio options. On confirm, the chosen name is promoted:
 *  - the DB author is updated (find-or-create if it was a co-author)
 *  - the old author is pushed into co-authors
 *  - a rewrite_book_file_tags job is queued
 */
import { useState } from 'react'
import { FiX, FiLoader, FiStar } from 'react-icons/fi'

interface Props {
  bookTitle: string
  currentAuthorName: string
  coAuthors: string[]
  onClose: () => void
  onConfirm: (leadName: string) => void
  isPending: boolean
}

export default function SetLeadAuthorModal({
  bookTitle,
  currentAuthorName,
  coAuthors,
  onClose,
  onConfirm,
  isPending,
}: Props) {
  const [selected, setSelected] = useState(currentAuthorName)

  // Full list: current author first, then co-authors
  const allNames = [currentAuthorName, ...coAuthors.filter((n) => n !== currentAuthorName)]

  const handleConfirm = () => {
    if (selected) onConfirm(selected)
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl w-full max-w-sm mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between px-6 pt-6 pb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <FiStar className="w-5 h-5 text-[#FF1493]" />
              Set Lead Author
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 truncate max-w-xs" title={bookTitle}>
              {bookTitle}
            </p>
          </div>
          <button onClick={onClose} className="ml-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 shrink-0">
            <FiX className="w-5 h-5" />
          </button>
        </div>

        {/* Author options */}
        <div className="px-6 pb-4 space-y-2">
          <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
            The selected name becomes the primary author. All others remain as co-authors.
            Audio file tags will be updated automatically.
          </p>

          {allNames.map((name) => {
            const isCurrent = name === currentAuthorName
            const isSelected = name === selected
            return (
              <label
                key={name}
                className={`flex items-center gap-3 px-4 py-3 rounded-lg cursor-pointer border transition-colors ${
                  isSelected
                    ? 'bg-[#FF1493]/10 border-[#FF1493]/40'
                    : 'border-transparent hover:bg-gray-100 dark:hover:bg-[#1C2128]'
                }`}
              >
                <input
                  type="radio"
                  name="lead-author"
                  value={name}
                  checked={isSelected}
                  onChange={() => setSelected(name)}
                  className="accent-[#FF1493]"
                />
                <span className="flex-1 text-sm font-medium text-gray-900 dark:text-white">{name}</span>
                {isCurrent && !isSelected && (
                  <span className="text-[10px] text-gray-400 dark:text-gray-500 shrink-0">current</span>
                )}
                {isSelected && (
                  <span className="text-[10px] font-semibold text-[#FF1493] shrink-0">lead</span>
                )}
              </label>
            )
          })}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-3 px-6 py-4 bg-gray-50 dark:bg-[#0D1117]/50 rounded-b-xl border-t border-gray-100 dark:border-[#30363D]">
          <button className="btn btn-secondary" onClick={onClose} disabled={isPending}>
            Cancel
          </button>
          <button
            className="btn btn-primary flex items-center gap-2"
            onClick={handleConfirm}
            disabled={!selected || isPending}
          >
            {isPending ? (
              <>
                <FiLoader className="w-4 h-4 animate-spin" />
                Applying…
              </>
            ) : (
              <>
                <FiStar className="w-4 h-4" />
                Set as Lead
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
