import { useState, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { playlistsApi } from '../api/client'
import AudioPlayer from '../components/AudioPlayer'
import {
  FiMusic,
  FiPlus,
  FiX,
  FiEdit2,
  FiTrash2,
  FiPlay,
  FiRefreshCw,
  FiList,
  FiGlobe,
  FiLock,
  FiImage,
  FiMenu,
} from 'react-icons/fi'
import type { Playlist, PlaylistDetail, PlaylistTrack } from '../types'
import toast, { Toaster } from 'react-hot-toast'
import { useAuth } from '../contexts/AuthContext'
import { usePlayer } from '../contexts/PlayerContext'
import { S54 } from '../assets/graphics'
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

function SortableTrackRow({
  track,
  index,
  onPlay,
  onRemove,
  formatDuration,
}: {
  track: PlaylistTrack
  index: number
  onPlay: (track: PlaylistTrack) => void
  onRemove: (trackId: string) => void
  formatDuration: (ms: number | null) => string
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: track.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : undefined,
  }

  return (
    <tr
      ref={setNodeRef}
      style={style}
      className={`hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors ${isDragging ? 'bg-[#FF1493]/5 dark:bg-[#FF1493]/15 shadow-lg' : ''}`}
    >
      <td className="px-2 py-3 text-sm text-gray-500 dark:text-gray-400 w-10">
        <button
          className="cursor-grab active:cursor-grabbing touch-none p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          {...attributes}
          {...listeners}
        >
          <FiMenu className="w-4 h-4" />
        </button>
      </td>
      <td className="px-2 py-3 text-sm text-gray-500 dark:text-gray-400 w-10">
        {index + 1}
      </td>
      <td className="px-4 py-3">
        <div>
          <div className="text-sm font-medium text-gray-900 dark:text-white">
            {track.title}
          </div>
          <div className="text-sm text-gray-600 dark:text-gray-400">
            {track.artist_name}
          </div>
        </div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-700 dark:text-gray-300">
        {track.album_title}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
        {formatDuration(track.duration_ms)}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center space-x-2">
          {track.has_file && (
            <button
              className="text-[#FF1493] hover:text-[#d10f7a]"
              title="Play track"
              onClick={() => onPlay(track)}
            >
              <FiPlay className="w-4 h-4" />
            </button>
          )}
          <button
            className="text-red-600 hover:text-red-700"
            title="Remove from playlist"
            onClick={() => onRemove(track.id)}
          >
            <FiX className="w-4 h-4" />
          </button>
        </div>
      </td>
    </tr>
  )
}

function Playlists() {
  const { isDjOrAbove } = useAuth()
  const globalPlayer = usePlayer()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [selectedPlaylist, setSelectedPlaylist] = useState<PlaylistDetail | null>(null)
  const [currentTrack, setCurrentTrack] = useState<PlaylistTrack & { artist_name: string } | null>(null)
  const coverArtInputRef = useRef<HTMLInputElement>(null)

  // Form states
  const [playlistName, setPlaylistName] = useState('')
  const [playlistDescription, setPlaylistDescription] = useState('')

  const queryClient = useQueryClient()

  // Fetch playlists
  const { data: playlistsData, isLoading, refetch } = useQuery({
    queryKey: ['playlists'],
    queryFn: () => playlistsApi.list(100, 0),
  })

  const playlists = playlistsData?.items || []

  // Fetch selected playlist details
  const { data: playlistDetail } = useQuery({
    queryKey: ['playlist', selectedPlaylist?.id],
    queryFn: () => playlistsApi.get(selectedPlaylist!.id),
    enabled: !!selectedPlaylist,
  })

  // Create playlist mutation
  const createMutation = useMutation({
    mutationFn: (data: { name: string; description?: string }) => playlistsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      setShowCreateModal(false)
      setPlaylistName('')
      setPlaylistDescription('')
      toast.success('Playlist created successfully')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to create playlist'
      toast.error(message)
    },
  })

  // Update playlist mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: { name?: string; description?: string } }) =>
      playlistsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      queryClient.invalidateQueries({ queryKey: ['playlist', selectedPlaylist?.id] })
      setShowEditModal(false)
      toast.success('Playlist updated successfully')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to update playlist'
      toast.error(message)
    },
  })

  // Delete playlist mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => playlistsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      if (selectedPlaylist) {
        setSelectedPlaylist(null)
      }
      toast.success('Playlist deleted successfully')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to delete playlist'
      toast.error(message)
    },
  })

  // Remove track mutation
  const removeTrackMutation = useMutation({
    mutationFn: ({ playlistId, trackId }: { playlistId: string; trackId: string }) =>
      playlistsApi.removeTrack(playlistId, trackId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlist', selectedPlaylist?.id] })
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      toast.success('Track removed from playlist')
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to remove track'
      toast.error(message)
    },
  })

  // Publish mutation
  const publishMutation = useMutation({
    mutationFn: (id: string) => playlistsApi.publish(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      queryClient.invalidateQueries({ queryKey: ['playlist', selectedPlaylist?.id] })
      toast.success('Playlist published to Sound Booth')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to publish'),
  })

  // Unpublish mutation
  const unpublishMutation = useMutation({
    mutationFn: (id: string) => playlistsApi.unpublish(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      queryClient.invalidateQueries({ queryKey: ['playlist', selectedPlaylist?.id] })
      toast.success('Playlist unpublished')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to unpublish'),
  })

  // Cover art upload mutation
  const uploadCoverArtMutation = useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) => playlistsApi.uploadCoverArt(id, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlists'] })
      queryClient.invalidateQueries({ queryKey: ['playlist', selectedPlaylist?.id] })
      toast.success('Cover art uploaded')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to upload cover art'),
  })

  // Reorder tracks mutation
  const reorderMutation = useMutation({
    mutationFn: ({ playlistId, trackPositions }: { playlistId: string; trackPositions: Array<{ track_id: string; position: number }> }) =>
      playlistsApi.reorder(playlistId, trackPositions),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['playlist', selectedPlaylist?.id] })
      toast.success('Track order updated')
    },
    onError: (error: any) => {
      queryClient.invalidateQueries({ queryKey: ['playlist', selectedPlaylist?.id] })
      toast.error(error.response?.data?.detail || 'Failed to reorder tracks')
    },
  })

  // DnD sensors for mouse, touch, and keyboard
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id || !playlistDetail || !selectedPlaylist) return

    const oldIndex = playlistDetail.tracks.findIndex(t => t.id === active.id)
    const newIndex = playlistDetail.tracks.findIndex(t => t.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return

    const reordered = arrayMove(playlistDetail.tracks, oldIndex, newIndex)

    // Optimistic update
    queryClient.setQueryData(['playlist', selectedPlaylist.id], {
      ...playlistDetail,
      tracks: reordered,
    })

    // Send new positions to backend
    const trackPositions = reordered.map((track, idx) => ({
      track_id: track.id,
      position: idx + 1,
    }))
    reorderMutation.mutate({ playlistId: selectedPlaylist.id, trackPositions })
  }, [playlistDetail, selectedPlaylist, queryClient, reorderMutation])

  const handleCoverArtUpload = (playlistId: string, event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      uploadCoverArtMutation.mutate({ id: playlistId, file })
    }
    event.target.value = ''
  }

  const formatDuration = (ms: number | null): string => {
    if (!ms) return '--:--'
    const minutes = Math.floor(ms / 60000)
    const seconds = Math.floor((ms % 60000) / 1000)
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }

  const getTotalDuration = (tracks: PlaylistTrack[]): string => {
    const totalMs = tracks.reduce((sum, track) => sum + (track.duration_ms || 0), 0)
    return formatDuration(totalMs)
  }

  const handleCreatePlaylist = () => {
    if (!playlistName.trim()) {
      toast.error('Please enter a playlist name')
      return
    }
    createMutation.mutate({
      name: playlistName,
      description: playlistDescription || undefined,
    })
  }

  const handleEditPlaylist = () => {
    if (!selectedPlaylist || !playlistName.trim()) {
      toast.error('Please enter a playlist name')
      return
    }
    updateMutation.mutate({
      id: selectedPlaylist.id,
      data: {
        name: playlistName,
        description: playlistDescription || undefined,
      },
    })
  }

  const handleDeletePlaylist = (playlist: Playlist) => {
    if (confirm(`Are you sure you want to delete "${playlist.name}"?`)) {
      deleteMutation.mutate(playlist.id)
    }
  }

  const handleRemoveTrack = (trackId: string) => {
    if (selectedPlaylist && confirm('Remove this track from the playlist?')) {
      removeTrackMutation.mutate({
        playlistId: selectedPlaylist.id,
        trackId,
      })
    }
  }

  const openEditModal = (playlist: PlaylistDetail) => {
    setPlaylistName(playlist.name)
    setPlaylistDescription(playlist.description || '')
    setShowEditModal(true)
  }

  const playPlaylist = () => {
    if (playlistDetail && playlistDetail.tracks.length > 0) {
      const firstTrack = playlistDetail.tracks[0]
      setCurrentTrack(firstTrack as PlaylistTrack & { artist_name: string })
    }
  }

  return (
    <div className="space-y-6">
      <Toaster position="top-right" />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Playlists</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            {playlists.length} playlist{playlists.length !== 1 ? 's' : ''}
          </p>
        </div>
        <div className="flex space-x-3">
          <button className="btn btn-secondary" onClick={() => refetch()}>
            <FiRefreshCw className="w-4 h-4 mr-2" />
            Refresh
          </button>
          <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
            <FiPlus className="w-4 h-4 mr-2" />
            Create Playlist
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Playlists List */}
        <div className="lg:col-span-1">
          <div className="card p-4">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4 flex items-center">
              <FiList className="w-5 h-5 mr-2" />
              My Playlists
            </h2>
            {isLoading ? (
              <div className="flex justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
              </div>
            ) : playlists.length > 0 ? (
              <div className="space-y-2">
                {playlists.map((playlist) => (
                  <div
                    key={playlist.id}
                    className={`p-3 rounded-lg cursor-pointer transition-colors group ${
                      selectedPlaylist?.id === playlist.id
                        ? 'bg-[#FF1493]/10 dark:bg-[#FF1493]/10'
                        : 'hover:bg-gray-100 dark:hover:bg-[#1C2128]'
                    }`}
                    onClick={() => setSelectedPlaylist(playlist as PlaylistDetail)}
                  >
                    <div className="flex items-start gap-3">
                      {/* Cover art thumbnail */}
                      <div className="w-10 h-10 rounded bg-gray-200 dark:bg-[#0D1117] flex-shrink-0 flex items-center justify-center overflow-hidden">
                        <img
                          src={playlist.cover_art_url || S54.defaultPlaylistCover}
                          alt=""
                          className="w-full h-full object-cover"
                          onError={(e) => { (e.target as HTMLImageElement).src = S54.defaultPlaylistCover }}
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <h3 className="font-medium text-gray-900 dark:text-white truncate flex items-center gap-1.5">
                          {playlist.name}
                          {playlist.is_published && (
                            <FiGlobe className="w-3 h-3 text-green-500 flex-shrink-0" title="Published" />
                          )}
                        </h3>
                        <p className="text-sm text-gray-600 dark:text-gray-400">
                          {playlist.track_count} track{playlist.track_count !== 1 ? 's' : ''}
                        </p>
                      </div>
                      <button
                        className="opacity-0 group-hover:opacity-100 text-red-600 hover:text-red-700 transition-opacity"
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDeletePlaylist(playlist)
                        }}
                      >
                        <FiTrash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <FiMusic className="w-16 h-16 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
                <p className="text-gray-500 dark:text-gray-400 mb-4">
                  No playlists yet
                </p>
                <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
                  Create Your First Playlist
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Playlist Details */}
        <div className="lg:col-span-2">
          {selectedPlaylist && playlistDetail ? (
            <div className="space-y-6">
              {/* Playlist Header */}
              <div className="card p-6">
                <div className="mb-4">
                  <div className="flex-1">
                    <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                      {playlistDetail.name}
                    </h2>
                    {playlistDetail.description && (
                      <p className="text-gray-600 dark:text-gray-400 mb-4">
                        {playlistDetail.description}
                      </p>
                    )}
                    <div className="flex items-center space-x-4 text-sm text-gray-600 dark:text-gray-400">
                      <span>{playlistDetail.track_count} tracks</span>
                      <span>•</span>
                      <span>{getTotalDuration(playlistDetail.tracks)}</span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 mt-4">
                    {/* Cover art upload */}
                    <input ref={coverArtInputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => handleCoverArtUpload(playlistDetail.id, e)} />
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => coverArtInputRef.current?.click()}
                      title="Upload cover art"
                    >
                      <FiImage className="w-4 h-4" />
                    </button>
                    {/* Publish/Unpublish (DJ+ only) */}
                    {isDjOrAbove && (
                      playlistDetail.is_published ? (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => unpublishMutation.mutate(playlistDetail.id)}
                          disabled={unpublishMutation.isPending}
                          title="Unpublish from Sound Booth"
                        >
                          <FiLock className="w-4 h-4 mr-1" />
                          Unpublish
                        </button>
                      ) : (
                        <button
                          className="btn btn-secondary btn-sm text-green-600 dark:text-green-400"
                          onClick={() => publishMutation.mutate(playlistDetail.id)}
                          disabled={publishMutation.isPending}
                          title="Publish to Sound Booth"
                        >
                          <FiGlobe className="w-4 h-4 mr-1" />
                          Publish
                        </button>
                      )
                    )}
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => openEditModal(playlistDetail)}
                    >
                      <FiEdit2 className="w-4 h-4" />
                    </button>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={playPlaylist}
                      disabled={playlistDetail.tracks.length === 0}
                    >
                      <FiPlay className="w-4 h-4 mr-2" />
                      Play All
                    </button>
                    <button
                      className="btn btn-secondary btn-sm"
                      disabled={playlistDetail.tracks.length === 0}
                      onClick={() => {
                        const playable = playlistDetail.tracks
                          .filter(t => t.has_file)
                          .map(t => ({
                            id: t.id,
                            title: t.title,
                            has_file: t.has_file,
                            artist_name: t.artist_name,
                            album_title: t.album_title,
                            album_cover_art_url: t.cover_art_url,
                            duration_ms: t.duration_ms,
                          }))
                        if (playable.length > 0) {
                          const shuffled = [...playable].sort(() => Math.random() - 0.5)
                          globalPlayer.playAlbum(shuffled, 0)
                        }
                      }}
                    >
                      <img src={S54.player.shuffle} alt="Shuffle" className="w-4 h-4 mr-2" />
                      Shuffle
                    </button>
                  </div>
                </div>
              </div>

              {/* Tracks Table */}
              <div className="card">
                <div className="p-4 border-b border-gray-200 dark:border-[#30363D]">
                  <h3 className="text-xl font-bold text-gray-900 dark:text-white">Tracks</h3>
                </div>

                {playlistDetail.tracks.length > 0 ? (
                  <div className="overflow-x-auto">
                    <DndContext
                      sensors={sensors}
                      collisionDetection={closestCenter}
                      onDragEnd={handleDragEnd}
                    >
                      <table className="w-full">
                        <thead className="bg-gray-50 dark:bg-[#161B22]">
                          <tr>
                            <th className="px-2 py-3 w-10"></th>
                            <th className="px-2 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-10">
                              #
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                              Title
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                              Album
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-24">
                              Duration
                            </th>
                            <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-32">
                              Actions
                            </th>
                          </tr>
                        </thead>
                        <SortableContext
                          items={playlistDetail.tracks.map(t => t.id)}
                          strategy={verticalListSortingStrategy}
                        >
                          <tbody className="bg-white dark:bg-[#0D1117] divide-y divide-gray-200 dark:divide-[#30363D]">
                            {playlistDetail.tracks.map((track, index) => (
                              <SortableTrackRow
                                key={track.id}
                                track={track}
                                index={index}
                                onPlay={(t) => setCurrentTrack(t as PlaylistTrack & { artist_name: string })}
                                onRemove={handleRemoveTrack}
                                formatDuration={formatDuration}
                              />
                            ))}
                          </tbody>
                        </SortableContext>
                      </table>
                    </DndContext>
                  </div>
                ) : (
                  <div className="p-12 text-center">
                    <FiMusic className="w-16 h-16 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
                    <p className="text-gray-500 dark:text-gray-400 mb-4">
                      No tracks in this playlist yet
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      Browse albums and add tracks from the album detail page
                    </p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="card p-12 text-center">
              <FiMusic className="w-20 h-20 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
              <p className="text-gray-500 dark:text-gray-400">
                Select a playlist to view details
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Audio Player */}
      <AudioPlayer
        track={currentTrack}
        onEnded={() => {
          // Auto-play next track in playlist
          if (currentTrack && playlistDetail) {
            const currentIndex = playlistDetail.tracks.findIndex(t => t.id === currentTrack.id)
            const nextTrack = playlistDetail.tracks[currentIndex + 1]
            if (nextTrack?.has_file) {
              setCurrentTrack(nextTrack as PlaylistTrack & { artist_name: string })
            } else {
              setCurrentTrack(null)
            }
          }
        }}
      />

      {/* Create Playlist Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Create Playlist</h2>
              <button onClick={() => setShowCreateModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <FiX className="w-6 h-6" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Name *
                </label>
                <input
                  type="text"
                  className="input w-full"
                  value={playlistName}
                  onChange={(e) => setPlaylistName(e.target.value)}
                  placeholder="My Awesome Playlist"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  className="input w-full"
                  rows={3}
                  value={playlistDescription}
                  onChange={(e) => setPlaylistDescription(e.target.value)}
                  placeholder="Optional description..."
                />
              </div>

              <div className="flex space-x-3 pt-4">
                <button
                  className="btn btn-secondary flex-1"
                  onClick={() => setShowCreateModal(false)}
                >
                  Cancel
                </button>
                <button
                  className="btn btn-primary flex-1"
                  onClick={handleCreatePlaylist}
                  disabled={createMutation.isPending}
                >
                  {createMutation.isPending ? 'Creating...' : 'Create'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit Playlist Modal */}
      {showEditModal && selectedPlaylist && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Edit Playlist</h2>
              <button onClick={() => setShowEditModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <FiX className="w-6 h-6" />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Name *
                </label>
                <input
                  type="text"
                  className="input w-full"
                  value={playlistName}
                  onChange={(e) => setPlaylistName(e.target.value)}
                  placeholder="My Awesome Playlist"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  className="input w-full"
                  rows={3}
                  value={playlistDescription}
                  onChange={(e) => setPlaylistDescription(e.target.value)}
                  placeholder="Optional description..."
                />
              </div>

              <div className="flex space-x-3 pt-4">
                <button
                  className="btn btn-secondary flex-1"
                  onClick={() => setShowEditModal(false)}
                >
                  Cancel
                </button>
                <button
                  className="btn btn-primary flex-1"
                  onClick={handleEditPlaylist}
                  disabled={updateMutation.isPending}
                >
                  {updateMutation.isPending ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Playlists
