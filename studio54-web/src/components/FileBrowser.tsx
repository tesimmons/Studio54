import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { libraryApi } from '../api/client'
import { FiFolder, FiChevronRight, FiHome, FiArrowUp } from 'react-icons/fi'

interface FileBrowserProps {
  onSelect: (path: string) => void
  initialPath?: string
}

function FileBrowser({ onSelect, initialPath = '/' }: FileBrowserProps) {
  const [currentPath, setCurrentPath] = useState(initialPath)

  // Fetch directories for current path
  const { data, isLoading, error } = useQuery({
    queryKey: ['browse-folders', currentPath],
    queryFn: () => libraryApi.browseFolders(currentPath),
    retry: 1,
  })

  useEffect(() => {
    if (initialPath) {
      setCurrentPath(initialPath)
    }
  }, [initialPath])

  const handleNavigate = (path: string) => {
    setCurrentPath(path)
  }

  const handleSelect = (path: string) => {
    onSelect(path)
  }

  const handleGoUp = () => {
    if (data?.parent_path) {
      setCurrentPath(data.parent_path)
    }
  }

  const handleGoHome = () => {
    setCurrentPath('/')
  }

  // Split current path into breadcrumb segments
  const pathSegments = currentPath.split('/').filter(Boolean)

  return (
    <div className="border border-gray-300 dark:border-[#30363D] rounded-lg bg-white dark:bg-[#161B22]">
      {/* Header with breadcrumbs */}
      <div className="border-b border-gray-300 dark:border-[#30363D] p-3 bg-gray-50 dark:bg-[#0D1117]">
        <div className="flex items-center space-x-2 text-sm">
          {/* Home button */}
          <button
            onClick={handleGoHome}
            className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-[#30363D] transition-colors"
            title="Go to root"
          >
            <FiHome className="w-4 h-4 text-gray-600 dark:text-gray-300" />
          </button>

          {/* Up button */}
          {data?.parent_path && (
            <button
              onClick={handleGoUp}
              className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-[#30363D] transition-colors"
              title="Go up one level"
            >
              <FiArrowUp className="w-4 h-4 text-gray-600 dark:text-gray-300" />
            </button>
          )}

          {/* Breadcrumbs */}
          <div className="flex items-center flex-1 overflow-x-auto">
            <span className="text-gray-600 dark:text-gray-300">/</span>
            {pathSegments.map((segment, index) => {
              const segmentPath = '/' + pathSegments.slice(0, index + 1).join('/')
              return (
                <div key={segmentPath} className="flex items-center">
                  <button
                    onClick={() => handleNavigate(segmentPath)}
                    className="px-1 hover:text-[#FF1493] dark:hover:text-[#ff4da6] text-gray-700 dark:text-gray-200"
                  >
                    {segment}
                  </button>
                  {index < pathSegments.length - 1 && (
                    <FiChevronRight className="w-4 h-4 text-gray-400 mx-1" />
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Current path display */}
        <div className="mt-2 text-xs text-gray-500 dark:text-gray-400 font-mono truncate">
          {data?.current_path || currentPath}
        </div>
      </div>

      {/* Directory listing */}
      <div className="max-h-96 overflow-y-auto">
        {isLoading && (
          <div className="p-8 text-center text-gray-500 dark:text-gray-400">
            Loading directories...
          </div>
        )}

        {error && (
          <div className="p-8 text-center text-red-600 dark:text-red-400">
            {error instanceof Error ? error.message : 'Failed to load directories'}
          </div>
        )}

        {data && data.directories.length === 0 && (
          <div className="p-8 text-center text-gray-500 dark:text-gray-400">
            No subdirectories found
          </div>
        )}

        {data && data.directories.length > 0 && (
          <div className="divide-y divide-gray-200 dark:divide-[#30363D]">
            {data.directories.map((dir) => (
              <div
                key={dir.path}
                className="flex items-center justify-between p-3 hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors"
              >
                <div className="flex items-center flex-1 min-w-0">
                  <FiFolder className={`w-5 h-5 mr-3 flex-shrink-0 ${
                    dir.is_readable
                      ? 'text-yellow-500'
                      : 'text-gray-400 dark:text-gray-600'
                  }`} />
                  <button
                    onClick={() => handleNavigate(dir.path)}
                    disabled={!dir.is_readable}
                    className={`text-left truncate ${
                      dir.is_readable
                        ? 'text-gray-900 dark:text-gray-100 hover:text-[#FF1493] dark:hover:text-[#ff4da6]'
                        : 'text-gray-400 dark:text-gray-600 cursor-not-allowed'
                    }`}
                    title={dir.is_readable ? `Navigate to ${dir.name}` : 'Permission denied'}
                  >
                    {dir.name}
                  </button>
                </div>

                <button
                  onClick={() => handleSelect(dir.path)}
                  disabled={!dir.is_readable}
                  className={`ml-3 px-3 py-1 text-sm rounded transition-colors ${
                    dir.is_readable
                      ? 'bg-[#FF1493] text-white hover:bg-[#d10f7a]'
                      : 'bg-gray-300 dark:bg-gray-600 text-gray-500 dark:text-gray-400 cursor-not-allowed'
                  }`}
                >
                  Select
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer with select current directory button */}
      <div className="border-t border-gray-300 dark:border-[#30363D] p-3 bg-gray-50 dark:bg-[#0D1117]">
        <button
          onClick={() => handleSelect(data?.current_path || currentPath)}
          className="w-full px-4 py-2 bg-[#FF1493] text-white rounded-lg hover:bg-[#d10f7a] transition-colors font-medium"
        >
          Select Current Directory
        </button>
      </div>
    </div>
  )
}

export default FileBrowser
