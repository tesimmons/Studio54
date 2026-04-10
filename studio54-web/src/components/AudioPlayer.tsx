/**
 * Audio Player Component
 * Simple audio playback for music files from MUSE
 */

import AudioPlayerLib from 'react-h5-audio-player'
import 'react-h5-audio-player/lib/styles.css'
import { useState, useEffect } from 'react'

interface Track {
  id: string
  title: string
  track_number?: number
  has_file?: boolean
  muse_file_id?: string | null
  artist_name?: string
}

interface AudioPlayerProps {
  track: Track | null
  onEnded?: () => void
}

export default function AudioPlayer({ track, onEnded }: AudioPlayerProps) {
  const [audioSrc, setAudioSrc] = useState<string | null>(null)

  useEffect(() => {
    // Use Studio54 streaming endpoint if track has a file linked
    if (track?.id && track?.has_file) {
      const studio54Url = (import.meta as any).env?.VITE_API_URL || '/api/v1'
      const authToken = localStorage.getItem('studio54_token')
      const tokenParam = authToken ? `?token=${encodeURIComponent(authToken)}` : ''
      setAudioSrc(`${studio54Url}/tracks/${track.id}/stream${tokenParam}`)
    } else if (track?.muse_file_id) {
      // Fallback to MUSE streaming if muse_file_id is available
      const museUrl = (import.meta as any).env?.VITE_MUSE_API_URL || 'http://localhost:8007'
      setAudioSrc(`${museUrl}/api/v1/files/${track.muse_file_id}/stream`)
    } else {
      setAudioSrc(null)
    }
  }, [track])

  if (!track || !audioSrc) {
    return (
      <div className="card p-6 text-center">
        <p className="text-gray-500 dark:text-gray-400">
          Select a track to play
        </p>
      </div>
    )
  }

  return (
    <div className="card p-4">
      <div className="mb-3">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
          {track.track_number && `${track.track_number}. `}
          {track.title}
        </h3>
        {track.artist_name && (
          <p className="text-sm text-gray-600 dark:text-gray-400">{track.artist_name}</p>
        )}
      </div>
      <AudioPlayerLib
        src={audioSrc}
        autoPlay={false}
        showJumpControls={true}
        onEnded={onEnded}
        className="rounded-lg"
      />
    </div>
  )
}
