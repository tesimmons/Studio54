import { useEffect, useRef, useMemo } from 'react'
import { FiX } from 'react-icons/fi'

interface LyricLine {
  time: number
  text: string
}

function parseLRC(lrc: string): LyricLine[] {
  const lines: LyricLine[] = []
  const regex = /\[(\d{2}):(\d{2})\.(\d{2,3})\]\s*(.*)/

  for (const raw of lrc.split('\n')) {
    const match = raw.match(regex)
    if (match) {
      const minutes = parseInt(match[1], 10)
      const seconds = parseInt(match[2], 10)
      const centiseconds = parseInt(match[3].padEnd(3, '0'), 10)
      const time = minutes * 60 + seconds + centiseconds / 1000
      const text = match[4].trim()
      if (text) {
        lines.push({ time, text })
      }
    }
  }

  return lines.sort((a, b) => a.time - b.time)
}

function findCurrentLineIndex(lines: LyricLine[], currentTime: number): number {
  let idx = -1
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].time <= currentTime) {
      idx = i
    } else {
      break
    }
  }
  return idx
}

interface LyricsPanelProps {
  syncedLyrics: string | null
  plainLyrics: string | null
  currentTime: number
  onClose: () => void
  isFloating?: boolean
  queueOpen?: boolean
}

export default function LyricsPanel({
  syncedLyrics,
  plainLyrics,
  currentTime,
  onClose,
  isFloating = false,
  queueOpen = false,
}: LyricsPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const activeLineRef = useRef<HTMLDivElement>(null)

  const parsedLines = useMemo(
    () => (syncedLyrics ? parseLRC(syncedLyrics) : []),
    [syncedLyrics]
  )

  const currentLineIndex = syncedLyrics
    ? findCurrentLineIndex(parsedLines, currentTime)
    : -1

  // Auto-scroll to active line
  useEffect(() => {
    if (activeLineRef.current && containerRef.current) {
      activeLineRef.current.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
    }
  }, [currentLineIndex])

  const hasSynced = parsedLines.length > 0

  if (isFloating) {
    return (
      <div className="px-3 pb-3 border-t border-gray-200 dark:border-[#30363D]">
        <div className="flex items-center justify-between py-2">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            Lyrics
          </span>
          <button
            onClick={onClose}
            className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
          >
            <FiX className="w-3.5 h-3.5" />
          </button>
        </div>
        <div
          ref={containerRef}
          className="max-h-48 overflow-y-auto scrollbar-thin"
        >
          {hasSynced ? (
            <div className="space-y-1 py-2">
              {parsedLines.map((line, i) => (
                <div
                  key={i}
                  ref={i === currentLineIndex ? activeLineRef : null}
                  className={`transition-all duration-300 ${
                    i === currentLineIndex
                      ? 'text-xl font-semibold text-[#FF1493] dark:text-[#ff4da6]'
                      : 'text-base text-gray-400 dark:text-gray-500'
                  }`}
                >
                  {line.text}
                </div>
              ))}
            </div>
          ) : plainLyrics ? (
            <pre className="text-base text-gray-500 dark:text-gray-400 whitespace-pre-wrap font-sans leading-relaxed py-2">
              {plainLyrics}
            </pre>
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-4">
              No lyrics found
            </p>
          )}
        </div>
      </div>
    )
  }

  // Docked panel: slides up from the bottom bar
  return (
    <div className="fixed bottom-32 md:bottom-40 left-0 z-40 flex justify-center pointer-events-none" style={{ right: queueOpen ? '20rem' : '0' }}>
      <div className="w-full max-w-lg mx-4 pointer-events-auto bg-white/95 dark:bg-[#161B22]/95 backdrop-blur-sm rounded-t-2xl shadow-2xl border border-gray-200 dark:border-[#30363D] border-b-0 flex flex-col max-h-[60vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-[#30363D] flex-shrink-0">
          <span className="text-sm font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wide">
            Lyrics
          </span>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 rounded-lg hover:bg-gray-100 dark:hover:bg-[#1C2128] transition-colors"
          >
            <FiX className="w-4 h-4" />
          </button>
        </div>

        {/* Lyrics content */}
        <div
          ref={containerRef}
          className="flex-1 overflow-y-auto px-5 scrollbar-thin"
        >
          {hasSynced ? (
            <div className="space-y-3 py-6">
              {parsedLines.map((line, i) => (
                <div
                  key={i}
                  ref={i === currentLineIndex ? activeLineRef : null}
                  className={`transition-all duration-300 text-center ${
                    i === currentLineIndex
                      ? 'text-4xl font-bold text-gray-900 dark:text-white scale-105'
                      : Math.abs(i - currentLineIndex) === 1
                      ? 'text-2xl text-gray-500 dark:text-gray-400'
                      : 'text-xl text-gray-300 dark:text-gray-600'
                  }`}
                >
                  {line.text}
                </div>
              ))}
            </div>
          ) : plainLyrics ? (
            <pre className="text-xl text-gray-600 dark:text-gray-400 whitespace-pre-wrap font-sans leading-relaxed py-6 text-center">
              {plainLyrics}
            </pre>
          ) : (
            <div className="flex items-center justify-center py-12">
              <p className="text-sm text-gray-400 dark:text-gray-500">
                No lyrics found for this track
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
