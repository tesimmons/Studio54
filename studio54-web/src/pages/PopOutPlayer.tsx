import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FiVolume2, FiVolume1, FiVolumeX, FiX, FiSave, FiCheck } from 'react-icons/fi'
import { usePlayer, type RepeatMode } from '../contexts/PlayerContext'
import { usePlayerBroadcast, POPOUT_STATE_KEY, POPUP_OPEN_FLAG_KEY, serializePlayerState, type BroadcastMessage } from '../hooks/usePlayerBroadcast'
import AddToPlaylistDropdown from '../components/AddToPlaylistDropdown'
import LyricsPanel from '../components/LyricsPanel'
import StarRating from '../components/StarRating'
import { tracksApi, playlistsApi, booksApi, bookProgressApi, nowPlayingApi } from '../api/client'
import toast from 'react-hot-toast'
import { Toaster } from 'react-hot-toast'
import { S54 } from '../assets/graphics'

function PopOutPlayer() {
  const { state, dispatch, audioRef, setRepeatMode, toggleShuffle, setVolume, toggleMute } = usePlayer()
  const { currentTrack, queue, isPlaying, repeatMode, shuffleMode, volume, isMuted } = state
  const queryClient = useQueryClient()

  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [showQueue, setShowQueue] = useState(false)
  const [showLyrics, setShowLyrics] = useState(false)
  const [savingQueue, setSavingQueue] = useState(false)
  const [queuePlaylistName, setQueuePlaylistName] = useState('')
  const saveQueueInputRef = useRef<HTMLInputElement>(null)
  const keepAliveRef = useRef<HTMLAudioElement>(null)
  const timeUpdateThrottleRef = useRef(0)

  // Read saved currentTime synchronously (state is already hydrated by PlayerProvider)
  const savedTimeRef = useRef(() => {
    try {
      const saved = localStorage.getItem(POPOUT_STATE_KEY)
      if (saved) return JSON.parse(saved).currentTime ?? 0
    } catch {}
    return 0
  })
  const initialSeekRef = useRef(savedTimeRef.current())

  const handleBroadcastMessage = useCallback((msg: BroadcastMessage) => {
    switch (msg.type) {
      case 'PING':
        broadcastSend({ type: 'PONG' })
        break
      case 'PLAY_PAUSE':
        if (msg.payload?.action === 'pause') {
          dispatch({ type: 'PAUSE' })
        } else {
          dispatch({ type: 'RESUME' })
        }
        break
      case 'SEEK':
        if (audioRef.current && msg.payload?.positionMs != null) {
          audioRef.current.currentTime = msg.payload.positionMs / 1000
        }
        break
      case 'VOLUME':
        if (msg.payload?.toggleMute) {
          dispatch({ type: 'TOGGLE_MUTE' })
        } else if (msg.payload?.volume != null) {
          dispatch({ type: 'SET_VOLUME', volume: msg.payload.volume })
        }
        break
      case 'NEXT':
        dispatch({ type: 'NEXT' })
        break
      case 'PREVIOUS':
        dispatch({ type: 'PREVIOUS' })
        break
      case 'PLAY_ALBUM':
        if (msg.payload) {
          dispatch({ type: 'PLAY_ALBUM', tracks: msg.payload.tracks, startIndex: msg.payload.startIndex })
        }
        break
      case 'PLAY_BOOK':
        if (msg.payload) {
          dispatch({ type: 'PLAY_BOOK', tracks: msg.payload.tracks, startIndex: msg.payload.startIndex, bookId: msg.payload.bookId })
        }
        break
      case 'ADD_TO_QUEUE':
        if (msg.payload?.track) {
          dispatch({ type: 'ADD_TO_QUEUE', track: msg.payload.track })
        }
        break
      case 'REPEAT_CHANGE':
        if (msg.payload?.mode) {
          dispatch({ type: 'SET_REPEAT', mode: msg.payload.mode })
        }
        break
      case 'SHUFFLE_CHANGE':
        dispatch({ type: 'TOGGLE_SHUFFLE' })
        break
      case 'CLOSE_PLAYER':
        // Save state and close
        saveStateAndClose()
        break
    }
  }, [])

  const { send: broadcastSend } = usePlayerBroadcast(handleBroadcastMessage)

  // Announce ready on mount and mark popup as open in localStorage so the main
  // window can detect it synchronously on reload (eliminating PING/PONG race).
  useEffect(() => {
    localStorage.setItem(POPUP_OPEN_FLAG_KEY, '1')
    broadcastSend({ type: 'POPOUT_READY' })
    return () => {
      localStorage.removeItem(POPUP_OPEN_FLAG_KEY)
    }
  }, [broadcastSend])

  // Save state periodically (every 5s)
  useEffect(() => {
    const interval = setInterval(() => {
      if (state.currentTrack) {
        const ct = audioRef.current?.currentTime ?? 0
        const serialized = serializePlayerState(state, ct)
        try {
          localStorage.setItem(POPOUT_STATE_KEY, JSON.stringify(serialized))
        } catch {}
      }
    }, 5000)
    return () => clearInterval(interval)
  }, [state])

  const saveStateAndClose = useCallback(() => {
    const ct = audioRef.current?.currentTime ?? 0
    const serialized = serializePlayerState(state, ct)
    try {
      localStorage.setItem(POPOUT_STATE_KEY, JSON.stringify(serialized))
    } catch {}
    localStorage.removeItem(POPUP_OPEN_FLAG_KEY)
    broadcastSend({ type: 'POPOUT_CLOSED' })
    window.close()
  }, [state, broadcastSend])

  // Handle beforeunload
  useEffect(() => {
    const handler = () => {
      const ct = audioRef.current?.currentTime ?? 0
      const serialized = serializePlayerState(state, ct)
      try {
        localStorage.setItem(POPOUT_STATE_KEY, JSON.stringify(serialized))
      } catch {}
      localStorage.removeItem(POPUP_OPEN_FLAG_KEY)
      broadcastSend({ type: 'POPOUT_CLOSED' })
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [state, broadcastSend])

  // Audio source management
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

  // Load audio when track changes
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    const src = getAudioSrc()
    if (src) {
      audio.src = src
      audio.load()
      const onCanPlay = () => {
        // On first load, seek to saved position
        if (initialSeekRef.current > 0) {
          audio.currentTime = initialSeekRef.current
          initialSeekRef.current = 0
        }
        if (isPlaying) {
          audio.play().catch((e) => console.warn('Playback failed:', e))
        }
        audio.removeEventListener('canplay', onCanPlay)
      }
      audio.addEventListener('canplay', onCanPlay)
    }
  }, [currentTrack?.id])

  // Play/pause sync
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !currentTrack) return
    if (isPlaying) {
      audio.play().catch(() => {})
    } else {
      audio.pause()
    }
  }, [isPlaying])

  // Volume sync
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.volume = isMuted ? 0 : volume
  }, [volume, isMuted])

  // iOS keepalive
  useEffect(() => {
    const keepAlive = keepAliveRef.current
    if (!keepAlive) return
    keepAlive.volume = 0.01
    keepAlive.loop = true
    if (isPlaying && currentTrack) {
      keepAlive.play().catch(() => {})
    } else {
      keepAlive.pause()
    }
  }, [isPlaying, currentTrack?.id])

  // Media Session API
  useEffect(() => {
    if (!('mediaSession' in navigator) || !currentTrack) return
    navigator.mediaSession.metadata = new MediaMetadata({
      title: currentTrack.title,
      artist: currentTrack.artist_name || '',
      album: currentTrack.album_title || '',
      artwork: currentTrack.album_cover_art_url
        ? [{ src: currentTrack.album_cover_art_url, sizes: '512x512', type: 'image/jpeg' }]
        : [],
    })
    navigator.mediaSession.setActionHandler('play', () => dispatch({ type: 'RESUME' }))
    navigator.mediaSession.setActionHandler('pause', () => dispatch({ type: 'PAUSE' }))
    navigator.mediaSession.setActionHandler('previoustrack', () => dispatch({ type: 'PREVIOUS' }))
    navigator.mediaSession.setActionHandler('nexttrack', () => dispatch({ type: 'NEXT' }))
    navigator.mediaSession.setActionHandler('seekto', (details) => {
      if (audioRef.current && details.seekTime != null) {
        audioRef.current.currentTime = details.seekTime
      }
    })
  }, [currentTrack?.id, currentTrack?.title])

  useEffect(() => {
    if ('mediaSession' in navigator) {
      navigator.mediaSession.playbackState = isPlaying ? 'playing' : 'paused'
    }
  }, [isPlaying])

  // Update document title
  useEffect(() => {
    if (currentTrack) {
      document.title = `Studio54 - ${currentTrack.title} - ${currentTrack.artist_name || 'Unknown Artist'}`
    } else {
      document.title = 'Studio54 - Player'
    }
  }, [currentTrack?.id, currentTrack?.title, currentTrack?.artist_name])

  // Send TIME_UPDATE to main window (throttled to 1/sec)
  // Send TRACK_CHANGE on track change
  const prevTrackIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (currentTrack?.id !== prevTrackIdRef.current) {
      prevTrackIdRef.current = currentTrack?.id ?? null
      const ct = audioRef.current?.currentTime ?? 0
      broadcastSend({ type: 'TRACK_CHANGE', payload: serializePlayerState(state, ct) })
    }
  }, [currentTrack?.id, state, broadcastSend])

  // Now Playing heartbeat
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null)
  useEffect(() => {
    const sendHeartbeat = () => {
      if (state.currentTrack && state.isPlaying) {
        const heartbeatData: any = {
          track_id: state.currentTrack.id,
          track_title: state.currentTrack.title,
          artist_name: state.currentTrack.artist_name || 'Unknown Artist',
          artist_id: state.currentTrack.artist_id,
          album_id: state.currentTrack.album_id,
          album_title: state.currentTrack.album_title,
          cover_art_url: state.currentTrack.album_cover_art_url,
        }
        if (state.bookId && state.chapterId) {
          heartbeatData.book_id = state.bookId
          heartbeatData.chapter_id = state.chapterId
          heartbeatData.position_ms = Math.round((audioRef.current?.currentTime ?? 0) * 1000)
        }
        nowPlayingApi.heartbeat(heartbeatData).catch(() => {})
      }
    }
    if (heartbeatRef.current) {
      clearInterval(heartbeatRef.current)
      heartbeatRef.current = null
    }
    if (state.currentTrack && state.isPlaying) {
      sendHeartbeat()
      heartbeatRef.current = setInterval(sendHeartbeat, 30000)
    }
    return () => {
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current)
        heartbeatRef.current = null
      }
    }
  }, [state.currentTrack?.id, state.isPlaying])

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
      dispatch({ type: 'NEXT' })
    }
  }, [repeatMode, currentTrack?.id, state.bookId, queue.length, dispatch])

  const handleTimeUpdate = () => {
    const audio = audioRef.current
    if (audio) {
      setCurrentTime(audio.currentTime)
      setDuration(audio.duration || 0)
      // Throttled broadcast
      const now = Date.now()
      if (now - timeUpdateThrottleRef.current > 1000) {
        timeUpdateThrottleRef.current = now
        broadcastSend({
          type: 'TIME_UPDATE',
          payload: { currentTime: audio.currentTime, duration: audio.duration || 0 }
        })
      }
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
    const nextMode = modes[(idx + 1) % modes.length]
    setRepeatMode(nextMode)
    broadcastSend({ type: 'REPEAT_CHANGE', payload: { mode: nextMode } })
  }

  const handleToggleShuffle = () => {
    toggleShuffle()
    broadcastSend({ type: 'SHUFFLE_CHANGE' })
  }

  const repeatLabel = repeatMode === 'one' ? '1' : repeatMode === 'all' ? 'All' : ''
  const VolumeIcon = isMuted || volume === 0 ? FiVolumeX : volume < 0.5 ? FiVolume1 : FiVolume2
  const isPreview = !currentTrack?.has_file && !currentTrack?.muse_file_id && currentTrack?.preview_url

  // Mini vs Expanded mode
  const isExpanded = showLyrics || showQueue

  // Resize window when switching modes
  useEffect(() => {
    try {
      if (isExpanded) {
        window.resizeTo(900, 650)
      } else {
        window.resizeTo(420, 250)
      }
    } catch {}
  }, [isExpanded])

  // Lyrics query
  const { data: lyricsData } = useQuery({
    queryKey: ['lyrics', currentTrack?.id],
    queryFn: () => tracksApi.getLyrics(currentTrack!.id),
    enabled: !!currentTrack?.id && showLyrics,
    staleTime: Infinity,
    retry: false,
  })

  // Track rating
  const isBookChapter = !!currentTrack?.isBookChapter
  const [trackRating, setTrackRating] = useState<number | null>(null)
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

  // Save queue as playlist
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

  // Shared UI pieces -------------------------------------------------------

  const albumArtEl = (size: 'sm' | 'lg') => (
    <div className={`rounded-xl overflow-hidden shadow-2xl bg-[#161B22] ${size === 'sm' ? 'w-16 h-16' : 'w-full aspect-square max-w-[280px]'}`}>
      <img
        src={currentTrack?.album_cover_art_url || S54.defaultAlbumArt}
        alt=""
        className="w-full h-full object-cover"
      />
    </div>
  )

  const progressBarEl = (
    <div className="flex items-center space-x-2">
      <span className="text-xs text-[#8B949E] w-10 text-right">{formatTime(currentTime)}</span>
      <input
        type="range"
        min={0}
        max={duration || 0}
        value={currentTime}
        onChange={handleSeek}
        className="flex-1 h-1 bg-[#30363D] rounded-full appearance-none cursor-pointer accent-[#FF1493]"
      />
      <span className="text-xs text-[#8B949E] w-10">{formatTime(duration)}</span>
    </div>
  )

  const transportEl = (compact = false) => (
    <div className={`flex items-center justify-center ${compact ? 'space-x-2' : 'space-x-4'}`}>
      <button onClick={() => dispatch({ type: 'PREVIOUS' })} title="Previous" className="p-1 text-[#8B949E] hover:text-white transition-colors">
        <img src={S54.player.rewind} alt="Previous" className={`${compact ? 'w-5 h-5' : 'w-7 h-7'} object-contain`} />
      </button>
      <button
        onClick={() => isPlaying ? dispatch({ type: 'PAUSE' }) : dispatch({ type: 'RESUME' })}
        title={isPlaying ? 'Pause' : 'Play'}
        className={`${compact ? 'w-10 h-10' : 'w-14 h-14'} rounded-full bg-[#FF1493] hover:bg-[#d10f7a] text-white flex items-center justify-center transition-colors`}
      >
        <img src={isPlaying ? S54.player.pause : S54.player.play} alt={isPlaying ? 'Pause' : 'Play'} className={`${compact ? 'w-5 h-5' : 'w-7 h-7'} object-contain brightness-0 invert`} />
      </button>
      <button onClick={() => dispatch({ type: 'NEXT' })} title="Next" className="p-1 text-[#8B949E] hover:text-white transition-colors">
        <img src={S54.player.fastForward} alt="Next" className={`${compact ? 'w-5 h-5' : 'w-7 h-7'} object-contain`} />
      </button>
    </div>
  )

  const utilityButtonsEl = (
    <div className="flex items-center space-x-1">
      <button onClick={handleToggleShuffle} title={`Shuffle: ${shuffleMode ? 'on' : 'off'}`} className={`p-1.5 rounded transition-colors ${shuffleMode ? 'bg-[#FF1493]/10 text-[#FF1493]' : 'text-[#8B949E] hover:text-white'}`}>
        <img src={S54.player.shuffle} alt="Shuffle" className="w-4 h-4 object-contain invert" />
      </button>
      <button onClick={cycleRepeat} title={`Repeat: ${repeatMode}`} className={`p-1.5 rounded transition-colors relative ${repeatMode !== 'off' ? 'bg-[#FF1493]/10 text-[#FF1493]' : 'text-[#8B949E] hover:text-white'}`}>
        <img src={S54.player.repeat} alt="Repeat" className="w-4 h-4 object-contain" />
        {repeatLabel && <span className="absolute -top-1 -right-1 text-[8px] font-bold text-[#FF1493]">{repeatLabel}</span>}
      </button>
      <button onClick={toggleMute} title={isMuted ? 'Unmute' : 'Mute'} className="p-1.5 text-[#8B949E] hover:text-white transition-colors">
        <VolumeIcon className="w-4 h-4" />
      </button>
      <button onClick={() => setShowLyrics(!showLyrics)} title={showLyrics ? 'Hide lyrics' : 'Show lyrics'} className={`p-1.5 rounded transition-colors ${showLyrics ? 'bg-[#FF1493]/10 text-[#FF1493]' : 'text-[#8B949E] hover:text-white'}`}>
        <img src={S54.player.lyrics} alt="Lyrics" className="w-4 h-4 object-contain" />
      </button>
      <button onClick={() => setShowQueue(!showQueue)} title={showQueue ? 'Hide queue' : 'Show queue'} className={`p-1.5 rounded transition-colors relative ${showQueue ? 'bg-[#FF1493]/10 text-[#FF1493]' : 'text-[#8B949E] hover:text-white'}`}>
        <img src={S54.player.playlist} alt="Queue" className="w-4 h-4 object-contain" />
        {queue.length > 0 && <span className="absolute -top-1 -right-1 w-3.5 h-3.5 bg-[#FF1493] text-white text-[7px] font-bold rounded-full flex items-center justify-center">{queue.length}</span>}
      </button>
    </div>
  )

  const volumeSliderEl = (
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
      className="w-24 h-1 bg-[#30363D] rounded-full appearance-none cursor-pointer accent-[#FF1493]"
      title={`Volume: ${Math.round((isMuted ? 0 : volume) * 100)}%`}
    />
  )

  const queuePanelEl = (maxH?: string) => (
    <div className="w-full bg-[#161B22] flex flex-col h-full rounded-lg border border-[#30363D]" style={{ maxHeight: maxH || '120px' }}>
      <div className="border-b border-[#30363D] flex-shrink-0">
        <div className="flex items-center justify-between px-3 py-2">
          <h3 className="text-xs font-semibold text-white">Queue ({queue.length})</h3>
          {queue.length > 0 && (
            <div className="flex items-center space-x-2">
              <button onClick={() => { setSavingQueue(true); setTimeout(() => saveQueueInputRef.current?.focus(), 0) }} className="text-[10px] text-[#8B949E] hover:text-[#FF1493] flex items-center" title="Save queue as playlist">
                <FiSave className="w-3 h-3 mr-0.5" /> Save
              </button>
              <button onClick={() => dispatch({ type: 'CLEAR_QUEUE' })} className="text-[10px] text-[#8B949E] hover:text-[#E6EDF3]" title="Clear queue">Clear</button>
            </div>
          )}
        </div>
        {savingQueue && (
          <div className="px-3 pb-2 flex items-center space-x-1">
            <input ref={saveQueueInputRef} type="text" value={queuePlaylistName} onChange={(e) => setQueuePlaylistName(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && queuePlaylistName.trim()) saveQueueMutation.mutate(queuePlaylistName.trim()); if (e.key === 'Escape') { setSavingQueue(false); setQueuePlaylistName('') } }}
              placeholder="Playlist name..." disabled={saveQueueMutation.isPending}
              className="flex-1 min-w-0 text-xs px-2 py-1 rounded border border-[#30363D] bg-[#0D1117] text-white placeholder-gray-400 focus:outline-none focus:border-[#FF1493]"
            />
            <button onClick={() => { const n = queuePlaylistName.trim(); if (n) saveQueueMutation.mutate(n) }} disabled={!queuePlaylistName.trim() || saveQueueMutation.isPending} className="p-0.5 text-[#FF1493] hover:text-[#d10f7a] disabled:opacity-40"><FiCheck className="w-3.5 h-3.5" /></button>
            <button onClick={() => { setSavingQueue(false); setQueuePlaylistName('') }} className="p-0.5 text-gray-400 hover:text-[#E6EDF3]"><FiX className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {queue.length === 0 ? (
          <p className="p-3 text-xs text-[#8B949E] text-center">Queue is empty</p>
        ) : (
          queue.map((track, index) => (
            <div key={`${track.id}-${index}`} className="flex items-center justify-between px-3 py-1.5 hover:bg-[#1C2128]">
              <div className="min-w-0 flex-1">
                <div className="text-xs text-white truncate">{track.title}</div>
                <div className="text-[10px] text-[#8B949E] truncate">{track.artist_name}</div>
              </div>
              <button onClick={() => dispatch({ type: 'REMOVE_FROM_QUEUE', index })} className="text-gray-400 hover:text-[#E6EDF3] ml-2" title="Remove"><FiX className="w-3.5 h-3.5" /></button>
            </div>
          ))
        )}
      </div>
    </div>
  )

  // -------------------------------------------------------------------------
  // No track state
  // -------------------------------------------------------------------------

  if (!currentTrack) {
    return (
      <div className="min-h-screen bg-[#0D1117] flex items-center justify-center">
        <div className="text-center">
          <img src={S54.logo} alt="Studio54" className="w-24 h-24 mx-auto mb-4 opacity-50" />
          <p className="text-[#8B949E]">No track playing</p>
        </div>
      </div>
    )
  }

  // -------------------------------------------------------------------------
  // MINI MODE (default — compact horizontal bar)
  // -------------------------------------------------------------------------

  if (!isExpanded) {
    return (
      <div className="h-screen bg-[#0D1117] text-white flex flex-col select-none overflow-hidden">
        <Toaster position="top-right" />
        <audio ref={audioRef} preload="auto" onTimeUpdate={handleTimeUpdate} onLoadedMetadata={handleTimeUpdate} onEnded={handleEnded}
          onError={(e) => { const audio = e.currentTarget; const err = audio.error; console.error('Audio error:', err?.code, err?.message, 'src:', audio.src) }} />
        <audio ref={keepAliveRef} src="/silence.mp3" preload="auto" />

        <div className="flex-1 flex flex-col p-3 gap-2">
          {/* Row 1: Art + Track info */}
          <div className="flex items-center gap-3">
            {albumArtEl('sm')}
            <div className="flex-1 min-w-0">
              <h2 className="text-sm font-bold text-white truncate">
                {currentTrack.title}
                {isPreview && <span className="ml-1 text-[10px] font-semibold bg-amber-900/40 text-amber-300 px-1 rounded">30s</span>}
              </h2>
              <p className="text-xs text-[#8B949E] truncate">{currentTrack.artist_name}</p>
            </div>
            {!isBookChapter && <StarRating rating={trackRating} onChange={(r) => ratingMutation.mutate(r)} size="sm" />}
          </div>

          {/* Row 2: Progress bar */}
          {progressBarEl}

          {/* Row 3: Transport + utility buttons */}
          <div className="flex items-center justify-between">
            {transportEl(true)}
            <div className="flex items-center gap-1">
              {volumeSliderEl}
              {utilityButtonsEl}
            </div>
          </div>
        </div>
      </div>
    )
  }

  // -------------------------------------------------------------------------
  // EXPANDED MODE (lyrics on right, playlist at bottom)
  // -------------------------------------------------------------------------

  return (
    <div className="h-screen bg-[#0D1117] text-white flex flex-col select-none overflow-hidden">
      <Toaster position="top-right" />
      <audio ref={audioRef} preload="auto" onTimeUpdate={handleTimeUpdate} onLoadedMetadata={handleTimeUpdate} onEnded={handleEnded}
        onError={(e) => { const audio = e.currentTarget; const err = audio.error; console.error('Audio error:', err?.code, err?.message, 'src:', audio.src) }} />
      <audio ref={keepAliveRef} src="/silence.mp3" preload="auto" />

      {/* Grid: left (art+controls) | right (lyrics) */}
      <div className="flex-1 grid overflow-hidden" style={{
        gridTemplate: showQueue
          ? '"left right" 1fr "bottom bottom" 140px / 45% 55%'
          : '"left right" 1fr / 45% 55%',
      }}>
        {/* LEFT column — art, info, controls */}
        <div className="flex flex-col p-4 overflow-y-auto" style={{ gridArea: 'left' }}>
          <div className="flex justify-center mb-3">
            {albumArtEl('lg')}
          </div>

          {/* Track info */}
          <div className="text-center mb-2">
            <h2 className="text-base font-bold text-white truncate">
              {currentTrack.title}
              {isPreview && <span className="ml-1 text-[10px] font-semibold bg-amber-900/40 text-amber-300 px-1 rounded">30s</span>}
            </h2>
            <p className="text-sm text-[#8B949E] truncate">{currentTrack.artist_name}</p>
            {currentTrack.album_title && <p className="text-xs text-[#484F58] truncate">{currentTrack.album_title}</p>}
            {!isBookChapter && (
              <div className="mt-1 flex justify-center">
                <StarRating rating={trackRating} onChange={(r) => ratingMutation.mutate(r)} size="sm" />
              </div>
            )}
          </div>

          {/* Progress bar */}
          {progressBarEl}

          {/* Transport controls */}
          <div className="mt-2">{transportEl(false)}</div>

          {/* Volume + utility */}
          <div className="flex items-center justify-center gap-2 mt-2">
            <VolumeIcon className="w-4 h-4 text-[#8B949E]" />
            {volumeSliderEl}
          </div>
          <div className="flex justify-center mt-2">
            {utilityButtonsEl}
            <AddToPlaylistDropdown trackId={currentTrack.id} />
          </div>
        </div>

        {/* RIGHT column — lyrics */}
        <div className="overflow-hidden border-l border-[#30363D]" style={{ gridArea: 'right' }}>
          {showLyrics ? (
            <LyricsPanel
              syncedLyrics={lyricsData?.synced_lyrics ?? null}
              plainLyrics={lyricsData?.plain_lyrics ?? null}
              currentTime={currentTime}
              onClose={() => setShowLyrics(false)}
              isFloating
            />
          ) : (
            <div className="flex items-center justify-center h-full text-[#484F58] text-sm">
              {showQueue ? 'Toggle lyrics to view here' : ''}
            </div>
          )}
        </div>

        {/* BOTTOM row — playlist (only when showQueue) */}
        {showQueue && (
          <div className="border-t border-[#30363D] overflow-hidden" style={{ gridArea: 'bottom' }}>
            {queuePanelEl('140px')}
          </div>
        )}
      </div>
    </div>
  )
}

export default PopOutPlayer
