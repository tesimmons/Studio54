import { FiChevronLeft, FiChevronRight, FiChevronsLeft, FiChevronsRight } from 'react-icons/fi'

interface PaginationProps {
  page: number
  totalPages: number
  totalCount?: number
  itemsPerPage: number
  onPageChange: (page: number) => void
  onItemsPerPageChange?: (perPage: number) => void
  perPageOptions?: number[]
}

function Pagination({
  page,
  totalPages,
  totalCount,
  itemsPerPage,
  onPageChange,
  onItemsPerPageChange,
  perPageOptions = [25, 50, 100, 200],
}: PaginationProps) {
  if (totalPages <= 1) return null

  // Build the page number window (up to 5 buttons)
  const pageNumbers: number[] = []
  const windowSize = Math.min(5, totalPages)
  for (let i = 0; i < windowSize; i++) {
    let pageNum: number
    if (totalPages <= 5) {
      pageNum = i + 1
    } else if (page <= 3) {
      pageNum = i + 1
    } else if (page >= totalPages - 2) {
      pageNum = totalPages - 4 + i
    } else {
      pageNum = page - 2 + i
    }
    pageNumbers.push(pageNum)
  }

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-3 card p-3 sm:p-4">
      {/* Left side: info + per-page */}
      <div className="flex items-center gap-4 text-sm text-gray-600 dark:text-gray-400">
        <span>
          Page {page} of {totalPages}
          {totalCount !== undefined && (
            <span className="ml-1 text-gray-400 dark:text-gray-500">
              ({totalCount.toLocaleString()} total)
            </span>
          )}
        </span>
        {onItemsPerPageChange && (
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-500 dark:text-gray-400">Per page:</label>
            <select
              value={itemsPerPage}
              onChange={(e) => onItemsPerPageChange(Number(e.target.value))}
              className="px-2 py-1 rounded border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#161B22] text-sm"
            >
              {perPageOptions.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Right side: navigation buttons */}
      <div className="flex items-center gap-1.5">
        <button
          className="btn btn-secondary btn-sm px-2"
          onClick={() => onPageChange(1)}
          disabled={page === 1}
          title="First page"
        >
          <FiChevronsLeft className="w-4 h-4" />
        </button>
        <button
          className="btn btn-secondary btn-sm px-2"
          onClick={() => onPageChange(page - 1)}
          disabled={page === 1}
          title="Previous page"
        >
          <FiChevronLeft className="w-4 h-4" />
        </button>

        {/* Page number buttons */}
        <div className="hidden sm:flex items-center gap-1">
          {pageNumbers.map((pageNum) => (
            <button
              key={pageNum}
              className={`w-9 h-9 rounded-lg text-sm font-medium transition-colors ${
                page === pageNum
                  ? 'bg-[#FF1493] text-white'
                  : 'bg-gray-100 dark:bg-[#161B22] text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#1C2128]'
              }`}
              onClick={() => onPageChange(pageNum)}
            >
              {pageNum}
            </button>
          ))}
        </div>

        <button
          className="btn btn-secondary btn-sm px-2"
          onClick={() => onPageChange(page + 1)}
          disabled={page === totalPages}
          title="Next page"
        >
          <FiChevronRight className="w-4 h-4" />
        </button>
        <button
          className="btn btn-secondary btn-sm px-2"
          onClick={() => onPageChange(totalPages)}
          disabled={page === totalPages}
          title="Last page"
        >
          <FiChevronsRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

export default Pagination
