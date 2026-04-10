import { createContext, useContext, useReducer, useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import { tracksApi, nowPlayingApi, bookProgressApi, bookPlaylistsApi } from '../api/client'
import type { BookPlaylistChapter } from '../types'
import { usePlayerBroadcast, serializePlayerState, POPOUT_STATE_KEY, POPUP_OPEN_FLAG_KEY, type BroadcastMessage, type SerializedPlayerState } from '../hooks/usePlayerBroadcast'
import { useAuth } from './AuthContext'

export interface PlayerTrack {
  id: string
  title: string
  track_number?: number
  duration_ms?: number | null
  has_file: boolean
  file_path?: string | null
  muse_file_id?: string | null
  preview_url?: string
  artist_name?: string
  artist_id?: string | null
  album_id?: string
  album_title?: string
  album_cover_art_url?: string | null
  /** True when this track is a book chapter (not a music track) */
  isBookChapter?: boolean
}

export type RepeatMode = 'off' | 'all' | 'one'

interface PlayerState {
  currentTrack: PlayerTrack | null
  queue: PlayerTrack[]
  history: PlayerTrack[]
  playHistory: PlayerTrack[]
  isPlaying: boolean
  repeatMode: RepeatMode
  shuffleMode: boolean
  volume: number
  isMuted: boolean
  bookId: string | null
  chapterId: string | null
}

type PlayerAction =
  | { type: 'PLAY'; track: PlayerTrack }
  | { type: 'PAUSE' }
  | { type: 'RESUME' }
  | { type: 'NEXT' }
  | { type: 'PREVIOUS' }
  | { type: 'ADD_TO_QUEUE'; track: PlayerTrack }
  | { type: 'REMOVE_FROM_QUEUE'; index: number }
  | { type: 'CLEAR_QUEUE' }
  | { type: 'PLAY_ALBUM'; tracks: PlayerTrack[]; startIndex: number }
  | { type: 'PLAY_BOOK'; tracks: PlayerTrack[]; startIndex: number; bookId: string }
  | { type: 'SET_REPEAT'; mode: RepeatMode }
  | { type: 'SET_VOLUME'; volume: number }
  | { type: 'TOGGLE_MUTE' }
  | { type: 'TOGGLE_SHUFFLE' }
  | { type: 'CLOSE_PLAYER' }
  | { type: 'RESTORE_STATE'; state: SerializedPlayerState }

function shuffleArray<T>(arr: T[]): T[] {
  const shuffled = [...arr]
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
  }
  return shuffled
}

function playerReducer(state: PlayerState, action: PlayerAction): PlayerState {
  switch (action.type) {
    case 'PLAY':
      return {
        ...state,
        currentTrack: action.track,
        isPlaying: true,
        history: state.currentTrack
          ? [state.currentTrack, ...state.history].slice(0, 50)
          : state.history,
        playHistory: state.currentTrack
          ? [...state.playHistory, state.currentTrack]
          : state.playHistory,
        bookId: null,
        chapterId: null,
      }
    case 'PAUSE':
      return { ...state, isPlaying: false }
    case 'RESUME':
      return { ...state, isPlaying: true }
    case 'NEXT': {
      if (state.repeatMode === 'one' && state.currentTrack) {
        return { ...state, isPlaying: true }
      }

      if (state.queue.length === 0) {
        if (state.repeatMode === 'all' && (state.playHistory.length > 0 || state.currentTrack)) {
          const allTracks = state.currentTrack
            ? [...state.playHistory, state.currentTrack]
            : [...state.playHistory]
          if (allTracks.length === 0) {
            return { ...state, currentTrack: null, isPlaying: false }
          }
          const ordered = state.shuffleMode ? shuffleArray(allTracks) : allTracks
          const [first, ...rest] = ordered
          return {
            ...state,
            currentTrack: first,
            queue: rest,
            playHistory: [],
            isPlaying: true,
            history: state.currentTrack
              ? [state.currentTrack, ...state.history].slice(0, 50)
              : state.history,
          }
        }
        return { ...state, currentTrack: null, isPlaying: false }
      }

      if (state.shuffleMode) {
        const randomIndex = Math.floor(Math.random() * state.queue.length)
        const nextTrack = state.queue[randomIndex]
        const restQueue = [...state.queue.slice(0, randomIndex), ...state.queue.slice(randomIndex + 1)]
        return {
          ...state,
          currentTrack: nextTrack,
          queue: restQueue,
          isPlaying: true,
          history: state.currentTrack
            ? [state.currentTrack, ...state.history].slice(0, 50)
            : state.history,
          playHistory: state.currentTrack
            ? [...state.playHistory, state.currentTrack]
            : state.playHistory,
        }
      }

      const [nextTrack, ...restQueue] = state.queue
      return {
        ...state,
        currentTrack: nextTrack,
        queue: restQueue,
        isPlaying: true,
        history: state.currentTrack
          ? [state.currentTrack, ...state.history].slice(0, 50)
          : state.history,
        playHistory: state.currentTrack
          ? [...state.playHistory, state.currentTrack]
          : state.playHistory,
        chapterId: state.bookId ? nextTrack.id : state.chapterId,
      }
    }
    case 'PREVIOUS': {
      if (state.history.length === 0) return state
      const [prevTrack, ...restHistory] = state.history
      return {
        ...state,
        currentTrack: prevTrack,
        history: restHistory,
        isPlaying: true,
        queue: state.currentTrack ? [state.currentTrack, ...state.queue] : state.queue,
        chapterId: state.bookId ? prevTrack.id : state.chapterId,
      }
    }
    case 'ADD_TO_QUEUE':
      return { ...state, queue: [...state.queue, action.track] }
    case 'REMOVE_FROM_QUEUE':
      return {
        ...state,
        queue: state.queue.filter((_, i) => i !== action.index),
      }
    case 'CLEAR_QUEUE':
      return { ...state, queue: [], playHistory: [] }
    case 'PLAY_ALBUM': {
      const tracksWithFile = action.tracks.filter(t => t.has_file)
      if (tracksWithFile.length === 0) return state
      const startIdx = Math.min(action.startIndex, tracksWithFile.length - 1)
      const remaining = tracksWithFile.slice(startIdx + 1)
      return {
        ...state,
        currentTrack: tracksWithFile[startIdx],
        queue: state.shuffleMode ? shuffleArray(remaining) : remaining,
        playHistory: [],
        isPlaying: true,
        history: state.currentTrack
          ? [state.currentTrack, ...state.history].slice(0, 50)
          : state.history,
        bookId: null,
        chapterId: null,
      }
    }
    case 'PLAY_BOOK': {
      const tracksWithFile = action.tracks.filter(t => t.has_file).map(t => ({ ...t, isBookChapter: true }))
      if (tracksWithFile.length === 0) return state
      const startIdx = Math.min(action.startIndex, tracksWithFile.length - 1)
      const remaining = tracksWithFile.slice(startIdx + 1)
      return {
        ...state,
        currentTrack: tracksWithFile[startIdx],
        queue: remaining,
        playHistory: [],
        isPlaying: true,
        shuffleMode: false,
        history: state.currentTrack
          ? [state.currentTrack, ...state.history].slice(0, 50)
          : state.history,
        bookId: action.bookId,
        chapterId: tracksWithFile[startIdx].id,
      }
    }
    case 'SET_REPEAT':
      return { ...state, repeatMode: action.mode }
    case 'SET_VOLUME': {
      const volume = Math.max(0, Math.min(1, action.volume))
      try { localStorage.setItem('studio54-player-volume', JSON.stringify({ volume, isMuted: state.isMuted })) } catch {}
      return { ...state, volume }
    }
    case 'TOGGLE_SHUFFLE': {
      const newShuffle = !state.shuffleMode
      return {
        ...state,
        shuffleMode: newShuffle,
        queue: newShuffle ? shuffleArray(state.queue) : state.queue,
      }
    }
    case 'TOGGLE_MUTE': {
      const isMuted = !state.isMuted
      try { localStorage.setItem('studio54-player-volume', JSON.stringify({ volume: state.volume, isMuted })) } catch {}
      return { ...state, isMuted }
    }
    case 'CLOSE_PLAYER':
      return { ...state, currentTrack: null, isPlaying: false, queue: [], playHistory: [], history: [], shuffleMode: false, bookId: null, chapterId: null }
    case 'RESTORE_STATE':
      return {
        ...state,
        currentTrack: action.state.currentTrack,
        queue: action.state.queue,
        history: action.state.history,
        playHistory: action.state.playHistory,
        isPlaying: action.state.isPlaying,
        repeatMode: action.state.repeatMode,
        shuffleMode: action.state.shuffleMode,
        volume: action.state.volume,
        isMuted: action.state.isMuted,
        bookId: action.state.bookId,
        chapterId: action.state.chapterId,
      }
    default:
      return state
  }
}

// Detect if we're in the pop-out player window (checked once at module load)
export const IS_POPOUT_WINDOW = window.location.pathname === '/player'

function loadVolumeState(): { volume: number; isMuted: boolean } {
  try {
    const saved = localStorage.getItem('studio54-player-volume')
    if (saved) {
      const data = JSON.parse(saved)
      return { volume: data.volume ?? 0.8, isMuted: data.isMuted ?? false }
    }
  } catch {}
  return { volume: 0.8, isMuted: false }
}

function loadInitialState(): PlayerState {
  const base: PlayerState = {
    currentTrack: null,
    queue: [],
    history: [],
    playHistory: [],
    isPlaying: false,
    repeatMode: 'off',
    shuffleMode: false,
    bookId: null,
    chapterId: null,
    ...loadVolumeState(),
  }

  // In the pop-out window, hydrate state from localStorage synchronously
  // so the first render already has track data (no flash of "No track playing")
  if (IS_POPOUT_WINDOW) {
    try {
      const saved = localStorage.getItem(POPOUT_STATE_KEY)
      if (saved) {
        const restored: SerializedPlayerState = JSON.parse(saved)
        return {
          ...base,
          currentTrack: restored.currentTrack,
          queue: restored.queue,
          history: restored.history,
          playHistory: restored.playHistory,
          isPlaying: restored.isPlaying,
          repeatMode: restored.repeatMode,
          shuffleMode: restored.shuffleMode,
          volume: restored.volume,
          isMuted: restored.isMuted,
          bookId: restored.bookId,
          chapterId: restored.chapterId,
        }
      }
    } catch {}
  }

  return base
}

// ---------------------------------------------------------------------------
// Per-user player state persistence
// ---------------------------------------------------------------------------

const PLAYER_STATE_PREFIX = 'studio54-player-state-'

function getPlayerStateKey(userId: string): string {
  return `${PLAYER_STATE_PREFIX}${userId}`
}

function loadPersistedState(userId: string): SerializedPlayerState | null {
  try {
    const saved = localStorage.getItem(getPlayerStateKey(userId))
    if (saved) return JSON.parse(saved)
  } catch {}
  return null
}

function savePlayerState(state: SerializedPlayerState, userId: string): void {
  try {
    localStorage.setItem(getPlayerStateKey(userId), JSON.stringify(state))
  } catch {}
}

function clearPlayerState(userId: string): void {
  try {
    localStorage.removeItem(getPlayerStateKey(userId))
  } catch {}
}

const initialState: PlayerState = loadInitialState()

interface PlayerContextValue {
  state: PlayerState
  play: (track: PlayerTrack) => void
  pause: () => void
  resume: () => void
  next: () => void
  previous: () => void
  addToQueue: (track: PlayerTrack) => void
  removeFromQueue: (index: number) => void
  clearQueue: () => void
  playAlbum: (tracks: PlayerTrack[], startIndex?: number) => void
  playBook: (tracks: PlayerTrack[], startIndex: number, bookId: string) => void
  seekTo: (positionMs: number) => void
  audioRef: React.RefObject<HTMLAudioElement>
  isPopOutOpen: boolean
  popOut: () => void
  closePopOut: () => void
  setRepeatMode: (mode: RepeatMode) => void
  toggleShuffle: () => void
  setVolume: (volume: number) => void
  toggleMute: () => void
  closePlayer: () => void
  dispatch: React.Dispatch<PlayerAction>
  popOutCurrentTime: number
  popOutDuration: number
}

const PlayerContext = createContext<PlayerContextValue | null>(null)

export function PlayerProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(playerReducer, initialState)
  const { user } = useAuth()
  // Initialize synchronously from localStorage so the main window knows immediately
  // on reload whether the popup is open — eliminates the PING/PONG race condition
  // that caused audio to play in both windows briefly after a reload.
  const [isPopOutOpen, setIsPopOutOpen] = useState(() => {
    if (IS_POPOUT_WINDOW) return false
    return localStorage.getItem(POPUP_OPEN_FLAG_KEY) === '1'
  })
  const popOutWindowRef = useRef<Window | null>(null)
  const [popOutCurrentTime, setPopOutCurrentTime] = useState(0)
  const [popOutDuration, setPopOutDuration] = useState(0)

  const handleBroadcastMessage = useCallback((msg: BroadcastMessage) => {
    switch (msg.type) {
      case 'PING':
        // Another window is asking if a pop-out exists — don't respond here
        // (only the pop-out page responds with PONG)
        break
      case 'PONG':
        // Pop-out window responded to our PING
        setIsPopOutOpen(true)
        break
      case 'POPOUT_READY':
        setIsPopOutOpen(true)
        break
      case 'POPOUT_CLOSED': {
        setIsPopOutOpen(false)
        popOutWindowRef.current = null
        // Restore state from the pop-out's last saved state
        try {
          const saved = localStorage.getItem(POPOUT_STATE_KEY)
          if (saved) {
            const restored: SerializedPlayerState = JSON.parse(saved)
            dispatch({ type: 'RESTORE_STATE', state: restored })
          }
        } catch {}
        break
      }
      case 'TRACK_CHANGE':
        // Pop-out changed track — sync our UI state
        if (msg.payload) {
          dispatch({ type: 'RESTORE_STATE', state: msg.payload })
        }
        break
      case 'TIME_UPDATE':
        // Pop-out sending time updates for UI display
        if (msg.payload) {
          setPopOutCurrentTime(msg.payload.currentTime ?? 0)
          setPopOutDuration(msg.payload.duration ?? 0)
        }
        break
    }
  }, [])

  const { send } = usePlayerBroadcast(handleBroadcastMessage)

  // On mount (main window only), check if a pop-out window already exists.
  // The pop-out must NOT send PING — it has two BroadcastChannel instances
  // (one here in PlayerProvider, one in PopOutPlayer) and they would cross-talk:
  // PlayerProvider sends PING → PopOutPlayer receives it → responds PONG →
  // PlayerProvider receives PONG → erroneously sets isPopOutOpen=true on itself,
  // causing all wrapped transport functions to broadcast instead of dispatch.
  useEffect(() => {
    if (IS_POPOUT_WINDOW) return
    send({ type: 'PING' })
  }, [send])

  // Poll popOutWindowRef to detect if pop-out was closed unexpectedly
  useEffect(() => {
    if (!isPopOutOpen) return
    const interval = setInterval(() => {
      if (popOutWindowRef.current && popOutWindowRef.current.closed) {
        setIsPopOutOpen(false)
        popOutWindowRef.current = null
        // Restore state
        try {
          const saved = localStorage.getItem(POPOUT_STATE_KEY)
          if (saved) {
            const restored: SerializedPlayerState = JSON.parse(saved)
            dispatch({ type: 'RESTORE_STATE', state: restored })
          }
        } catch {}
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [isPopOutOpen])

  const audioRef = useRef<HTMLAudioElement>(null!)

  const popOut = useCallback(() => {
    // Serialize current state with audio position
    const currentTime = audioRef.current?.currentTime ?? 0
    const serialized = serializePlayerState(state, currentTime)
    try {
      localStorage.setItem(POPOUT_STATE_KEY, JSON.stringify(serialized))
    } catch {}

    // Pause local audio
    if (audioRef.current) {
      audioRef.current.pause()
    }
    dispatch({ type: 'PAUSE' })

    // Open pop-out window
    const win = window.open(
      '/player',
      'studio54-player',
      'width=420,height=250,resizable=yes'
    )
    if (win) {
      popOutWindowRef.current = win
      setIsPopOutOpen(true)
    }
  }, [state])

  const closePopOut = useCallback(() => {
    send({ type: 'CLOSE_PLAYER' })
    // The pop-out will send POPOUT_CLOSED and save state before closing
  }, [send])

  // When pop-out is open, forward transport commands via BroadcastChannel
  const addToQueue = useCallback((track: PlayerTrack) => {
    if (isPopOutOpen) {
      send({ type: 'ADD_TO_QUEUE', payload: { track } })
    } else {
      dispatch({ type: 'ADD_TO_QUEUE', track })
      tracksApi.getLyrics(track.id).catch(() => {})
    }
  }, [isPopOutOpen, send])

  const playAlbum = useCallback((tracks: PlayerTrack[], startIndex = 0) => {
    if (isPopOutOpen) {
      send({ type: 'PLAY_ALBUM', payload: { tracks, startIndex } })
    } else {
      dispatch({ type: 'PLAY_ALBUM', tracks, startIndex })
      const tracksWithFile = tracks.filter(t => t.has_file)
      const effectiveStart = Math.min(startIndex, tracksWithFile.length - 1)
      tracksWithFile.forEach((track, i) => {
        if (i !== effectiveStart) {
          tracksApi.getLyrics(track.id).catch(() => {})
        }
      })
    }
  }, [isPopOutOpen, send])

  const playBook = useCallback((tracks: PlayerTrack[], startIndex: number, bookId: string) => {
    if (isPopOutOpen) {
      send({ type: 'PLAY_BOOK', payload: { tracks, startIndex, bookId } })
    } else {
      dispatch({ type: 'PLAY_BOOK', tracks, startIndex, bookId })
    }
  }, [isPopOutOpen, send])

  const pause = useCallback(() => {
    if (isPopOutOpen) {
      send({ type: 'PLAY_PAUSE', payload: { action: 'pause' } })
    } else {
      dispatch({ type: 'PAUSE' })
    }
  }, [isPopOutOpen, send])

  const resume = useCallback(() => {
    if (isPopOutOpen) {
      send({ type: 'PLAY_PAUSE', payload: { action: 'resume' } })
    } else {
      dispatch({ type: 'RESUME' })
    }
  }, [isPopOutOpen, send])

  const next = useCallback(() => {
    if (isPopOutOpen) {
      send({ type: 'NEXT' })
    } else {
      dispatch({ type: 'NEXT' })
    }
  }, [isPopOutOpen, send])

  const previous = useCallback(() => {
    if (isPopOutOpen) {
      send({ type: 'PREVIOUS' })
    } else {
      dispatch({ type: 'PREVIOUS' })
    }
  }, [isPopOutOpen, send])

  const seekTo = useCallback((positionMs: number) => {
    if (isPopOutOpen) {
      send({ type: 'SEEK', payload: { positionMs } })
    } else if (audioRef.current) {
      audioRef.current.currentTime = positionMs / 1000
    }
  }, [isPopOutOpen, send])

  const setRepeatMode = useCallback((mode: RepeatMode) => {
    if (isPopOutOpen) {
      send({ type: 'REPEAT_CHANGE', payload: { mode } })
    }
    dispatch({ type: 'SET_REPEAT', mode })
  }, [isPopOutOpen, send])

  const toggleShuffle = useCallback(() => {
    if (isPopOutOpen) {
      send({ type: 'SHUFFLE_CHANGE' })
    }
    dispatch({ type: 'TOGGLE_SHUFFLE' })
  }, [isPopOutOpen, send])

  const setVolume = useCallback((volume: number) => {
    if (isPopOutOpen) {
      send({ type: 'VOLUME', payload: { volume } })
    }
    dispatch({ type: 'SET_VOLUME', volume })
  }, [isPopOutOpen, send])

  const toggleMute = useCallback(() => {
    // Sync to pop-out via volume message
    if (isPopOutOpen) {
      send({ type: 'VOLUME', payload: { toggleMute: true } })
    }
    dispatch({ type: 'TOGGLE_MUTE' })
  }, [isPopOutOpen, send])

  const closePlayer = useCallback(() => {
    if (isPopOutOpen) {
      send({ type: 'CLOSE_PLAYER' })
    }
    dispatch({ type: 'CLOSE_PLAYER' })
  }, [isPopOutOpen, send])

  const value: PlayerContextValue = {
    state,
    play: (track) => dispatch({ type: 'PLAY', track }),
    pause,
    resume,
    next,
    previous,
    addToQueue,
    removeFromQueue: (index) => dispatch({ type: 'REMOVE_FROM_QUEUE', index }),
    clearQueue: () => dispatch({ type: 'CLEAR_QUEUE' }),
    playAlbum,
    playBook,
    seekTo,
    audioRef,
    isPopOutOpen,
    popOut,
    closePopOut,
    setRepeatMode,
    toggleShuffle,
    setVolume,
    toggleMute,
    closePlayer,
    dispatch,
    popOutCurrentTime,
    popOutDuration,
  }

  // ---------------------------------------------------------------------------
  // Per-user player state persistence (save/restore)
  // ---------------------------------------------------------------------------

  // Hydrate from saved state on mount (main window only, not pop-out)
  const hasHydratedRef = useRef(false)
  useEffect(() => {
    if (IS_POPOUT_WINDOW || hasHydratedRef.current || !user?.id) return
    hasHydratedRef.current = true

    const saved = loadPersistedState(user.id)
    if (saved && saved.currentTrack) {
      dispatch({ type: 'RESTORE_STATE', state: saved })

      // For audiobooks, check if server-side BookProgress is more recent
      if (saved.bookId && saved.chapterId) {
        bookProgressApi.get(saved.bookId).then((progress) => {
          if (progress && progress.position_ms != null) {
            const savedMs = (saved.currentTime || 0) * 1000
            if (progress.position_ms > savedMs) {
              // Server has more recent position — update currentTime
              // We store this so the audio element can seek to it once loaded
              const updatedState = { ...saved, currentTime: progress.position_ms / 1000 }
              savePlayerState(updatedState, user.id)
            }
          }
        }).catch(() => {})
      }
    }
  }, [user?.id])

  // Debounced save of player state
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (IS_POPOUT_WINDOW || !user?.id) return

    // Clear on CLOSE_PLAYER (no current track)
    if (!state.currentTrack) {
      clearPlayerState(user.id)
      return
    }

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      const currentTime = audioRef.current?.currentTime ?? 0
      const serialized = serializePlayerState(state, currentTime)
      savePlayerState(serialized, user.id)
    }, 500)

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [
    state.currentTrack?.id,
    state.isPlaying,
    state.queue.length,
    state.repeatMode,
    state.shuffleMode,
    state.volume,
    state.isMuted,
    state.bookId,
    user?.id,
  ])

  // Also save periodically while playing (to capture currentTime)
  useEffect(() => {
    if (IS_POPOUT_WINDOW || !user?.id || !state.currentTrack || !state.isPlaying) return
    const interval = setInterval(() => {
      const currentTime = audioRef.current?.currentTime ?? 0
      const serialized = serializePlayerState(state, currentTime)
      savePlayerState(serialized, user.id)
    }, 5000)
    return () => clearInterval(interval)
  }, [state.currentTrack?.id, state.isPlaying, user?.id])

  // ---------------------------------------------------------------------------
  // Server-side book progress sync
  // ---------------------------------------------------------------------------

  const lastServerSaveRef = useRef<number>(0)
  const prevIsPlayingRef = useRef<boolean>(state.isPlaying)
  const prevChapterIdRef = useRef<string | null>(state.chapterId)
  const prevBookIdRef = useRef<string | null>(state.bookId)

  const saveBookProgressToServer = useCallback(() => {
    if (IS_POPOUT_WINDOW) return
    if (!state.bookId || !state.chapterId) return
    const now = Date.now()
    if (now - lastServerSaveRef.current < 5000) return
    lastServerSaveRef.current = now
    const positionMs = Math.round((audioRef.current?.currentTime ?? 0) * 1000)
    bookProgressApi.upsert(state.bookId, {
      chapter_id: state.chapterId,
      position_ms: positionMs,
    }).catch(() => {})
  }, [state.bookId, state.chapterId])

  // Periodic server save every 30s while an audiobook is playing
  useEffect(() => {
    if (IS_POPOUT_WINDOW || !state.bookId || !state.chapterId || !state.isPlaying) return
    const interval = setInterval(saveBookProgressToServer, 30000)
    return () => clearInterval(interval)
  }, [state.bookId, state.chapterId, state.isPlaying, saveBookProgressToServer])

  // Save on pause (isPlaying transitions from true to false)
  useEffect(() => {
    if (IS_POPOUT_WINDOW) {
      prevIsPlayingRef.current = state.isPlaying
      return
    }
    if (prevIsPlayingRef.current && !state.isPlaying && state.bookId && state.chapterId) {
      // Force save by resetting the throttle
      lastServerSaveRef.current = 0
      saveBookProgressToServer()
    }
    prevIsPlayingRef.current = state.isPlaying
  }, [state.isPlaying, state.bookId, state.chapterId, saveBookProgressToServer])

  // Save on chapter change
  useEffect(() => {
    if (IS_POPOUT_WINDOW) {
      prevChapterIdRef.current = state.chapterId
      return
    }
    if (prevChapterIdRef.current && prevChapterIdRef.current !== state.chapterId && state.bookId && state.chapterId) {
      lastServerSaveRef.current = 0
      saveBookProgressToServer()
    }
    prevChapterIdRef.current = state.chapterId
  }, [state.chapterId, state.bookId, saveBookProgressToServer])

  // Save on player close (bookId goes from set to null)
  useEffect(() => {
    if (IS_POPOUT_WINDOW) {
      prevBookIdRef.current = state.bookId
      return
    }
    if (prevBookIdRef.current && !state.bookId) {
      // Book was playing and player was closed - save last known position
      const positionMs = Math.round((audioRef.current?.currentTime ?? 0) * 1000)
      bookProgressApi.upsert(prevBookIdRef.current, {
        chapter_id: prevChapterIdRef.current || state.chapterId || '',
        position_ms: positionMs,
      }).catch(() => {})
    }
    prevBookIdRef.current = state.bookId
  }, [state.bookId])

  // Flush book progress on logout (user goes truthy→null)
  const prevUserRef = useRef<typeof user>(user)
  useEffect(() => {
    if (IS_POPOUT_WINDOW) {
      prevUserRef.current = user
      return
    }
    if (prevUserRef.current && !user && state.bookId && state.chapterId) {
      const positionMs = Math.round((audioRef.current?.currentTime ?? 0) * 1000)
      bookProgressApi.upsert(state.bookId, {
        chapter_id: state.chapterId,
        position_ms: positionMs,
      }).catch(() => {})
    }
    prevUserRef.current = user
  }, [user])

  // ---------------------------------------------------------------------------
  // play-book-playlist event listener (series "Play" button)
  // ---------------------------------------------------------------------------
  useEffect(() => {
    if (IS_POPOUT_WINDOW) return

    const handlePlayBookPlaylist = async (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (!detail?.playlistId) return

      try {
        const playlist = await bookPlaylistsApi.get(detail.seriesId)
        if (!playlist?.chapters?.length) return

        // Map chapters to PlayerTrack[]
        const tracks: PlayerTrack[] = playlist.chapters
          .filter((ch: BookPlaylistChapter) => ch.has_file && ch.file_path)
          .map((ch: BookPlaylistChapter) => ({
            id: ch.chapter_id,
            title: ch.chapter_title,
            track_number: ch.chapter_number ?? undefined,
            duration_ms: ch.duration_ms,
            has_file: true,
            file_path: ch.file_path,
            artist_name: playlist.series_name || playlist.name || undefined,
            album_title: ch.book_title || undefined,
            album_cover_art_url: ch.book_cover_art_url || undefined,
            isBookChapter: true,
          }))

        if (tracks.length === 0) return

        // Determine the bookId from the first chapter
        const firstBookId = playlist.chapters.find((ch: BookPlaylistChapter) => ch.book_id)?.book_id
        if (firstBookId) {
          dispatch({ type: 'PLAY_BOOK', tracks, startIndex: 0, bookId: firstBookId })
        } else {
          dispatch({ type: 'PLAY_ALBUM', tracks, startIndex: 0 })
        }
      } catch (err) {
        console.error('Failed to play book playlist:', err)
      }
    }

    window.addEventListener('play-book-playlist', handlePlayBookPlaylist)
    return () => window.removeEventListener('play-book-playlist', handlePlayBookPlaylist)
  }, [])

  // Now Playing heartbeat: send every 30s while playing, clear on pause/stop
  // Skip when pop-out is active (it sends its own heartbeats)
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (isPopOutOpen) {
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current)
        heartbeatRef.current = null
      }
      return
    }

    const sendHeartbeat = () => {
      if (state.currentTrack && state.isPlaying) {
        const heartbeatData: Parameters<typeof nowPlayingApi.heartbeat>[0] = {
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
    } else {
      nowPlayingApi.clearHeartbeat().catch(() => {})
    }

    return () => {
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current)
        heartbeatRef.current = null
      }
    }
  }, [state.currentTrack?.id, state.isPlaying, isPopOutOpen])

  return (
    <PlayerContext.Provider value={value}>
      {children}
    </PlayerContext.Provider>
  )
}

export function usePlayer() {
  const context = useContext(PlayerContext)
  if (!context) {
    throw new Error('usePlayer must be used within a PlayerProvider')
  }
  return context
}
