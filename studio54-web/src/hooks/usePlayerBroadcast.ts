import { useEffect, useRef, useCallback } from 'react'
import type { PlayerTrack, RepeatMode } from '../contexts/PlayerContext'

const CHANNEL_NAME = 'studio54-player-channel'
export const POPOUT_STATE_KEY = 'studio54-player-popout-state'
// Synchronous flag written by the popup on open/close so the main window can
// read it immediately on load — eliminates the PING/PONG race condition.
export const POPUP_OPEN_FLAG_KEY = 'studio54-player-popup-open'

export interface SerializedPlayerState {
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
  currentTime: number
}

export type BroadcastMessageType =
  | 'PING'
  | 'PONG'
  | 'POPOUT_READY'
  | 'POPOUT_CLOSED'
  | 'STATE_TRANSFER'
  | 'PLAY_PAUSE'
  | 'SEEK'
  | 'VOLUME'
  | 'NEXT'
  | 'PREVIOUS'
  | 'TRACK_CHANGE'
  | 'TIME_UPDATE'
  | 'PLAY_ALBUM'
  | 'PLAY_BOOK'
  | 'ADD_TO_QUEUE'
  | 'CLOSE_PLAYER'
  | 'REPEAT_CHANGE'
  | 'SHUFFLE_CHANGE'

export interface BroadcastMessage {
  type: BroadcastMessageType
  payload?: any
}

export function usePlayerBroadcast(onMessage: (msg: BroadcastMessage) => void) {
  const channelRef = useRef<BroadcastChannel | null>(null)

  useEffect(() => {
    const channel = new BroadcastChannel(CHANNEL_NAME)
    channelRef.current = channel

    channel.onmessage = (event: MessageEvent<BroadcastMessage>) => {
      onMessage(event.data)
    }

    return () => {
      channel.close()
      channelRef.current = null
    }
  }, [onMessage])

  const send = useCallback((msg: BroadcastMessage) => {
    channelRef.current?.postMessage(msg)
  }, [])

  return { send }
}

export function serializePlayerState(
  state: {
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
  },
  currentTime: number
): SerializedPlayerState {
  return {
    currentTrack: state.currentTrack,
    queue: state.queue,
    history: state.history,
    playHistory: state.playHistory,
    isPlaying: state.isPlaying,
    repeatMode: state.repeatMode,
    shuffleMode: state.shuffleMode,
    volume: state.volume,
    isMuted: state.isMuted,
    bookId: state.bookId,
    chapterId: state.chapterId,
    currentTime,
  }
}
