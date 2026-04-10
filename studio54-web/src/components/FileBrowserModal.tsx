import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { authFetch } from '../api/client'
import { FiX, FiFolder, FiChevronRight, FiHome } from 'react-icons/fi'

interface DirectoryEntry {
  name: string
  path: string
  is_directory: boolean
  size: number | null
  modified: number | null
}

interface DirectoryListing {
  current_path: string
  parent_path: string | null
  entries: DirectoryEntry[]
}

interface FileBrowserModalProps {
  isOpen: boolean
  onClose: () => void
  onSelect: (path: string) => void
  initialPath?: string
}

function FileBrowserModal({ isOpen, onClose, onSelect, initialPath = '/' }: FileBrowserModalProps) {
  const [currentPath, setCurrentPath] = useState(initialPath)

  // Fetch directory listing
  const { data, isLoading, error } = useQuery({
    queryKey: ['filesystem-browse', currentPath],
    queryFn: async (): Promise<DirectoryListing> => {
      const response = await authFetch(`/api/v1/filesystem/browse?path=${encodeURIComponent(currentPath)}`)
      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to browse directory')
      }
      return response.json()
    },
    enabled: isOpen,
  })

  // Update current path when initial path changes
  useEffect(() => {
    if (initialPath && isOpen) {
      setCurrentPath(initialPath)
    }
  }, [initialPath, isOpen])

  if (!isOpen) return null

  const handleSelectDirectory = () => {
    onSelect(currentPath)
    onClose()
  }

  const handleNavigate = (path: string) => {
    setCurrentPath(path)
  }

  // Create breadcrumb from current path
  const getBreadcrumbs = () => {
    const parts = currentPath.split('/').filter(Boolean)
    const breadcrumbs: Array<{ name: string; path: string }> = [
      { name: 'Root', path: '/' }
    ]

    let accumulatedPath = ''
    parts.forEach((part) => {
      accumulatedPath += `/${part}`
      breadcrumbs.push({ name: part, path: accumulatedPath })
    })

    return breadcrumbs
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-[#30363D]">
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
              Browse Directories
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Select a folder for this album
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
            title="Close"
          >
            <FiX className="w-6 h-6" />
          </button>
        </div>

        {/* Breadcrumb Navigation */}
        <div className="px-4 py-3 bg-gray-50 dark:bg-[#0D1117] border-b border-gray-200 dark:border-[#30363D]">
          <div className="flex items-center space-x-2 text-sm overflow-x-auto">
            {getBreadcrumbs().map((crumb, index) => (
              <div key={crumb.path} className="flex items-center space-x-2">
                {index > 0 && <FiChevronRight className="w-4 h-4 text-gray-400" />}
                <button
                  onClick={() => handleNavigate(crumb.path)}
                  className="text-[#FF1493] dark:text-[#ff4da6] hover:underline whitespace-nowrap"
                >
                  {index === 0 ? <FiHome className="w-4 h-4" title="Go to root directory" /> : crumb.name}
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Directory Listing */}
        <div className="flex-1 overflow-y-auto p-4">
          {isLoading && (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]"></div>
            </div>
          )}

          {error && (
            <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
              <p className="text-red-800 dark:text-red-200 text-sm">
                {error instanceof Error ? error.message : 'Failed to load directory'}
              </p>
            </div>
          )}

          {data && !isLoading && (
            <div className="space-y-1">
              {/* Parent directory link */}
              {data.parent_path && (
                <button
                  onClick={() => handleNavigate(data.parent_path!)}
                  className="w-full flex items-center space-x-3 p-3 rounded-lg hover:bg-gray-100 dark:hover:bg-[#1C2128] text-left"
                  title="Go to parent folder"
                >
                  <FiFolder className="w-5 h-5 text-gray-400" />
                  <span className="text-gray-600 dark:text-gray-300">..</span>
                </button>
              )}

              {/* Directory entries */}
              {data.entries.length === 0 && !data.parent_path && (
                <p className="text-gray-500 dark:text-gray-400 text-center py-8">
                  No directories found
                </p>
              )}

              {data.entries.map((entry) => (
                <button
                  key={entry.path}
                  onClick={() => handleNavigate(entry.path)}
                  className="w-full flex items-center space-x-3 p-3 rounded-lg hover:bg-gray-100 dark:hover:bg-[#1C2128] text-left"
                >
                  <FiFolder className="w-5 h-5 text-[#FF1493] dark:text-[#ff4da6]" />
                  <span className="text-gray-900 dark:text-white">{entry.name}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#0D1117]">
          <div className="flex-1 text-sm text-gray-600 dark:text-gray-400">
            <span className="font-medium">Selected:</span>{' '}
            <span className="font-mono">{currentPath}</span>
          </div>
          <div className="flex items-center space-x-3">
            <button
              onClick={onClose}
              className="btn btn-secondary"
              title="Cancel and close"
            >
              Cancel
            </button>
            <button
              onClick={handleSelectDirectory}
              className="btn btn-primary"
              title="Use this folder for the album"
            >
              Select This Folder
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default FileBrowserModal
