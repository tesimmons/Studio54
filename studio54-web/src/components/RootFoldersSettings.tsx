import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { rootFoldersApi, libraryApi } from '../api/client'
import { FiPlus, FiTrash2, FiX, FiFolder, FiHardDrive, FiMusic, FiBookOpen } from 'react-icons/fi'
import type { RootFolder, LibraryType } from '../types'

export default function RootFoldersSettings() {
  const queryClient = useQueryClient()

  const [showAddRootFolderModal, setShowAddRootFolderModal] = useState(false)
  const [rootFolderPath, setRootFolderPath] = useState('/')
  const [browsingPath, setBrowsingPath] = useState('/')
  const [libraryType, setLibraryType] = useState<LibraryType>('music')

  const { data: rootFolders, isLoading: rootFoldersLoading } = useQuery<RootFolder[]>({
    queryKey: ['rootFolders'],
    queryFn: () => rootFoldersApi.list(),
  })

  const { data: browseDirs } = useQuery({
    queryKey: ['browseDirs', browsingPath],
    queryFn: () => libraryApi.browseFolders(browsingPath),
    enabled: showAddRootFolderModal,
  })

  const addRootFolderMutation = useMutation({
    mutationFn: ({ path, library_type }: { path: string; library_type: LibraryType }) =>
      rootFoldersApi.add(path, library_type),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rootFolders'] })
      setShowAddRootFolderModal(false)
      setRootFolderPath('/'); setBrowsingPath('/'); setLibraryType('music')
      toast.success('Root folder added')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to add root folder'),
  })

  const deleteRootFolderMutation = useMutation({
    mutationFn: (id: string) => rootFoldersApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['rootFolders'] })
      toast.success('Root folder removed')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to remove root folder'),
  })

  const getLibraryTypeBadge = (type?: LibraryType) => {
    if (type === 'audiobook') {
      return (
        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300">
          <FiBookOpen className="w-3 h-3 mr-1" />
          Audiobook
        </span>
      )
    }
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
        <FiMusic className="w-3 h-3 mr-1" />
        Music
      </span>
    )
  }

  return (
    <>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Root Folders</h2>
          <button className="btn btn-primary" onClick={() => setShowAddRootFolderModal(true)}>
            <FiPlus className="w-4 h-4 mr-2" />
            Add Root Folder
          </button>
        </div>

        {rootFoldersLoading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
          </div>
        ) : rootFolders && rootFolders.length > 0 ? (
          <div className="space-y-3">
            {rootFolders.map((folder) => (
              <div key={folder.id} className="card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-4 flex-1">
                    <FiFolder className="w-8 h-8 text-[#FF1493] flex-shrink-0" />
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-gray-900 dark:text-white">{folder.path}</h3>
                        {getLibraryTypeBadge(folder.library_type)}
                      </div>
                      <div className="flex items-center space-x-4 mt-1 text-sm text-gray-500 dark:text-gray-400">
                        {folder.free_space_gb != null && (
                          <span className="flex items-center">
                            <FiHardDrive className="w-3 h-3 mr-1" />
                            {folder.free_space_gb} GB free
                          </span>
                        )}
                        <span>{folder.artist_count} {folder.library_type === 'audiobook' ? 'author' : 'artist'}{folder.artist_count !== 1 ? 's' : ''}</span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      if (confirm(`Remove root folder ${folder.path}? This won't delete any files.`)) {
                        deleteRootFolderMutation.mutate(folder.id)
                      }
                    }}
                    className="btn btn-sm btn-danger"
                    disabled={deleteRootFolderMutation.isPending}
                  >
                    <FiTrash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="card p-12 text-center">
            <FiFolder className="w-12 h-12 text-gray-400 mx-auto mb-3" />
            <p className="text-gray-500 dark:text-gray-400">No root folders configured. Add a root folder to organize your library.</p>
          </div>
        )}
      </div>

      {/* Add Root Folder Modal */}
      {showAddRootFolderModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowAddRootFolderModal(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Add Root Folder</h2>
              <button onClick={() => setShowAddRootFolderModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><FiX className="w-6 h-6" /></button>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
              {/* Library Type Selector */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Library Type</label>
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => setLibraryType('music')}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-colors ${
                      libraryType === 'music'
                        ? 'border-[#FF1493] bg-[#FF1493]/10 text-[#FF1493]'
                        : 'border-gray-200 dark:border-[#30363D] text-gray-500 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-500'
                    }`}
                  >
                    <FiMusic className="w-5 h-5" />
                    <span className="font-medium">Music</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setLibraryType('audiobook')}
                    className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-colors ${
                      libraryType === 'audiobook'
                        ? 'border-[#FF1493] bg-[#FF1493]/10 text-[#FF1493]'
                        : 'border-gray-200 dark:border-[#30363D] text-gray-500 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-500'
                    }`}
                  >
                    <FiBookOpen className="w-5 h-5" />
                    <span className="font-medium">Audiobook</span>
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Selected Path</label>
                <input type="text" className="input w-full" value={rootFolderPath} onChange={(e) => setRootFolderPath(e.target.value)} />
              </div>
              <div className="border border-gray-200 dark:border-[#30363D] rounded-lg overflow-hidden">
                <div className="bg-gray-50 dark:bg-[#0D1117] px-3 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 flex items-center justify-between">
                  <span>{browsingPath}</span>
                  {browseDirs?.parent_path && (
                    <button className="text-[#FF1493] hover:underline text-sm" onClick={() => setBrowsingPath(browseDirs.parent_path!)}>
                      Up
                    </button>
                  )}
                </div>
                <div className="max-h-60 overflow-y-auto">
                  {browseDirs?.directories.map((dir) => (
                    <div
                      key={dir.path}
                      className={`flex items-center px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-[#1C2128] border-t border-gray-100 dark:border-[#30363D]/50 ${
                        rootFolderPath === dir.path ? 'bg-[#FF1493]/5 dark:bg-[#FF1493]/10' : ''
                      }`}
                      onClick={() => { setRootFolderPath(dir.path); setBrowsingPath(dir.path) }}
                    >
                      <FiFolder className="w-4 h-4 text-gray-400 mr-2 flex-shrink-0" />
                      <span className="text-sm text-gray-700 dark:text-gray-300 truncate">{dir.name}</span>
                    </div>
                  ))}
                  {browseDirs && browseDirs.directories.length === 0 && (
                    <div className="px-3 py-4 text-sm text-gray-500 dark:text-gray-400 text-center">No subdirectories</div>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center justify-end p-6 border-t border-gray-200 dark:border-[#30363D] space-x-3">
              <button onClick={() => setShowAddRootFolderModal(false)} className="btn btn-secondary">Cancel</button>
              <button
                onClick={() => addRootFolderMutation.mutate({ path: rootFolderPath, library_type: libraryType })}
                className="btn btn-primary"
                disabled={addRootFolderMutation.isPending || !rootFolderPath}
              >
                {addRootFolderMutation.isPending ? 'Adding...' : 'Add Root Folder'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
