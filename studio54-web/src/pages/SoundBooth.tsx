import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { playlistsApi, nowPlayingApi } from '../api/client'
import type { NowPlayingListener } from '../api/client'
import { FiMusic, FiPlay, FiUser, FiChevronDown, FiChevronUp, FiHeadphones } from 'react-icons/fi'
import { S54 } from '../assets/graphics'
import type { PlaylistDetail, PlaylistTrack } from '../types'
import { usePlayer } from '../contexts/PlayerContext'

const ROLE_BADGES: Record<string, { label: string; color: string }> = {
  director: { label: 'Director', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30' },
  dj: { label: 'DJ', color: 'bg-purple-500/20 text-purple-400 border-purple-500/30' },
  bouncer: { label: 'Bouncer', color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' },
  partygoer: { label: 'Partygoer', color: 'bg-green-500/20 text-green-400 border-green-500/30' },
}

function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .map(w => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)
}

function ListenerCard({ listener }: { listener: NowPlayingListener }) {
  const badge = ROLE_BADGES[listener.role] || ROLE_BADGES.partygoer
  const navigate = useNavigate()

  const handleAlbumClick = () => {
    if (listener.album_id) {
      navigate(`/disco-lounge/albums/${listener.album_id}`)
    } else if (listener.artist_id) {
      navigate(`/disco-lounge/artists/${listener.artist_id}`)
    }
  }

  const handleArtistClick = (e: React.MouseEvent) => {
    if (listener.artist_id) {
      e.stopPropagation()
      navigate(`/disco-lounge/artists/${listener.artist_id}`)
    }
  }

  const isClickable = !!(listener.album_id || listener.artist_id)

  return (
    <div
      className={`flex items-center gap-3 p-3 rounded-xl bg-gray-50 dark:bg-[#161B22]/60 border border-gray-200 dark:border-[#30363D]/50 min-w-[220px] max-w-[280px] transition-colors ${isClickable ? 'cursor-pointer hover:bg-gray-100 dark:hover:bg-[#1C2128]/60' : ''}`}
      onClick={isClickable ? handleAlbumClick : undefined}
    >
      {/* Avatar or album art */}
      <div className="relative flex-shrink-0">
        {listener.cover_art_url ? (
          <img
            src={listener.cover_art_url}
            alt=""
            className="w-10 h-10 rounded-lg object-cover"
          />
        ) : (
          <div className="w-10 h-10 rounded-lg bg-[#FF1493]/50/20 flex items-center justify-center text-[#ff4da6] font-semibold text-sm">
            {getInitials(listener.display_name)}
          </div>
        )}
        {/* Animated listening indicator */}
        <div className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-green-500 border-2 border-white dark:border-gray-800 flex items-center justify-center">
          <div className="flex items-end gap-[1px] h-2">
            <div className="w-[2px] bg-white rounded-full animate-pulse" style={{ height: '4px', animationDelay: '0ms' }} />
            <div className="w-[2px] bg-white rounded-full animate-pulse" style={{ height: '6px', animationDelay: '150ms' }} />
            <div className="w-[2px] bg-white rounded-full animate-pulse" style={{ height: '3px', animationDelay: '300ms' }} />
          </div>
        </div>
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
            {listener.display_name}
          </span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${badge.color} font-medium leading-none`}>
            {badge.label}
          </span>
        </div>
        <p className={`text-xs text-gray-600 dark:text-gray-300 truncate mt-0.5 ${listener.album_id ? 'hover:text-[#ff4da6]' : ''}`}>
          {listener.track_title}
          {listener.album_title && (
            <span className="text-gray-400 dark:text-gray-500"> &middot; {listener.album_title}</span>
          )}
        </p>
        <p
          className={`text-[11px] truncate ${listener.artist_id ? 'text-[#ff4da6]/80 hover:text-[#ff4da6] cursor-pointer' : 'text-gray-400 dark:text-gray-500'}`}
          onClick={handleArtistClick}
        >
          {listener.artist_name}
        </p>
      </div>
    </div>
  )
}

function SoundBooth() {
  const [expandedPlaylist, setExpandedPlaylist] = useState<string | null>(null)
  const { play, playAlbum } = usePlayer()

  const { data: publishedData, isLoading } = useQuery({
    queryKey: ['publishedPlaylists'],
    queryFn: () => playlistsApi.listPublished(100, 0),
  })

  const { data: nowPlayingData } = useQuery({
    queryKey: ['nowPlaying'],
    queryFn: () => nowPlayingApi.getListeners(),
    refetchInterval: 10000,
  })

  const playlists = publishedData?.items || []
  const listeners = nowPlayingData?.listeners || []

  const { data: playlistDetail } = useQuery<PlaylistDetail>({
    queryKey: ['playlist', expandedPlaylist],
    queryFn: () => playlistsApi.get(expandedPlaylist!),
    enabled: !!expandedPlaylist,
  })

  const formatDuration = (ms: number | null): string => {
    if (!ms) return '--:--'
    const minutes = Math.floor(ms / 60000)
    const seconds = Math.floor((ms % 60000) / 1000)
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }

  const toPlayerTrack = (track: PlaylistTrack) => ({
    id: track.id,
    title: track.title,
    has_file: track.has_file,
    artist_name: track.artist_name,
    album_title: track.album_title,
    album_cover_art_url: track.cover_art_url,
    duration_ms: track.duration_ms,
  })

  const playTrack = (track: PlaylistTrack) => {
    if (track.has_file) {
      play(toPlayerTrack(track))
    }
  }

  const playAll = (detail: PlaylistDetail) => {
    const playable = detail.tracks.filter(t => t.has_file).map(toPlayerTrack)
    if (playable.length > 0) {
      playAlbum(playable, 0)
    }
  }

  const shuffleAll = (detail: PlaylistDetail) => {
    const playable = detail.tracks.filter(t => t.has_file).map(toPlayerTrack)
    if (playable.length > 0) {
      const shuffled = [...playable].sort(() => Math.random() - 0.5)
      playAlbum(shuffled, 0)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Sound Booth</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">
          Published playlists from DJs and Directors
        </p>
      </div>

      {/* Now Listening Section */}
      <div className="card p-4">
        <div className="flex items-center gap-2 mb-3">
          <FiHeadphones className="w-4 h-4 text-[#FF1493]" />
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
            Now Listening
          </h2>
          {listeners.length > 0 && (
            <span className="text-xs bg-[#FF1493]/50/20 text-[#ff4da6] px-2 py-0.5 rounded-full font-medium">
              {listeners.length}
            </span>
          )}
        </div>
        {listeners.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500 italic">
            No active listeners right now
          </p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {listeners.map((listener) => (
              <ListenerCard key={listener.user_id} listener={listener} />
            ))}
          </div>
        )}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
        </div>
      ) : playlists.length === 0 ? (
        <div className="card p-12 text-center">
          <FiMusic className="w-20 h-20 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
          <p className="text-lg text-gray-500 dark:text-gray-400">No published playlists yet</p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-2">
            DJs and Directors can publish playlists from the Playlists page
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {playlists.map((playlist) => (
            <div key={playlist.id} className="card overflow-hidden group">
              {/* Cover Art */}
              <div
                className="aspect-square bg-gradient-to-br from-[#FF1493]/20 to-[#FF8C00]/20 flex items-center justify-center relative cursor-pointer"
                onClick={() => setExpandedPlaylist(expandedPlaylist === playlist.id ? null : playlist.id)}
              >
                <img
                  src={playlist.cover_art_url || S54.defaultPlaylistCover}
                  alt={playlist.name}
                  className="w-full h-full object-cover"
                  onError={(e) => { (e.target as HTMLImageElement).src = S54.defaultPlaylistCover }}
                />
                <div className="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center">
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                    {expandedPlaylist === playlist.id ? (
                      <FiChevronUp className="w-10 h-10 text-white" />
                    ) : (
                      <FiChevronDown className="w-10 h-10 text-white" />
                    )}
                  </div>
                </div>
              </div>

              {/* Info */}
              <div className="p-4">
                <h3 className="font-semibold text-gray-900 dark:text-white truncate">{playlist.name}</h3>
                <div className="flex items-center gap-2 mt-1 text-sm text-gray-500 dark:text-gray-400">
                  <FiUser className="w-3 h-3" />
                  <span className="truncate">{playlist.owner_name || 'Unknown'}</span>
                </div>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  {playlist.track_count} track{playlist.track_count !== 1 ? 's' : ''}
                </p>
              </div>

              {/* Expanded track list */}
              {expandedPlaylist === playlist.id && playlistDetail && (
                <div className="border-t border-gray-200 dark:border-[#30363D]">
                  <div className="p-3 flex items-center justify-between bg-gray-50 dark:bg-[#161B22]/50">
                    <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Tracks</span>
                    <div className="flex items-center gap-1">
                      <button
                        className="btn btn-primary btn-sm py-1 px-3 text-xs"
                        onClick={() => playAll(playlistDetail)}
                        disabled={!playlistDetail.tracks.some(t => t.has_file)}
                      >
                        <FiPlay className="w-3 h-3 mr-1" />
                        Play All
                      </button>
                      <button
                        className="btn btn-secondary btn-sm py-1 px-3 text-xs"
                        onClick={() => shuffleAll(playlistDetail)}
                        disabled={!playlistDetail.tracks.some(t => t.has_file)}
                      >
                        <img src={S54.player.shuffle} alt="Shuffle" className="w-3 h-3 mr-1" />
                        Shuffle
                      </button>
                    </div>
                  </div>
                  <div className="max-h-64 overflow-y-auto divide-y divide-gray-100 dark:divide-[#30363D]">
                    {playlistDetail.tracks.map((track, idx) => (
                      <div
                        key={track.id}
                        className="px-4 py-2 flex items-center gap-3 hover:bg-gray-50 dark:hover:bg-[#161B22]/50 transition-colors"
                      >
                        <span className="text-xs text-gray-400 w-5 text-right">{idx + 1}</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-900 dark:text-white truncate">{track.title}</p>
                          <p className="text-xs text-gray-500 dark:text-gray-400 truncate">{track.artist_name}</p>
                        </div>
                        <span className="text-xs text-gray-400">{formatDuration(track.duration_ms)}</span>
                        {track.has_file && (
                          <button
                            className="text-[#FF1493] hover:text-[#ff4da6]"
                            onClick={() => playTrack(track)}
                          >
                            <FiPlay className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default SoundBooth
