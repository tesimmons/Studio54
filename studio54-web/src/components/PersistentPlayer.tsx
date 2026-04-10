import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FiX, FiExternalLink, FiMinimize2, FiVolume2, FiVolume1, FiVolumeX, FiSave, FiCheck } from 'react-icons/fi'
import { usePlayer, type RepeatMode } from '../contexts/PlayerContext'
import AddToPlaylistDropdown from './AddToPlaylistDropdown'
import LyricsPanel from './LyricsPanel'
import StarRating from './StarRating'
import { tracksApi, playlistsApi, booksApi, bookProgressApi } from '../api/client'
import toast from 'react-hot-toast'
import { S54 } from '../assets/graphics'

function PersistentPlayer() {
  const { state, pause, resume, next, previous, removeFromQueue, clearQueue, isPopOutOpen, popOut, closePopOut, setRepeatMode, toggleShuffle, setVolume, toggleMute, closePlayer, audioRef, popOutCurrentTime, popOutDuration } = usePlayer()
  const { currentTrack, queue, playHistory, isPlaying, repeatMode, shuffleMode, volume, isMuted } = state
  const navigate = useNavigate()
  const keepAliveRef = useRef<HTMLAudioElement>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [showQueue, setShowQueue] = useState(false)
  const [showLyrics, setShowLyrics] = useState(false)
  const [savingQueue, setSavingQueue] = useState(false)
  const [queuePlaylistName, setQueuePlaylistName] = useState('')
  const queryClient = useQueryClient()
  const saveQueueInputRef = useRef<HTMLInputElement>(null)

  const saveQueueMutation = useMutation({
    mutationFn: async (name: string) => {
      const allTracks = [currentTrack!, ...queue]
      const musicTracks = allTracks.filter(t => !t.isBookChapter)
      const chapterTracks = allTracks.filter(t => t.isBookChapter)
      if (musicTracks.length === 0 && chapterTracks.length === 0) {
        throw new Error('Queue is empty')
      }
      const playlist = await playlistsApi.create({ name })
      for (const track of musicTracks) {
        await playlistsApi.addTrack(playlist.id, track.id)
      }
      for (const chapter of chapterTracks) {
        await playlistsApi.addChapter(playlist.id, chapter.id)
      }
      return { playlist, trackCount: musicTracks.length + chapterTracks.length }
    },
    onSuccess: ({ playlist, trackCount }) => {
      toast.success(`Saved ${trackCount} items to "${playlist.name}"`)
      queryClient.invalidateQueries({ queryKey: ['playlists-list'] })
      setSavingQueue(false)
      setQueuePlaylistName('')
    },
    onError: (error: any) => {
      const msg = error?.response?.data?.detail || error?.message || 'Failed to save queue'
      toast.error(msg)
    },
  })

  const { data: lyricsData } = useQuery({
    queryKey: ['lyrics', currentTrack?.id],
    queryFn: () => tracksApi.getLyrics(currentTrack!.id),
    enabled: !!currentTrack?.id && showLyrics && !isPopOutOpen,
    staleTime: Infinity,
    retry: false,
  })

  const [trackRating, setTrackRating] = useState<number | null>(null)

  const isBookChapter = !!currentTrack?.isBookChapter

  const { data: trackRatingData } = useQuery({
    queryKey: ['track-rating', currentTrack?.id],
    queryFn: () => tracksApi.getRating(currentTrack!.id),
    enabled: !!currentTrack?.id && !isBookChapter,
  })

  useEffect(() => {
    if (isBookChapter) {
      setTrackRating(null)
    } else {
      setTrackRating(trackRatingData?.user_rating ?? null)
    }
  }, [trackRatingData, isBookChapter])

  const ratingMutation = useMutation({
    mutationFn: async (rating: number | null) => {
      if (isBookChapter) throw new Error('Rating not supported for book chapters')
      return tracksApi.setRating(currentTrack!.id, rating)
    },
    onSuccess: (data) => {
      setTrackRating(data.user_rating)
      queryClient.invalidateQueries({ queryKey: ['track-rating', currentTrack?.id] })
      if (currentTrack?.album_id) {
        queryClient.invalidateQueries({ queryKey: ['album', currentTrack.album_id] })
      }
    },
  })

  const getAudioSrc = useCallback(() => {
    if (!currentTrack) return null
    const authToken = localStorage.getItem('studio54_token')
    const tokenParam = authToken ? `?token=${encodeURIComponent(authToken)}` : ''
    if (currentTrack.has_file) {
      const baseUrl = (import.meta as any).env?.VITE_API_URL || '/api/v1'
      return `${baseUrl}/tracks/${currentTrack.id}/stream${tokenParam}`
    }
    if (currentTrack.muse_file_id) {
      const museUrl = (import.meta as any).env?.VITE_MUSE_API_URL || 'http://localhost:8007'
      return `${museUrl}/api/v1/files/${currentTrack.muse_file_id}/stream${tokenParam}`
    }
    if (currentTrack.preview_url) {
      if (currentTrack.preview_url.includes('/api/v1/') && authToken) {
        const separator = currentTrack.preview_url.includes('?') ? '&' : '?'
        return `${currentTrack.preview_url}${separator}token=${encodeURIComponent(authToken)}`
      }
      return currentTrack.preview_url
    }
    return null
  }, [currentTrack])

  // Skip audio management when pop-out is active
  useEffect(() => {
    if (isPopOutOpen) return
    const audio = audioRef.current
    if (!audio) return
    const src = getAudioSrc()
    if (src) {
      audio.src = src
      audio.load()
      if (isPlaying) {
        const onCanPlay = () => {
          audio.play().catch((e) => console.warn('Playback failed:', e))
          audio.removeEventListener('canplay', onCanPlay)
        }
        audio.addEventListener('canplay', onCanPlay)
      }
    }
  }, [currentTrack?.id, isPopOutOpen])

  useEffect(() => {
    if (isPopOutOpen) return
    const audio = audioRef.current
    if (!audio || !currentTrack) return
    if (isPlaying) {
      audio.play().catch(() => {})
    } else {
      audio.pause()
    }
  }, [isPlaying, isPopOutOpen])

  useEffect(() => {
    if (isPopOutOpen) return
    const audio = audioRef.current
    if (!audio) return
    audio.volume = isMuted ? 0 : volume
  }, [volume, isMuted, isPopOutOpen])

  // iOS keepalive
  useEffect(() => {
    if (isPopOutOpen) return
    const keepAlive = keepAliveRef.current
    if (!keepAlive) return
    keepAlive.volume = 0.01
    keepAlive.loop = true
    if (isPlaying && currentTrack) {
      keepAlive.play().catch(() => {})
    } else {
      keepAlive.pause()
    }
  }, [isPlaying, currentTrack?.id, isPopOutOpen])

  // Media Session API
  useEffect(() => {
    if (isPopOutOpen) return
    if (!('mediaSession' in navigator) || !currentTrack) return
    navigator.mediaSession.metadata = new MediaMetadata({
      title: currentTrack.title,
      artist: currentTrack.artist_name || '',
      album: currentTrack.album_title || '',
      artwork: currentTrack.album_cover_art_url
        ? [{ src: currentTrack.album_cover_art_url, sizes: '512x512', type: 'image/jpeg' }]
        : [],
    })
    navigator.mediaSession.setActionHandler('play', () => resume())
    navigator.mediaSession.setActionHandler('pause', () => pause())
    navigator.mediaSession.setActionHandler('previoustrack', () => previous())
    navigator.mediaSession.setActionHandler('nexttrack', () => next())
    navigator.mediaSession.setActionHandler('seekto', (details) => {
      const audio = audioRef.current
      if (audio && details.seekTime != null) {
        audio.currentTime = details.seekTime
      }
    })
  }, [currentTrack?.id, currentTrack?.title, isPopOutOpen, resume, pause, previous, next])

  useEffect(() => {
    if (isPopOutOpen) return
    if ('mediaSession' in navigator) {
      navigator.mediaSession.playbackState = isPlaying ? 'playing' : 'paused'
    }
  }, [isPlaying, isPopOutOpen])

  const handleEnded = useCallback(() => {
    if (currentTrack?.id) {
      if (state.bookId) {
        booksApi.recordChapterPlay(currentTrack.id).catch(() => {})

        // Save progress to server: chapter finished
        const isLastChapter = queue.length === 0 && repeatMode === 'off'
        bookProgressApi.upsert(state.bookId, {
          chapter_id: currentTrack.id,
          position_ms: 0,
          ...(isLastChapter ? { completed: true } : {}),
        }).catch(() => {})
      } else {
        tracksApi.recordPlay(currentTrack.id).catch(() => {})
      }
    }

    if (repeatMode === 'one') {
      const audio = audioRef.current
      if (audio) {
        audio.currentTime = 0
        audio.play().catch(() => {})
      }
    } else {
      next()
    }
  }, [repeatMode, next, currentTrack?.id, state.bookId, queue.length])

  const handleTimeUpdate = () => {
    const audio = audioRef.current
    if (audio) {
      setCurrentTime(audio.currentTime)
      setDuration(audio.duration || 0)
    }
  }

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current
    if (audio) {
      audio.currentTime = parseFloat(e.target.value)
      setCurrentTime(audio.currentTime)
    }
  }

  const formatTime = (seconds: number): string => {
    if (!seconds || isNaN(seconds)) return '0:00'
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const cycleRepeat = () => {
    const modes: RepeatMode[] = ['off', 'all', 'one']
    const idx = modes.indexOf(repeatMode)
    setRepeatMode(modes[(idx + 1) % modes.length])
  }

  const repeatLabel = repeatMode === 'one' ? '1' : repeatMode === 'all' ? 'All' : ''

  const VolumeIcon = isMuted || volume === 0 ? FiVolumeX : volume < 0.5 ? FiVolume1 : FiVolume2

  const isPreview = !currentTrack?.has_file && !currentTrack?.muse_file_id && currentTrack?.preview_url

  if (!currentTrack) return null

  const renderQueueList = (maxHeight: string, widthClass: string = 'w-80') => (
    <div className={`${widthClass} bg-white dark:bg-[#161B22] flex flex-col h-full`} style={{ maxHeight }}>
      <div className="border-b border-gray-200 dark:border-[#30363D] flex-shrink-0">
        <div className="flex items-center justify-between p-3">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
            Queue ({queue.length})
          </h3>
          {queue.length > 0 && (
            <div className="flex items-center space-x-2">
              <button
                onClick={() => { setSavingQueue(true); setTimeout(() => saveQueueInputRef.current?.focus(), 0) }}
                className="text-xs text-gray-500 hover:text-[#FF1493] dark:text-[#8B949E] dark:hover:text-[#FF1493] flex items-center"
                title="Save queue as new playlist"
              >
                <FiSave className="w-3 h-3 mr-1" />
                Save
              </button>
              <button
                onClick={clearQueue}
                className="text-xs text-gray-500 hover:text-gray-700 dark:text-[#8B949E] dark:hover:text-[#E6EDF3]"
                title="Clear all tracks from queue"
              >
                Clear
              </button>
            </div>
          )}
        </div>
        {savingQueue && (
          <div className="px-3 pb-3 flex items-center space-x-1">
            <input
              ref={saveQueueInputRef}
              type="text"
              value={queuePlaylistName}
              onChange={(e) => setQueuePlaylistName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && queuePlaylistName.trim()) saveQueueMutation.mutate(queuePlaylistName.trim())
                if (e.key === 'Escape') { setSavingQueue(false); setQueuePlaylistName('') }
              }}
              placeholder="Playlist name..."
              disabled={saveQueueMutation.isPending}
              className="flex-1 min-w-0 text-sm px-2 py-1 rounded border border-gray-300 dark:border-[#30363D] bg-white dark:bg-[#0D1117] text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:border-[#FF1493]"
            />
            <button
              onClick={() => { const n = queuePlaylistName.trim(); if (n) saveQueueMutation.mutate(n) }}
              disabled={!queuePlaylistName.trim() || saveQueueMutation.isPending}
              className="p-1 text-[#FF1493] hover:text-[#d10f7a] disabled:opacity-40 disabled:cursor-not-allowed"
              title="Create playlist from queue"
            >
              <FiCheck className="w-4 h-4" />
            </button>
            <button
              onClick={() => { setSavingQueue(false); setQueuePlaylistName('') }}
              className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-[#E6EDF3]"
              title="Cancel"
            >
              <FiX className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {playHistory.length > 0 && (
          <>
            {playHistory.map((track, index) => (
              <div
                key={`history-${track.id}-${index}`}
                className="flex items-center justify-between px-3 py-2 opacity-40"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-gray-500 dark:text-[#8B949E] truncate">{track.title}</div>
                  <div className="text-xs text-gray-400 dark:text-[#484F58] truncate">{track.artist_name}</div>
                </div>
              </div>
            ))}
            {queue.length > 0 && (
              <div className="border-t border-gray-200 dark:border-[#30363D]" />
            )}
          </>
        )}
        {queue.length === 0 && playHistory.length === 0 ? (
          <p className="p-4 text-sm text-gray-500 dark:text-[#8B949E] text-center">Queue is empty</p>
        ) : (
          queue.map((track, index) => (
            <div
              key={`${track.id}-${index}`}
              className="flex items-center justify-between px-3 py-2 hover:bg-gray-50 dark:hover:bg-[#1C2128]"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm text-gray-900 dark:text-white truncate">{track.title}</div>
                <div className="text-xs text-gray-500 dark:text-[#8B949E] truncate">{track.artist_name}</div>
              </div>
              <div className="flex items-center ml-2 flex-shrink-0 space-x-1">
                <AddToPlaylistDropdown trackId={track.id} />
                <button
                  onClick={() => removeFromQueue(index)}
                  className="text-gray-400 hover:text-gray-600 dark:hover:text-[#E6EDF3]"
                  title="Remove from queue"
                >
                  <FiX className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )

  const renderShuffleButton = (size: string = 'w-10 h-10', padding: string = 'p-2') => (
    <button
      onClick={toggleShuffle}
      title={`Shuffle: ${shuffleMode ? 'on' : 'off'}`}
      className={`${padding} rounded transition-colors ${
        shuffleMode
          ? 'bg-[#FF1493]/10 text-[#FF1493]'
          : 'text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]'
      }`}
    >
      <img src={S54.player.shuffle} alt="Shuffle" className={`${size} object-contain dark:invert`} />
    </button>
  )

  const renderRepeatButton = (size: string = 'w-10 h-10', padding: string = 'p-2') => (
    <button
      onClick={cycleRepeat}
      title={`Repeat: ${repeatMode}`}
      className={`${padding} rounded transition-colors relative ${
        repeatMode !== 'off'
          ? 'bg-[#FF1493]/10 text-[#FF1493]'
          : 'text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]'
      }`}
    >
      <img src={S54.player.repeat} alt="Repeat" className={`${size} object-contain`} />
      {repeatLabel && (
        <span className="absolute -top-1 -right-1 text-[8px] font-bold text-[#FF1493]">
          {repeatLabel}
        </span>
      )}
    </button>
  )

  const audioElement = (
    <>
      <audio
        ref={audioRef}
        preload="auto"
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleTimeUpdate}
        onEnded={handleEnded}
        onError={(e) => {
          const audio = e.currentTarget
          const err = audio.error
          console.error('Audio error:', err?.code, err?.message, 'src:', audio.src)
        }}
      />
      <audio ref={keepAliveRef} src="/silence.mp3" preload="auto" />
    </>
  )

  // Pop-out indicator bar — shown when audio is playing in a separate window
  if (isPopOutOpen) {
    const displayTime = popOutCurrentTime
    const displayDuration = popOutDuration

    return (
      <>
        {audioElement}
        <div className="fixed bottom-0 left-0 right-0 h-14 bg-white dark:bg-[#161B22] border-t border-gray-200 dark:border-[#30363D] z-50 flex items-center px-4 shadow-lg">
          {/* Album Art Thumbnail */}
          <div className="w-10 h-10 rounded bg-gray-200 dark:bg-[#0D1117] flex-shrink-0 overflow-hidden mr-3">
            {currentTrack.album_cover_art_url ? (
              <img src={currentTrack.album_cover_art_url} alt="" className="w-full h-full object-cover" />
            ) : (
              <img src={S54.defaultAlbumArt} alt="" className="w-full h-full object-cover" />
            )}
          </div>

          {/* Track Info */}
          <div className="min-w-0 flex-1 mr-4">
            <div className="text-sm font-medium text-gray-900 dark:text-white truncate">{currentTrack.title}</div>
            <div className="text-xs text-[#FF1493] truncate">Playing in pop-out window</div>
          </div>

          {/* Mini progress */}
          <div className="hidden md:flex items-center space-x-2 mr-4 flex-1 max-w-xs">
            <span className="text-[10px] text-gray-500 dark:text-[#8B949E] w-8 text-right">
              {formatTime(displayTime)}
            </span>
            <div className="flex-1 h-1 bg-gray-200 dark:bg-[#30363D] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#FF1493] rounded-full transition-all"
                style={{ width: displayDuration > 0 ? `${(displayTime / displayDuration) * 100}%` : '0%' }}
              />
            </div>
            <span className="text-[10px] text-gray-500 dark:text-[#8B949E] w-8">
              {formatTime(displayDuration)}
            </span>
          </div>

          {/* Transport Controls */}
          <div className="flex items-center space-x-1 mr-2">
            <button
              onClick={previous}
              title="Previous"
              className="p-1 text-gray-600 dark:text-[#8B949E] hover:text-gray-900 dark:hover:text-white transition-colors"
            >
              <img src={S54.player.rewind} alt="Previous" className="w-4 h-4 object-contain" />
            </button>
            <button
              onClick={() => isPlaying ? pause() : resume()}
              title={isPlaying ? 'Pause' : 'Play'}
              className="w-8 h-8 rounded-full bg-[#FF1493] hover:bg-[#d10f7a] text-white flex items-center justify-center transition-colors"
            >
              <img
                src={isPlaying ? S54.player.pause : S54.player.play}
                alt={isPlaying ? 'Pause' : 'Play'}
                className="w-4 h-4 object-contain brightness-0 invert"
              />
            </button>
            <button
              onClick={next}
              title="Next"
              className="p-1 text-gray-600 dark:text-[#8B949E] hover:text-gray-900 dark:hover:text-white transition-colors"
            >
              <img src={S54.player.fastForward} alt="Next" className="w-4 h-4 object-contain" />
            </button>
          </div>

          {/* Dock button — close pop-out and return player here */}
          <button
            onClick={closePopOut}
            title="Dock player back to this window"
            className="p-2 text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3] transition-colors"
          >
            <FiMinimize2 className="w-5 h-5" />
          </button>
        </div>
      </>
    )
  }

  // Full Bottom Bar (default)
  return (
    <>
      {audioElement}

      {showLyrics && (
        <LyricsPanel
          syncedLyrics={lyricsData?.synced_lyrics ?? null}
          plainLyrics={lyricsData?.plain_lyrics ?? null}
          currentTime={currentTime}
          onClose={() => setShowLyrics(false)}
          queueOpen={showQueue}
        />
      )}

      {/* Player Bar */}
      <div className="fixed bottom-0 left-0 right-0 h-32 md:h-28 lg:h-32 xl:h-40 bg-white dark:bg-[#161B22] border-t border-gray-200 dark:border-[#30363D] z-50 flex flex-col shadow-lg">

        {/* Top row: album art, track info, transport, desktop utility */}
        <div className="flex items-center flex-1 px-2 md:px-4">

          {/* Album Art + Track Info */}
          <div className="flex items-center min-w-0 w-36 md:w-64 lg:w-80 xl:w-96 flex-shrink-0">
            <button
              className="w-16 h-16 md:w-20 md:h-20 lg:w-28 lg:h-28 xl:w-36 xl:h-36 rounded bg-gray-200 dark:bg-[#0D1117] flex-shrink-0 overflow-hidden cursor-pointer hover:opacity-80 transition-opacity"
              onClick={() => { if (currentTrack.album_id) navigate(`/disco-lounge/albums/${currentTrack.album_id}`) }}
              title={currentTrack.album_title ? `Go to ${currentTrack.album_title}` : 'Go to album'}
            >
              {currentTrack.album_cover_art_url ? (
                <img
                  src={currentTrack.album_cover_art_url}
                  alt=""
                  className="w-full h-full object-cover"
                />
              ) : (
                <img src={S54.defaultAlbumArt} alt="" className="w-full h-full object-cover" />
              )}
            </button>
            <div className="ml-3 min-w-0">
              <button
                className="text-sm font-medium text-gray-900 dark:text-white truncate flex items-center gap-2 hover:text-[#FF1493] dark:hover:text-[#FF1493] transition-colors max-w-full"
                onClick={() => { if (currentTrack.album_id) navigate(`/disco-lounge/albums/${currentTrack.album_id}`) }}
                title={currentTrack.album_title ? `Go to ${currentTrack.album_title}` : 'Go to album'}
              >
                <span className="truncate">{currentTrack.title}</span>
                {isPreview && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 flex-shrink-0">
                    30s Preview
                  </span>
                )}
              </button>
              <button
                className="text-xs text-gray-500 dark:text-[#8B949E] hover:text-[#FF1493] truncate block"
                onClick={() => {
                  if (currentTrack.artist_id) navigate(`/disco-lounge/artists/${currentTrack.artist_id}`)
                }}
                title="Go to artist"
              >
                {currentTrack.artist_name}
              </button>
              {!isBookChapter && (
                <div className="mt-0.5 hidden md:block">
                  <StarRating rating={trackRating} onChange={(r) => ratingMutation.mutate(r)} size="sm" />
                </div>
              )}
            </div>
          </div>

          {/* Controls */}
          <div className="flex-1 flex flex-col items-center justify-center max-w-2xl mx-auto">
            <div className="flex items-center space-x-1 md:space-x-3 mb-1">
              <button
                onClick={previous}
                title="Play previous track"
                className="text-gray-600 dark:text-[#8B949E] hover:text-gray-900 dark:hover:text-white transition-colors"
              >
                <img src={S54.player.rewind} alt="Previous" className="w-4 h-4 md:w-5 md:h-5 lg:w-6 lg:h-6 xl:w-8 xl:h-8 object-contain" />
              </button>
              <button
                onClick={() => isPlaying ? pause() : resume()}
                title={isPlaying ? 'Pause playback' : 'Resume playback'}
                className="w-7 h-7 md:w-9 md:h-9 lg:w-11 lg:h-11 xl:w-14 xl:h-14 rounded-full bg-[#FF1493] hover:bg-[#d10f7a] text-white flex items-center justify-center transition-colors"
              >
                <img
                  src={isPlaying ? S54.player.pause : S54.player.play}
                  alt={isPlaying ? 'Pause' : 'Play'}
                  className="w-4 h-4 md:w-5 md:h-5 lg:w-6 lg:h-6 xl:w-8 xl:h-8 object-contain brightness-0 invert"
                />
              </button>
              <button
                onClick={next}
                title="Play next track in queue"
                className="text-gray-600 dark:text-[#8B949E] hover:text-gray-900 dark:hover:text-white transition-colors"
              >
                <img src={S54.player.fastForward} alt="Next" className="w-4 h-4 md:w-5 md:h-5 lg:w-6 lg:h-6 xl:w-8 xl:h-8 object-contain" />
              </button>
            </div>

            {/* Progress Bar */}
            <div className="w-full flex items-center space-x-2">
              <span className="text-xs text-gray-500 dark:text-[#8B949E] w-10 text-right">
                {formatTime(currentTime)}
              </span>
              <input
                type="range"
                min={0}
                max={duration || 0}
                value={currentTime}
                onChange={handleSeek}
                className="flex-1 h-1 bg-gray-200 dark:bg-[#30363D] rounded-full appearance-none cursor-pointer accent-[#FF1493]"
              />
              <span className="text-xs text-gray-500 dark:text-[#8B949E] w-10">
                {formatTime(duration)}
              </span>
            </div>
          </div>

          {/* Desktop utility buttons */}
          <div className="hidden md:flex w-auto items-center justify-end flex-shrink-0 space-x-2">
            <button
              onClick={toggleMute}
              title={isMuted ? 'Unmute' : 'Mute'}
              className="p-2 rounded-lg transition-colors text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]"
            >
              <VolumeIcon className="w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10" />
            </button>
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={isMuted ? 0 : volume}
              onChange={(e) => {
                const v = parseFloat(e.target.value)
                if (isMuted && v > 0) toggleMute()
                setVolume(v)
              }}
              className="w-14 lg:w-20 h-1 bg-gray-200 dark:bg-[#30363D] rounded-full appearance-none cursor-pointer accent-[#FF1493]"
              title={`Volume: ${Math.round((isMuted ? 0 : volume) * 100)}%`}
            />
            {renderShuffleButton('w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10', 'p-1 lg:p-2')}
            {renderRepeatButton('w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10', 'p-1 lg:p-2')}
            <button
              onClick={() => setShowLyrics(!showLyrics)}
              title={showLyrics ? 'Hide lyrics' : 'Show lyrics'}
              className={`p-1 lg:p-2 rounded-lg transition-colors ${
                showLyrics
                  ? 'bg-[#FF1493]/10 text-[#FF1493]'
                  : 'text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]'
              }`}
            >
              <img src={S54.player.lyrics} alt="Lyrics" className="w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10 object-contain" />
            </button>
            <AddToPlaylistDropdown trackId={currentTrack.id} />
            <button
              onClick={popOut}
              title="Pop out to new window"
              className="p-1 lg:p-2 rounded-lg transition-colors text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]"
            >
              <FiExternalLink className="w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10" />
            </button>
            <button
              onClick={() => setShowQueue(prev => !prev)}
              title={showQueue ? 'Hide play queue' : 'Show play queue'}
              className={`p-1 lg:p-2 rounded-lg transition-colors relative ${
                showQueue
                  ? 'bg-[#FF1493]/10 text-[#FF1493]'
                  : 'text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]'
              }`}
            >
              <img src={S54.player.playlist} alt="Queue" className="w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10 object-contain" />
              {queue.length > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 lg:w-5 lg:h-5 bg-[#FF1493] text-white text-[8px] lg:text-[10px] font-bold rounded-full flex items-center justify-center">
                  {queue.length}
                </span>
              )}
            </button>
            <button
              onClick={closePlayer}
              title="Close player"
              className="p-1 lg:p-2 rounded-lg transition-colors text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]"
            >
              <FiX className="w-5 h-5 lg:w-8 lg:h-8 xl:w-10 xl:h-10" />
            </button>
          </div>

          {/* Mobile: close button only in top row */}
          <div className="flex md:hidden items-center flex-shrink-0">
            <button
              onClick={closePlayer}
              title="Close player"
              className="p-1 rounded-lg transition-colors text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]"
            >
              <FiX className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Mobile bottom row: shuffle, repeat, lyrics, queue */}
        <div className="flex md:hidden items-center justify-center h-10 px-2 space-x-4 border-t border-gray-100 dark:border-[#30363D]/50">
          {renderShuffleButton('w-7 h-7', 'p-1')}
          {renderRepeatButton('w-7 h-7', 'p-1')}
          <button
            onClick={() => setShowLyrics(!showLyrics)}
            title={showLyrics ? 'Hide lyrics' : 'Show lyrics'}
            className={`p-1 rounded transition-colors ${
              showLyrics
                ? 'bg-[#FF1493]/10 text-[#FF1493]'
                : 'text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]'
            }`}
          >
            <img src={S54.player.lyrics} alt="Lyrics" className="w-7 h-7 object-contain" />
          </button>
          <button
            onClick={() => setShowQueue(prev => !prev)}
            title={showQueue ? 'Hide play queue' : 'Show play queue'}
            className={`p-1 rounded transition-colors relative ${
              showQueue
                ? 'bg-[#FF1493]/10 text-[#FF1493]'
                : 'text-gray-500 dark:text-[#8B949E] hover:text-gray-700 dark:hover:text-[#E6EDF3]'
            }`}
          >
            <img src={S54.player.playlist} alt="Queue" className="w-7 h-7 object-contain" />
            {queue.length > 0 && (
              <span className="absolute -top-0.5 -right-0.5 w-3.5 h-3.5 bg-[#FF1493] text-white text-[7px] font-bold rounded-full flex items-center justify-center">
                {queue.length}
              </span>
            )}
          </button>
        </div>
      </div>

      {showQueue && (
        <div className="fixed top-0 right-0 bottom-[10.5rem] md:bottom-28 lg:bottom-32 xl:bottom-40 w-full md:w-80 bg-white dark:bg-[#161B22] shadow-2xl border-l border-gray-200 dark:border-[#30363D] z-[55] overflow-hidden">
          {renderQueueList('100%', 'w-full')}
        </div>
      )}
    </>
  )
}

export default PersistentPlayer
