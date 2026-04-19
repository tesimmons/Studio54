import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { systemApi } from '../../../api/client'
import { FiUsers, FiDisc, FiLink, FiCheckCircle, FiMusic, FiHardDrive, FiBookOpen, FiBook, FiSettings } from 'react-icons/fi'
import type { SystemStats } from '../../../types'

interface StatisticsData {
  artists: { total: number; monitored: number }
  albums: { total: number; status_breakdown: Record<string, number> }
  tracks: { total: number; with_files: number; file_percent: number }
  library: {
    total_files: number
    total_size_bytes: number
    total_size: string
    format_distribution: Array<{ format: string; count: number }>
    musicbrainz_coverage: {
      tracks_tagged: number
      albums_tagged: number
      files_linked: number
      coverage_percent: number
    }
  }
}

const WIDGET_CONFIG: Record<string, {
  title: string
  icon: React.ReactNode
  color: 'primary' | 'success' | 'warning' | 'danger'
  source: 'statistics' | 'systemStats'
  getValue: (stats: StatisticsData | null, sysStats: SystemStats | null) => number | string
  getSubtitle: (stats: StatisticsData | null, sysStats: SystemStats | null) => string
  getLink?: () => string
}> = {
  'total-artists': {
    title: 'Total Artists',
    icon: <FiUsers className="w-6 h-6" />,
    color: 'primary',
    source: 'statistics',
    getValue: (s) => s?.artists.total || 0,
    getSubtitle: (s) => `${s?.artists.monitored || 0} monitored`,
    getLink: () => '/disco-lounge',
  },
  'monitored-albums': {
    title: 'Monitored Albums',
    icon: <FiDisc className="w-6 h-6" />,
    color: 'primary',
    source: 'systemStats',
    getValue: (_, sys) => sys?.monitored_albums || 0,
    getSubtitle: (_, sys) => `${sys?.total_albums || 0} total`,
    getLink: () => '/disco-lounge?monitored=true',
  },
  'wanted-albums': {
    title: 'Linked Albums',
    icon: <FiLink className="w-6 h-6" />,
    color: 'success',
    source: 'systemStats',
    getValue: (_, sys) => sys?.linked_albums || 0,
    getSubtitle: (_, sys) => `${sys?.total_albums || 0} total albums`,
  },
  'downloaded': {
    title: 'Downloaded',
    icon: <FiCheckCircle className="w-6 h-6" />,
    color: 'success',
    source: 'systemStats',
    getValue: (_, sys) => sys?.downloaded_albums || 0,
    getSubtitle: (_, sys) => sys?.total_download_size || '0 B',
    getLink: () => '/activity?tab=downloads',
  },
  'tracks': {
    title: 'Tracks',
    icon: <FiMusic className="w-6 h-6" />,
    color: 'primary',
    source: 'systemStats',
    getValue: (_, sys) => sys?.linked_tracks || 0,
    getSubtitle: (_, sys) => `${(sys?.total_tracks || 0).toLocaleString()} unique tracks`,
  },
  'library-size': {
    title: 'Library Size',
    icon: <FiHardDrive className="w-6 h-6" />,
    color: 'warning',
    source: 'statistics',
    getValue: (s) => s?.library.total_size || '0 B',
    getSubtitle: (s) => `${(s?.library.total_files || 0).toLocaleString()} files`,
  },
  'total-authors': {
    title: 'Total Authors',
    icon: <FiBookOpen className="w-6 h-6" />,
    color: 'primary',
    source: 'systemStats',
    getValue: (_, sys) => sys?.total_authors || 0,
    getSubtitle: (_, sys) => `${sys?.monitored_authors || 0} monitored`,
    getLink: () => '/reading-room',
  },
  'total-books': {
    title: 'Books',
    icon: <FiBook className="w-6 h-6" />,
    color: 'primary',
    source: 'systemStats',
    getValue: (_, sys) => sys?.total_books || 0,
    getSubtitle: (_, sys) => `${sys?.downloaded_books || 0} downloaded`,
    getLink: () => '/reading-room',
  },
}

const colorClasses = {
  primary: 'bg-[#FF1493]/5 dark:bg-[#FF1493]/10 text-[#FF1493] dark:text-[#ff4da6]',
  success: 'bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400',
  warning: 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-600 dark:text-yellow-400',
  danger: 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400',
}

type LibrarySizeScope = 'music' | 'audiobook' | 'all'

const LIBRARY_SIZE_OPTIONS: { value: LibrarySizeScope; label: string; icon: React.ReactNode }[] = [
  { value: 'music',     label: 'Music',      icon: <FiMusic className="w-5 h-5" /> },
  { value: 'audiobook', label: 'Audiobooks', icon: <FiBookOpen className="w-5 h-5" /> },
  { value: 'all',       label: 'All Libraries', icon: <FiHardDrive className="w-5 h-5" /> },
]

function LibrarySizePicker({ onSelect }: { onSelect: (scope: LibrarySizeScope) => void }) {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 p-4">
      <p className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Select library</p>
      <div className="flex flex-col gap-2 w-full">
        {LIBRARY_SIZE_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onSelect(opt.value)}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg border border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#0D1117] hover:border-[#FF1493]/50 hover:bg-[#FF1493]/5 transition-colors text-sm text-gray-700 dark:text-gray-300"
          >
            <span className="text-gray-400 dark:text-gray-500">{opt.icon}</span>
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

export default function StatCardWidget({
  widgetId,
  isEditMode,
  libraryType: registryLibraryType,
  widgetSettings,
  onSettingsChange,
}: {
  widgetId: string
  isEditMode: boolean
  libraryType?: 'music' | 'audiobook'
  widgetSettings?: Record<string, unknown>
  onSettingsChange?: (settings: Record<string, unknown>) => void
}) {
  const navigate = useNavigate()

  // For configurable library-size instances (e.g. "library-size__123"), derive the
  // effective library type from widgetSettings. The original "library-size" widget
  // (no suffix) falls back to "all" for backward compatibility.
  const isConfigurableInstance = widgetId.includes('__') && widgetId.startsWith('library-size')
  const configuredScope = widgetSettings?.libraryType as LibrarySizeScope | undefined
  const effectiveScope: LibrarySizeScope | undefined = isConfigurableInstance ? configuredScope : undefined

  // Map scope → API libraryType param
  const apiLibraryType: 'music' | 'audiobook' | undefined =
    effectiveScope === 'music' ? 'music' :
    effectiveScope === 'audiobook' ? 'audiobook' :
    registryLibraryType  // for non-library-size widgets, use registry value

  // Resolve the widget config key: configurable instances always use 'library-size'
  const configKey = isConfigurableInstance ? 'library-size' : widgetId
  const config = WIDGET_CONFIG[configKey]

  const { data: statisticsData } = useQuery<StatisticsData>({
    queryKey: ['statistics', apiLibraryType],
    queryFn: () => systemApi.getStatistics(apiLibraryType),
    refetchInterval: 60000,
    enabled: config?.source === 'statistics' && (!isConfigurableInstance || !!configuredScope),
  })

  const { data: systemStats } = useQuery<SystemStats>({
    queryKey: ['systemStats', apiLibraryType],
    queryFn: () => systemApi.getStats(apiLibraryType),
    refetchInterval: 30000,
    enabled: config?.source === 'systemStats' && (!isConfigurableInstance || !!configuredScope),
  })

  if (!config) return null

  // Configurable library-size instance — show picker if library not yet chosen
  if (isConfigurableInstance && !configuredScope) {
    return (
      <LibrarySizePicker
        onSelect={(scope) => onSettingsChange?.({ libraryType: scope })}
      />
    )
  }

  const value = config.getValue(statisticsData || null, systemStats || null)
  const subtitle = config.getSubtitle(statisticsData || null, systemStats || null)
  const link = config.getLink?.()
  const isClickable = !!link && !isEditMode

  const handleClick = () => {
    if (isClickable) navigate(link!)
  }

  // For configured instances, override the title to show which library
  const displayTitle = isConfigurableInstance && configuredScope
    ? `${LIBRARY_SIZE_OPTIONS.find(o => o.value === configuredScope)?.label ?? ''} Library Size`
    : config.title

  return (
    <div
      className={`h-full flex items-center p-4 ${isClickable ? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-[#161B22] transition-colors rounded-lg' : ''}`}
      onClick={handleClick}
    >
      <div className="flex items-center justify-between w-full">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">{displayTitle}</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">{typeof value === 'number' ? value.toLocaleString() : value}</p>
          {subtitle && <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400 truncate">{subtitle}</p>}
        </div>
        <div className="flex flex-col items-end gap-2 flex-shrink-0">
          <div className={`p-3 rounded-lg ${colorClasses[config.color]}`}>{config.icon}</div>
          {/* Reconfigure button visible only in edit mode for configurable instances */}
          {isEditMode && isConfigurableInstance && (
            <button
              title="Change library"
              onClick={(e) => {
                e.stopPropagation()
                onSettingsChange?.({})
              }}
              className="p-1 rounded text-gray-400 hover:text-[#FF1493] transition-colors"
            >
              <FiSettings className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
