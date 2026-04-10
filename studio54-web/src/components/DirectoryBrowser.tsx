/**
 * Directory Browser Modal
 * Allows users to browse and select filesystem directories
 */

import { useState, useEffect } from 'react'
import { authFetch } from '../api/client'
import { FiFolder, FiArrowUp, FiX } from 'react-icons/fi'
import toast from 'react-hot-toast'

interface DirectoryEntry {
  name: string
  path: string
  is_directory: boolean
  size?: number
  modified?: number
}

interface DirectoryListing {
  current_path: string
  parent_path: string | null
  entries: DirectoryEntry[]
}

interface DirectoryBrowserProps {
  isOpen: boolean
  onClose: () => void
  onSelect: (path: string) => void
  initialPath?: string
  title?: string
}

export default function DirectoryBrowser({
  isOpen,
  onClose,
  onSelect,
  initialPath = '/music',
  title = 'Select Directory'
}: DirectoryBrowserProps) {
  const [currentPath, setCurrentPath] = useState(initialPath)
  const [listing, setListing] = useState<DirectoryListing | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Browse directory
  const browsePath = async (path: string) => {
    setLoading(true)
    setError(null)

    try {
      const response = await authFetch(`/api/v1/filesystem/browse?path=${encodeURIComponent(path)}`)

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to browse directory')
      }

      const data: DirectoryListing = await response.json()
      setListing(data)
      setCurrentPath(data.current_path)
    } catch (err: any) {
      const errorMessage = err.message || 'Failed to load directory'
      setError(errorMessage)
      toast.error(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  // Load initial directory when modal opens
  useEffect(() => {
    if (isOpen) {
      browsePath(initialPath)
    }
  }, [isOpen, initialPath])

  // Handle directory click
  const handleDirectoryClick = (path: string) => {
    browsePath(path)
  }

  // Handle parent directory navigation
  const handleGoUp = () => {
    if (listing?.parent_path) {
      browsePath(listing.parent_path)
    }
  }

  // Handle select button
  const handleSelect = () => {
    onSelect(currentPath)
    onClose()
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
      <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-[#30363D]">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{title}</h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            <FiX size={24} />
          </button>
        </div>

        {/* Current Path */}
        <div className="p-4 bg-gray-50 dark:bg-[#0D1117] border-b border-gray-200 dark:border-[#30363D]">
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Current Path
              </label>
              <input
                type="text"
                value={currentPath}
                onChange={(e) => setCurrentPath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    browsePath(currentPath)
                  }
                }}
                className="input w-full font-mono text-sm"
                placeholder="/path/to/directory"
              />
            </div>
            <button
              onClick={() => browsePath(currentPath)}
              disabled={loading}
              className="btn btn-secondary ml-2 mt-6"
            >
              Go
            </button>
          </div>
        </div>

        {/* Directory Listing */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading && (
            <div className="text-center py-8 text-gray-500 dark:text-gray-400">
              Loading...
            </div>
          )}

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded p-4 text-red-700 dark:text-red-400">
              {error}
            </div>
          )}

          {!loading && !error && listing && (
            <div className="space-y-1">
              {/* Parent Directory */}
              {listing.parent_path && (
                <button
                  onClick={handleGoUp}
                  className="w-full flex items-center space-x-3 p-3 rounded hover:bg-gray-100 dark:hover:bg-[#1C2128] text-left"
                >
                  <FiArrowUp className="text-gray-500 dark:text-gray-400" size={20} />
                  <span className="text-gray-700 dark:text-gray-300">..</span>
                </button>
              )}

              {/* Directories */}
              {listing.entries.length === 0 && !listing.parent_path && (
                <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                  No directories found
                </div>
              )}

              {listing.entries.map((entry) => (
                <button
                  key={entry.path}
                  onClick={() => handleDirectoryClick(entry.path)}
                  className="w-full flex items-center space-x-3 p-3 rounded hover:bg-gray-100 dark:hover:bg-[#1C2128] text-left"
                >
                  <FiFolder className="text-blue-500 dark:text-blue-400" size={20} />
                  <div className="flex-1">
                    <div className="text-gray-900 dark:text-white">{entry.name}</div>
                    {entry.modified && (
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        Modified: {new Date(entry.modified * 1000).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-gray-200 dark:border-[#30363D]">
          <div className="text-sm text-gray-600 dark:text-gray-400">
            {listing && `${listing.entries.length} ${listing.entries.length === 1 ? 'directory' : 'directories'}`}
          </div>
          <div className="flex space-x-2">
            <button onClick={onClose} className="btn btn-secondary">
              Cancel
            </button>
            <button onClick={handleSelect} className="btn btn-primary" disabled={loading}>
              Select "{currentPath}"
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
