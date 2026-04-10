import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { systemApi } from '../../../api/client'
import { FiUsers, FiDisc, FiLink, FiCheckCircle, FiMusic, FiHardDrive, FiBookOpen, FiBook } from 'react-icons/fi'
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

export default function StatCardWidget({ widgetId, libraryType }: { widgetId: string; isEditMode: boolean; libraryType?: 'music' | 'audiobook' }) {
  const navigate = useNavigate()
  const config = WIDGET_CONFIG[widgetId]

  const { data: statisticsData } = useQuery<StatisticsData>({
    queryKey: ['statistics', libraryType],
    queryFn: () => systemApi.getStatistics(libraryType),
    refetchInterval: 60000,
    enabled: config?.source === 'statistics',
  })

  const { data: systemStats } = useQuery<SystemStats>({
    queryKey: ['systemStats', libraryType],
    queryFn: () => systemApi.getStats(libraryType),
    refetchInterval: 30000,
    enabled: config?.source === 'systemStats',
  })

  if (!config) return null

  const value = config.getValue(statisticsData || null, systemStats || null)
  const subtitle = config.getSubtitle(statisticsData || null, systemStats || null)
  const link = config.getLink?.()
  const isClickable = !!link

  const handleClick = () => {
    if (link) navigate(link)
  }

  return (
    <div
      className={`h-full flex items-center p-4 ${isClickable ? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-[#161B22] transition-colors rounded-lg' : ''}`}
      onClick={isClickable ? handleClick : undefined}
    >
      <div className="flex items-center justify-between w-full">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">{config.title}</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">{typeof value === 'number' ? value.toLocaleString() : value}</p>
          {subtitle && <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400 truncate">{subtitle}</p>}
        </div>
        <div className={`p-3 rounded-lg flex-shrink-0 ${colorClasses[config.color]}`}>{config.icon}</div>
      </div>
    </div>
  )
}
