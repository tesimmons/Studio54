import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { playlistsApi, bookPlaylistsApi, albumsApi, nowPlayingApi } from '../api/client'
import type { NowPlayingListener } from '../api/client'
import {
  FiMusic, FiPlay, FiHeadphones, FiBook, FiPlus, FiCheck,
  FiChevronDown, FiLoader,
} from 'react-icons/fi'
import { S54 } from '../assets/graphics'
import type { Playlist, BookPlaylist, Album } from '../types'
import { usePlayer } from '../contexts/PlayerContext'

const ROLE_BADGES: Record<string, { label: string; color: string }> = {
  director: { label: 'Director', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30' },
  dj: { label: 'DJ', color: 'bg-purple-500/20 text-purple-400 border-purple-500/30' },
  bouncer: { label: 'Bouncer', color: 'bg-blue-500/20 text-blue-400 border-blue-500/30' },
  partygoer: { label: 'Partygoer', color: 'bg-green-500/20 text-green-400 border-green-500/30' },
}

function getInitials(name: string): string {
  return name.split(/\s+/).map(w => w[0]).join('').toUpperCase().slice(0, 2)
}

// ── Now Listening card ──────────────────────────────────────────────────────

function ListenerCard({ listener }: { listener: NowPlayingListener }) {
  const badge = ROLE_BADGES[listener.role] || ROLE_BADGES.partygoer
  const navigate = useNavigate()

  const handleAlbumClick = () => {
    if (listener.album_id) navigate(`/disco-lounge/albums/${listener.album_id}`)
    else if (listener.artist_id) navigate(`/disco-lounge/artists/${listener.artist_id}`)
  }

  const handleArtistClick = (e: React.MouseEvent) => {
    if (listener.artist_id) { e.stopPropagation(); navigate(`/disco-lounge/artists/${listener.artist_id}`) }
  }

  const isClickable = !!(listener.album_id || listener.artist_id)

  return (
    <div
      className={`flex items-center gap-3 p-3 rounded-xl bg-gray-50 dark:bg-[#161B22]/60 border border-gray-200 dark:border-[#30363D]/50 min-w-[220px] max-w-[280px] transition-colors ${isClickable ? 'cursor-pointer hover:bg-gray-100 dark:hover:bg-[#1C2128]/60' : ''}`}
      onClick={isClickable ? handleAlbumClick : undefined}
    >
      <div className="relative flex-shrink-0">
        {listener.cover_art_url ? (
          <img src={listener.cover_art_url} alt="" className="w-10 h-10 rounded-lg object-cover" />
        ) : (
          <div className="w-10 h-10 rounded-lg bg-[#FF1493]/20 flex items-center justify-center text-[#ff4da6] font-semibold text-sm">
            {getInitials(listener.display_name)}
          </div>
        )}
        <div className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-green-500 border-2 border-white dark:border-gray-800 flex items-center justify-center">
          <div className="flex items-end gap-[1px] h-2">
            <div className="w-[2px] bg-white rounded-full animate-pulse" style={{ height: '4px', animationDelay: '0ms' }} />
            <div className="w-[2px] bg-white rounded-full animate-pulse" style={{ height: '6px', animationDelay: '150ms' }} />
            <div className="w-[2px] bg-white rounded-full animate-pulse" style={{ height: '3px', animationDelay: '300ms' }} />
          </div>
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-gray-900 dark:text-white truncate">{listener.display_name}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${badge.color} font-medium leading-none`}>{badge.label}</span>
        </div>
        <p className={`text-xs text-gray-600 dark:text-gray-300 truncate mt-0.5 ${listener.album_id ? 'hover:text-[#ff4da6]' : ''}`}>
          {listener.track_title}
          {listener.album_title && <span className="text-gray-400 dark:text-gray-500"> &middot; {listener.album_title}</span>}
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

// ── Compact playlist rows ───────────────────────────────────────────────────

function MusicPlaylistRow({ playlist, onPlay }: { playlist: Playlist; onPlay: () => void }) {
  return (
    <button
      className="w-full flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors text-left group"
      onClick={onPlay}
    >
      <div className="w-10 h-10 flex-shrink-0 rounded overflow-hidden bg-gray-200 dark:bg-[#21262D]">
        <img
          src={playlist.cover_art_url || S54.defaultPlaylistCover}
          alt={playlist.name}
          className="w-full h-full object-cover"
          onError={(e) => { (e.target as HTMLImageElement).src = S54.defaultPlaylistCover }}
        />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#FF1493] transition-colors">
          {playlist.name}
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
          {playlist.track_count} track{playlist.track_count !== 1 ? 's' : ''}
          {playlist.owner_name && <span> &middot; {playlist.owner_name}</span>}
        </p>
      </div>
      <FiPlay className="w-3.5 h-3.5 text-gray-400 group-hover:text-[#FF1493] flex-shrink-0 opacity-0 group-hover:opacity-100 transition-all" />
    </button>
  )
}

function BookPlaylistRow({ playlist, onPlay }: { playlist: BookPlaylist; onPlay: () => void }) {
  const formatDuration = (ms: number): string => {
    const h = Math.floor(ms / 3600000)
    const m = Math.floor((ms % 3600000) / 60000)
    return h > 0 ? `${h}h ${m}m` : `${m}m`
  }

  return (
    <button
      className="w-full flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors text-left group"
      onClick={onPlay}
    >
      <div className="w-10 h-10 flex-shrink-0 rounded overflow-hidden bg-teal-900/30 flex items-center justify-center">
        <FiBook className="w-5 h-5 text-teal-400" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-teal-400 transition-colors">
          {playlist.name}
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
          {playlist.chapter_count} chapter{playlist.chapter_count !== 1 ? 's' : ''}
          {playlist.total_duration_ms > 0 && <span> &middot; {formatDuration(playlist.total_duration_ms)}</span>}
        </p>
      </div>
      <FiPlay className="w-3.5 h-3.5 text-gray-400 group-hover:text-teal-400 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-all" />
    </button>
  )
}

// ── Add-to-playlist dropdown ────────────────────────────────────────────────

function AddToPlaylistMenu({
  album,
  playlists,
  onClose,
}: {
  album: Album
  playlists: Playlist[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [added, setAdded] = useState<string | null>(null)

  const addMutation = useMutation({
    mutationFn: async (playlistId: string) => {
      const detail = await albumsApi.get(album.id)
      const trackIds = detail.tracks.filter(t => t.has_file).map(t => t.id)
      if (trackIds.length === 0) throw new Error('No downloaded tracks')
      await playlistsApi.addTracksBulk(playlistId, trackIds)
      return playlistId
    },
    onSuccess: (playlistId) => {
      setAdded(playlistId)
      queryClient.invalidateQueries({ queryKey: ['publishedPlaylists'] })
      setTimeout(onClose, 800)
    },
  })

  const createMutation = useMutation({
    mutationFn: async (name: string) => {
      const playlist = await playlistsApi.create({ name })
      const detail = await albumsApi.get(album.id)
      const trackIds = detail.tracks.filter(t => t.has_file).map(t => t.id)
      if (trackIds.length > 0) await playlistsApi.addTracksBulk(playlist.id, trackIds)
      return playlist
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['publishedPlaylists'] })
      onClose()
    },
  })

  return (
    <div className="absolute right-0 top-full mt-1 z-50 w-56 bg-white dark:bg-[#161B22] border border-gray-200 dark:border-[#30363D] rounded-xl shadow-xl overflow-hidden">
      <div className="px-3 py-2 border-b border-gray-100 dark:border-[#30363D]">
        <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Add to Playlist</p>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate mt-0.5">{album.title}</p>
      </div>

      {/* Existing playlists */}
      <div className="max-h-48 overflow-y-auto sidebar-scroll py-1">
        {playlists.length === 0 ? (
          <p className="text-xs text-gray-400 px-3 py-2">No playlists yet</p>
        ) : playlists.map(p => (
          <button
            key={p.id}
            className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 dark:hover:bg-[#1C2128] text-left transition-colors"
            onClick={() => addMutation.mutate(p.id)}
            disabled={addMutation.isPending}
          >
            {added === p.id ? (
              <FiCheck className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
            ) : (
              <FiPlus className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
            )}
            <span className="text-sm text-gray-700 dark:text-gray-300 truncate">{p.name}</span>
          </button>
        ))}
      </div>

      {/* Create new */}
      <div className="border-t border-gray-100 dark:border-[#30363D] px-3 py-2">
        {creating ? (
          <div className="flex gap-1.5">
            <input
              autoFocus
              className="flex-1 text-xs px-2 py-1 rounded border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white outline-none focus:border-[#FF1493]"
              placeholder="New playlist name…"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && newName.trim()) createMutation.mutate(newName.trim())
                if (e.key === 'Escape') setCreating(false)
              }}
            />
            <button
              className="text-xs px-2 py-1 rounded bg-[#FF1493] text-white hover:bg-[#ff4da6] disabled:opacity-50"
              onClick={() => newName.trim() && createMutation.mutate(newName.trim())}
              disabled={!newName.trim() || createMutation.isPending}
            >
              {createMutation.isPending ? <FiLoader className="w-3 h-3 animate-spin" /> : 'Create'}
            </button>
          </div>
        ) : (
          <button
            className="w-full flex items-center gap-2 text-xs text-[#FF1493] hover:text-[#ff4da6] transition-colors"
            onClick={() => setCreating(true)}
          >
            <FiPlus className="w-3.5 h-3.5" />
            New playlist
          </button>
        )}
      </div>
    </div>
  )
}

// ── Recent album row ────────────────────────────────────────────────────────

function RecentAlbumRow({
  album,
  musicPlaylists,
}: {
  album: Album
  musicPlaylists: Playlist[]
}) {
  const { playAlbum } = usePlayer()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [playing, setPlaying] = useState(false)

  const handlePlay = async () => {
    setPlaying(true)
    try {
      const detail = await albumsApi.get(album.id)
      const playable = detail.tracks
        .filter(t => t.has_file)
        .map(t => ({
          id: t.id,
          title: t.title,
          has_file: t.has_file,
          artist_name: (t as any).artist_name ?? (album as any).artist_name ?? '',
          album_title: album.title,
          album_cover_art_url: album.cover_art_url,
          duration_ms: t.duration_ms,
        }))
      if (playable.length > 0) playAlbum(playable, 0)
    } finally {
      setPlaying(false)
    }
  }

  return (
    <div className="flex items-center gap-3 px-2 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-[#161B22]/60 group transition-colors">
      {/* Thumbnail */}
      <div
        className="w-10 h-10 flex-shrink-0 rounded overflow-hidden bg-gray-200 dark:bg-[#21262D] cursor-pointer"
        onClick={() => navigate(`/albums/${album.id}`)}
      >
        {album.cover_art_url ? (
          <img
            src={
              album.cover_art_url.startsWith('/api/') || album.cover_art_url.startsWith('http')
                ? album.cover_art_url
                : `/api/v1/${album.id}/cover-art`
            }
            alt={album.title}
            className="w-full h-full object-cover"
            onError={(e) => { (e.target as HTMLImageElement).src = S54.defaultAlbumArt }}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <FiMusic className="w-4 h-4 text-gray-400" />
          </div>
        )}
      </div>

      {/* Info */}
      <div
        className="flex-1 min-w-0 cursor-pointer"
        onClick={() => navigate(`/albums/${album.id}`)}
      >
        <p className="text-sm font-medium text-gray-900 dark:text-white truncate group-hover:text-[#FF1493] transition-colors">
          {album.title}
        </p>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">
          {(album as any).artist_name || ''}
        </p>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        <button
          className="w-7 h-7 flex items-center justify-center rounded-full hover:bg-[#FF1493]/10 text-gray-400 hover:text-[#FF1493] transition-colors"
          onClick={handlePlay}
          title="Play album"
        >
          {playing
            ? <FiLoader className="w-3.5 h-3.5 animate-spin" />
            : <FiPlay className="w-3.5 h-3.5" />
          }
        </button>

        <div className="relative">
          <button
            className="w-7 h-7 flex items-center justify-center rounded-full hover:bg-[#FF1493]/10 text-gray-400 hover:text-[#FF1493] transition-colors"
            onClick={() => setMenuOpen(o => !o)}
            title="Add to playlist"
          >
            <FiPlus className="w-3.5 h-3.5" />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <AddToPlaylistMenu
                album={album}
                playlists={musicPlaylists}
                onClose={() => setMenuOpen(false)}
              />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main page ───────────────────────────────────────────────────────────────

function SoundBooth() {
  const { playAlbum, playBook } = usePlayer()
  const [playingPlaylistId, setPlayingPlaylistId] = useState<string | null>(null)
  const [playingBookPlaylistId, setPlayingBookPlaylistId] = useState<string | null>(null)

  // Now Listening
  const { data: nowPlayingData } = useQuery({
    queryKey: ['nowPlaying'],
    queryFn: () => nowPlayingApi.getListeners(),
    refetchInterval: 10000,
  })
  const listeners = nowPlayingData?.listeners || []

  // Music playlists (published)
  const { data: publishedData, isLoading: playlistsLoading } = useQuery({
    queryKey: ['publishedPlaylists'],
    queryFn: () => playlistsApi.listPublished(200, 0),
  })
  const musicPlaylists: Playlist[] = publishedData?.items || []

  // All user playlists (for add-to-playlist menu)
  const { data: allPlaylistsData } = useQuery({
    queryKey: ['allPlaylists'],
    queryFn: () => playlistsApi.list(200, 0),
  })
  const allPlaylists: Playlist[] = allPlaylistsData?.items || []

  // Book playlists
  const { data: bookPlaylistsData, isLoading: bookPlaylistsLoading } = useQuery({
    queryKey: ['bookPlaylists'],
    queryFn: () => bookPlaylistsApi.list(),
  })
  const bookPlaylists: BookPlaylist[] = Array.isArray(bookPlaylistsData) ? bookPlaylistsData : []

  // Recently downloaded music albums
  const { data: recentData, isLoading: recentLoading } = useQuery({
    queryKey: ['recentAlbums'],
    queryFn: () => albumsApi.list({ status: 'downloaded', limit: 20 }),
  })
  const recentAlbums: Album[] = recentData?.items || []

  const handleMusicPlaylistPlay = async (playlist: Playlist) => {
    setPlayingPlaylistId(playlist.id)
    try {
      const detail = await playlistsApi.get(playlist.id)
      const playable = detail.tracks
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
      if (playable.length > 0) playAlbum(playable, 0)
    } finally {
      setPlayingPlaylistId(null)
    }
  }

  const handleBookPlaylistPlay = async (playlist: BookPlaylist) => {
    setPlayingBookPlaylistId(playlist.id)
    try {
      const detail = await bookPlaylistsApi.get(playlist.series_id)
      const playable = detail.chapters
        .filter(c => c.has_file)
        .map(c => ({
          id: c.chapter_id,
          title: c.chapter_title,
          has_file: c.has_file,
          album_title: c.book_title ?? playlist.name,
          album_cover_art_url: c.book_cover_art_url,
          duration_ms: c.duration_ms,
          isBookChapter: true as const,
        }))
      if (playable.length > 0) playBook(playable, 0, playlist.series_id)
    } finally {
      setPlayingBookPlaylistId(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Sound Booth</h1>
        <p className="mt-1 text-gray-600 dark:text-gray-400 text-sm">
          Active listeners, playlists, and recently added music
        </p>
      </div>

      {/* ── Now Listening ─────────────────────────────────────────────── */}
      <div className="card p-4">
        <div className="flex items-center gap-2 mb-3">
          <FiHeadphones className="w-4 h-4 text-[#FF1493]" />
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
            Now Listening
          </h2>
          {listeners.length > 0 && (
            <span className="text-xs bg-[#FF1493]/20 text-[#ff4da6] px-2 py-0.5 rounded-full font-medium">
              {listeners.length}
            </span>
          )}
        </div>
        {listeners.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500 italic">No active listeners right now</p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {listeners.map(l => <ListenerCard key={l.user_id} listener={l} />)}
          </div>
        )}
      </div>

      {/* ── Two-column body ────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">

        {/* LEFT: Playlists ─────────────────────────────────────────────── */}
        <div className="card p-4 flex flex-col min-h-[60vh]">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide flex items-center gap-2 mb-3 flex-shrink-0">
            <FiMusic className="w-4 h-4 text-[#FF1493]" />
            Playlists
          </h2>

          <div className="flex-1 min-h-0 overflow-y-auto sidebar-scroll space-y-4 pr-1">
            {/* Books section */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <FiBook className="w-3.5 h-3.5 text-teal-400" />
                <span className="text-xs font-semibold text-teal-500 dark:text-teal-400 uppercase tracking-wider">
                  Books
                </span>
                {bookPlaylists.length > 0 && (
                  <span className="text-xs text-gray-400">({bookPlaylists.length})</span>
                )}
              </div>
              {bookPlaylistsLoading ? (
                <div className="flex justify-center py-4">
                  <FiLoader className="w-4 h-4 animate-spin text-gray-400" />
                </div>
              ) : bookPlaylists.length === 0 ? (
                <p className="text-xs text-gray-400 dark:text-gray-500 italic px-2 py-1">
                  No book playlists — create one from a series page
                </p>
              ) : (
                <div className="space-y-0.5">
                  {bookPlaylists.map(p => (
                    playingBookPlaylistId === p.id ? (
                      <div key={p.id} className="flex items-center gap-3 px-2 py-1.5">
                        <FiLoader className="w-4 h-4 animate-spin text-teal-400 flex-shrink-0" />
                        <span className="text-sm text-teal-400 truncate">{p.name}</span>
                      </div>
                    ) : (
                      <BookPlaylistRow
                        key={p.id}
                        playlist={p}
                        onPlay={() => handleBookPlaylistPlay(p)}
                      />
                    )
                  ))}
                </div>
              )}
            </div>

            <div className="border-t border-gray-100 dark:border-[#30363D]" />

            {/* Music section */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <FiMusic className="w-3.5 h-3.5 text-[#FF1493]" />
                <span className="text-xs font-semibold text-[#FF1493] uppercase tracking-wider">
                  Music
                </span>
                {musicPlaylists.length > 0 && (
                  <span className="text-xs text-gray-400">({musicPlaylists.length})</span>
                )}
              </div>
              {playlistsLoading ? (
                <div className="flex justify-center py-4">
                  <FiLoader className="w-4 h-4 animate-spin text-gray-400" />
                </div>
              ) : musicPlaylists.length === 0 ? (
                <p className="text-xs text-gray-400 dark:text-gray-500 italic px-2 py-1">
                  No published playlists — DJs and Directors can publish from the Playlists page
                </p>
              ) : (
                <div className="space-y-0.5">
                  {musicPlaylists.map(p => (
                    playingPlaylistId === p.id ? (
                      <div key={p.id} className="flex items-center gap-3 px-2 py-1.5">
                        <FiLoader className="w-4 h-4 animate-spin text-[#FF1493] flex-shrink-0" />
                        <span className="text-sm text-[#FF1493] truncate">{p.name}</span>
                      </div>
                    ) : (
                      <MusicPlaylistRow
                        key={p.id}
                        playlist={p}
                        onPlay={() => handleMusicPlaylistPlay(p)}
                      />
                    )
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* RIGHT: Recently Downloaded ──────────────────────────────────── */}
        <div className="card p-4 flex flex-col min-h-[60vh]">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide flex items-center gap-2 mb-3 flex-shrink-0">
            <FiChevronDown className="w-4 h-4 text-[#FF8C00]" />
            Recently Added Music
            <span className="text-xs text-gray-400 font-normal normal-case tracking-normal">last 20</span>
          </h2>

          <div className="flex-1 min-h-0 overflow-y-auto sidebar-scroll pr-1">
            {recentLoading ? (
              <div className="flex justify-center py-8">
                <FiLoader className="w-5 h-5 animate-spin text-gray-400" />
              </div>
            ) : recentAlbums.length === 0 ? (
              <div className="text-center py-8">
                <FiMusic className="w-10 h-10 text-gray-300 dark:text-gray-700 mx-auto mb-2" />
                <p className="text-sm text-gray-400 dark:text-gray-500">No downloaded albums yet</p>
              </div>
            ) : (
              <div className="space-y-0.5">
                {recentAlbums.map(album => (
                  <RecentAlbumRow
                    key={album.id}
                    album={album}
                    musicPlaylists={allPlaylists}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default SoundBooth
