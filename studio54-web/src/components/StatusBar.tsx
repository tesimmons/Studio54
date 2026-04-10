interface StatusBarProps {
  isMonitored: boolean
  linkedFiles: number
  totalTracks: number
  albumCount?: number
  size?: 'sm' | 'md'
  showText?: boolean
}

function getStatusInfo(isMonitored: boolean, linkedFiles: number, totalTracks: number, albumCount?: number) {
  // If there are albums but no tracks synced yet, show a "needs sync" state
  if (totalTracks === 0 && (albumCount || 0) > 0) {
    return { color: '#F59E0B', label: `${albumCount} albums (not synced)`, percent: 0, isFaded: true }
  }
  if (totalTracks === 0) {
    return { color: '#9CA3AF', label: 'No Tracks', percent: 0, isFaded: true }
  }
  if (!isMonitored) {
    // Still show linked progress even when unmonitored
    const percent = Math.round((linkedFiles / totalTracks) * 100)
    if (percent > 0) {
      return { color: '#A855F7', label: `${linkedFiles}/${totalTracks} linked`, percent, isFaded: false }
    }
    return { color: '#A855F7', label: 'Unmonitored', percent: 0, isFaded: true }
  }
  const percent = Math.round((linkedFiles / totalTracks) * 100)
  if (percent === 0) {
    return { color: '#EF4444', label: 'No Files', percent: 0, isFaded: true }
  }
  if (percent < 25) {
    return { color: '#F97316', label: `${linkedFiles}/${totalTracks} linked`, percent, isFaded: false }
  }
  if (percent < 75) {
    return { color: '#F59E0B', label: `${linkedFiles}/${totalTracks} linked`, percent, isFaded: false }
  }
  if (percent < 100) {
    return { color: '#84CC16', label: `${linkedFiles}/${totalTracks} linked`, percent, isFaded: false }
  }
  return { color: '#22C55E', label: 'Complete', percent: 100, isFaded: false }
}

function StatusBar({ isMonitored, linkedFiles, totalTracks, albumCount, size = 'sm', showText = false }: StatusBarProps) {
  const { color, label, percent, isFaded } = getStatusInfo(isMonitored, linkedFiles, totalTracks, albumCount)
  const barHeight = size === 'sm' ? 'h-1' : 'h-1.5'

  return (
    <div>
      <div className={`w-full ${barHeight} bg-gray-200 dark:bg-[#0D1117] rounded-full overflow-hidden`}>
        <div
          className={`${barHeight} rounded-full transition-all duration-300`}
          style={{
            width: `${Math.max(percent, isFaded ? 100 : percent)}%`,
            backgroundColor: color,
            opacity: isFaded ? 0.4 : 1,
          }}
        />
      </div>
      {showText && (
        <span className="text-[10px] mt-0.5 block" style={{ color }}>
          {label}
        </span>
      )}
    </div>
  )
}

export default StatusBar
