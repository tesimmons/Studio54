import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FiList, FiPlus, FiCheck } from 'react-icons/fi'
import { playlistsApi } from '../api/client'
import toast from 'react-hot-toast'

interface AddToPlaylistDropdownProps {
  trackId: string
}

function AddToPlaylistDropdown({ trackId }: AddToPlaylistDropdownProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const { data: playlists } = useQuery({
    queryKey: ['playlists-list'],
    queryFn: async () => {
      const result = await playlistsApi.list(100, 0)
      return result.items
    },
    enabled: isOpen,
  })

  const addTrackMutation = useMutation({
    mutationFn: async (playlistId: string) => {
      return playlistsApi.addTrack(playlistId, trackId)
    },
    onSuccess: (data) => {
      toast.success(data.message || 'Added to playlist')
      queryClient.invalidateQueries({ queryKey: ['playlists-list'] })
      setIsOpen(false)
    },
    onError: (error: any) => {
      const msg = error?.response?.data?.detail || error?.message || 'Failed to add to playlist'
      toast.error(msg)
    },
  })

  const createAndAddMutation = useMutation({
    mutationFn: async (name: string) => {
      const playlist = await playlistsApi.create({ name })
      await playlistsApi.addTrack(playlist.id, trackId)
      return playlist
    },
    onSuccess: (playlist) => {
      toast.success(`Created "${playlist.name}" and added track`)
      queryClient.invalidateQueries({ queryKey: ['playlists-list'] })
      setCreating(false)
      setNewName('')
      setIsOpen(false)
    },
    onError: (error: any) => {
      const msg = error?.response?.data?.detail || error?.message || 'Failed to create playlist'
      toast.error(msg)
    },
  })

  // Close on click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
        setCreating(false)
        setNewName('')
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  // Auto-focus input when creating
  useEffect(() => {
    if (creating && inputRef.current) {
      inputRef.current.focus()
    }
  }, [creating])

  const handleCreateSubmit = () => {
    const trimmed = newName.trim()
    if (!trimmed) return
    createAndAddMutation.mutate(trimmed)
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={(e) => { e.stopPropagation(); setIsOpen(!isOpen) }}
        className="text-gray-500 dark:text-gray-400 hover:text-[#FF1493] dark:hover:text-[#ff4da6] transition-colors"
        title="Add to playlist"
      >
        <FiList className="w-4 h-4" />
      </button>

      {isOpen && (
        <div className="absolute right-0 bottom-full mb-1 w-48 bg-white dark:bg-[#161B22] border border-gray-200 dark:border-[#30363D] rounded-lg shadow-lg z-50 py-1 max-h-48 overflow-y-auto">
          {/* New Playlist option */}
          {creating ? (
            <div className="px-2 py-1.5 flex items-center space-x-1" onClick={(e) => e.stopPropagation()}>
              <input
                ref={inputRef}
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreateSubmit()
                  if (e.key === 'Escape') { setCreating(false); setNewName('') }
                }}
                placeholder="Playlist name..."
                disabled={createAndAddMutation.isPending}
                className="flex-1 min-w-0 text-sm px-1.5 py-1 rounded border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:border-[#FF1493]"
              />
              <button
                onClick={(e) => { e.stopPropagation(); handleCreateSubmit() }}
                disabled={!newName.trim() || createAndAddMutation.isPending}
                className="p-1 text-[#FF1493] hover:text-[#d10f7a] disabled:opacity-40 disabled:cursor-not-allowed"
                title="Create playlist"
              >
                <FiCheck className="w-4 h-4" />
              </button>
            </div>
          ) : (
            <button
              onClick={(e) => { e.stopPropagation(); setCreating(true) }}
              className="w-full text-left px-3 py-1.5 text-sm text-[#FF1493] hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors flex items-center font-medium"
            >
              <FiPlus className="w-3 h-3 mr-2 flex-shrink-0" />
              New Playlist...
            </button>
          )}

          {/* Divider */}
          {playlists && playlists.length > 0 && (
            <div className="border-t border-gray-200 dark:border-[#30363D] my-1" />
          )}

          {/* Existing playlists */}
          {!playlists || playlists.length === 0 ? (
            !creating && (
              <div className="px-3 py-2 text-xs text-gray-500 dark:text-gray-400">
                No playlists yet
              </div>
            )
          ) : (
            playlists.map((pl) => (
              <button
                key={pl.id}
                onClick={(e) => { e.stopPropagation(); addTrackMutation.mutate(pl.id) }}
                disabled={addTrackMutation.isPending}
                className="w-full text-left px-3 py-1.5 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors flex items-center"
              >
                <FiPlus className="w-3 h-3 mr-2 flex-shrink-0" />
                <span className="truncate">{pl.name}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

export default AddToPlaylistDropdown
