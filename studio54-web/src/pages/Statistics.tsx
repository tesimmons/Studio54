import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { FiUsers, FiDisc, FiMusic, FiHardDrive, FiDownload, FiDatabase } from 'react-icons/fi'
import api from '../api/client'
import { useAuth } from '../contexts/AuthContext'

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
  downloads: {
    daily_trend: Array<{ date: string; completed: number; failed: number }>
  }
  jobs_last_7d: Record<string, number>
}

const STATUS_COLORS: Record<string, string> = {
  wanted: 'bg-yellow-500',
  searching: 'bg-blue-500',
  downloading: 'bg-indigo-500',
  downloaded: 'bg-green-500',
  failed: 'bg-red-500',
}

const FORMAT_COLORS: Record<string, string> = {
  flac: 'bg-emerald-500',
  mp3: 'bg-blue-500',
  aac: 'bg-purple-500',
  m4a: 'bg-violet-500',
  ogg: 'bg-orange-500',
  wav: 'bg-cyan-500',
  opus: 'bg-pink-500',
  wma: 'bg-amber-500',
  unknown: 'bg-gray-400',
}

function StatCard({ title, value, subtitle, icon, color = 'primary' }: {
  title: string
  value: number | string
  subtitle?: string
  icon: React.ReactNode
  color?: 'primary' | 'success' | 'warning' | 'danger'
}) {
  const colorClasses = {
    primary: 'bg-[#FF1493]/5 dark:bg-[#FF1493]/10 text-[#FF1493] dark:text-[#ff4da6]',
    success: 'bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400',
    warning: 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-600 dark:text-yellow-400',
    danger: 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400',
  }

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">{title}</p>
          <p className="mt-2 text-3xl font-semibold text-gray-900 dark:text-white">{value}</p>
          {subtitle && <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{subtitle}</p>}
        </div>
        <div className={`p-3 rounded-lg ${colorClasses[color]}`}>{icon}</div>
      </div>
    </div>
  )
}

function HorizontalBar({ label, value, max, color, showPercent = false }: {
  label: string
  value: number
  max: number
  color: string
  showPercent?: boolean
}) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-20 text-sm text-gray-600 dark:text-gray-400 text-right truncate">{label}</span>
      <div className="flex-1 h-5 bg-gray-200 dark:bg-[#0D1117] rounded-full overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all duration-500`}
          style={{ width: `${Math.max(pct, 1)}%` }}
        />
      </div>
      <span className="w-16 text-sm font-medium text-gray-900 dark:text-white text-right">
        {showPercent ? `${pct.toFixed(1)}%` : value.toLocaleString()}
      </span>
    </div>
  )
}

function Statistics() {
  const navigate = useNavigate()
  const { isDjOrAbove } = useAuth()
  const { data: stats, isLoading } = useQuery<StatisticsData>({
    queryKey: ['statistics'],
    queryFn: async () => {
      const { data } = await api.get('/statistics')
      return data
    },
    refetchInterval: 60000,
  })

  if (isLoading || !stats) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493] mx-auto" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading statistics...</p>
        </div>
      </div>
    )
  }

  const albumMax = Math.max(...Object.values(stats.albums.status_breakdown), 1)
  const formatMax = stats.library.format_distribution.length > 0
    ? Math.max(...stats.library.format_distribution.map(f => f.count), 1)
    : 1
  const trendMax = stats.downloads.daily_trend.length > 0
    ? Math.max(...stats.downloads.daily_trend.map(d => d.completed + d.failed), 1)
    : 1

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Statistics</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">
          Library overview, download trends, and quality distribution
        </p>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Artists"
          value={stats.artists.total}
          subtitle={`${stats.artists.monitored} monitored`}
          icon={<FiUsers className="w-6 h-6" />}
        />
        <StatCard
          title="Albums"
          value={stats.albums.total}
          subtitle={`${stats.albums.status_breakdown.downloaded || 0} downloaded`}
          icon={<FiDisc className="w-6 h-6" />}
          color="success"
        />
        <StatCard
          title="Tracks"
          value={stats.tracks.total}
          subtitle={`${stats.tracks.with_files} with files (${stats.tracks.file_percent}%)`}
          icon={<FiMusic className="w-6 h-6" />}
        />
        <StatCard
          title="Library Size"
          value={stats.library.total_size}
          subtitle={`${stats.library.total_files.toLocaleString()} files`}
          icon={<FiHardDrive className="w-6 h-6" />}
          color="warning"
        />
      </div>

      {/* Middle Row: Album Status + Format Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Album Status Breakdown */}
        <div className="card p-6">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Album Status</h2>
          <div className="space-y-1">
            {Object.entries(stats.albums.status_breakdown)
              .sort(([, a], [, b]) => b - a)
              .map(([status, count]) => (
                <HorizontalBar
                  key={status}
                  label={status}
                  value={count}
                  max={albumMax}
                  color={STATUS_COLORS[status] || 'bg-gray-400'}
                />
              ))}
          </div>
          {Object.keys(stats.albums.status_breakdown).length === 0 && (
            <p className="text-gray-500 dark:text-gray-400">No albums yet</p>
          )}
        </div>

        {/* Format Distribution */}
        <div className="card p-6">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">File Formats</h2>
          <div className="space-y-1">
            {stats.library.format_distribution.slice(0, 8).map(({ format, count }) => (
              <HorizontalBar
                key={format}
                label={format.toUpperCase()}
                value={count}
                max={formatMax}
                color={FORMAT_COLORS[format.toLowerCase()] || 'bg-gray-400'}
              />
            ))}
          </div>
          {stats.library.format_distribution.length === 0 && (
            <p className="text-gray-500 dark:text-gray-400">No library files scanned</p>
          )}
        </div>
      </div>

      {/* Download Trend */}
      {isDjOrAbove && <div className="card p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          <FiDownload className="inline w-5 h-5 mr-2 -mt-0.5" />
          Download Trend (Last 30 Days)
        </h2>
        {stats.downloads.daily_trend.length > 0 ? (
          <div className="flex items-end gap-1 h-40">
            {stats.downloads.daily_trend.map((day) => {
              const totalH = ((day.completed + day.failed) / trendMax) * 100
              const failedH = (day.failed / trendMax) * 100
              const completedH = (day.completed / trendMax) * 100
              return (
                <div key={day.date} className="flex-1 flex flex-col items-center justify-end h-full group relative">
                  <div className="w-full flex flex-col justify-end" style={{ height: `${totalH}%` }}>
                    {day.completed > 0 && (
                      <div
                        className="w-full bg-green-500 rounded-t cursor-pointer hover:bg-green-400 transition-colors"
                        style={{ height: `${(completedH / totalH) * 100}%`, minHeight: '2px' }}
                        onClick={() => navigate(`/download-history?status_filter=completed&date_from=${day.date}&date_to=${day.date}`)}
                      />
                    )}
                    {day.failed > 0 && (
                      <div
                        className="w-full bg-red-500 cursor-pointer hover:bg-red-400 transition-colors"
                        style={{ height: `${(failedH / totalH) * 100}%`, minHeight: '2px' }}
                        onClick={() => navigate(`/download-history?status_filter=failed&date_from=${day.date}&date_to=${day.date}`)}
                      />
                    )}
                  </div>
                  {/* Tooltip */}
                  <div className="absolute bottom-full mb-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10">
                    {day.date}: {day.completed} ok, {day.failed} fail
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <p className="text-gray-500 dark:text-gray-400">No download data in the last 30 days</p>
        )}
        {stats.downloads.daily_trend.length > 0 && (
          <div className="flex items-center gap-4 mt-3 text-xs text-gray-500">
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-green-500 rounded inline-block" /> Completed</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-red-500 rounded inline-block" /> Failed</span>
          </div>
        )}
      </div>}

      {/* Bottom Row: MusicBrainz Coverage + Job Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* MusicBrainz Coverage */}
        <div className="card p-6">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
            <FiDatabase className="inline w-5 h-5 mr-2 -mt-0.5" />
            MusicBrainz Coverage
          </h2>
          <div className="space-y-4">
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-gray-600 dark:text-gray-400">Track MBID Coverage</span>
                <span className="font-medium text-gray-900 dark:text-white">{stats.library.musicbrainz_coverage.coverage_percent}%</span>
              </div>
              <div className="h-3 bg-gray-200 dark:bg-[#0D1117] rounded-full overflow-hidden">
                <div
                  className="h-full bg-[#FF1493]/50 rounded-full transition-all duration-500"
                  style={{ width: `${stats.library.musicbrainz_coverage.coverage_percent}%` }}
                />
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {stats.library.musicbrainz_coverage.tracks_tagged.toLocaleString()} of {stats.library.total_files.toLocaleString()} files tagged
              </p>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="bg-gray-50 dark:bg-[#161B22] rounded-lg p-3">
                <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                  {stats.library.musicbrainz_coverage.tracks_tagged.toLocaleString()}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Tracks Tagged</p>
              </div>
              <div className="bg-gray-50 dark:bg-[#161B22] rounded-lg p-3">
                <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                  {stats.library.musicbrainz_coverage.files_linked.toLocaleString()}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Files Linked</p>
              </div>
              <div className="bg-gray-50 dark:bg-[#161B22] rounded-lg p-3">
                <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                  {stats.library.musicbrainz_coverage.albums_tagged.toLocaleString()}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">Albums Tagged</p>
              </div>
            </div>
          </div>
        </div>

        {/* Recent Jobs */}
        <div className="card p-6">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Jobs (Last 7 Days)</h2>
          {Object.keys(stats.jobs_last_7d).length > 0 ? (
            <div className="space-y-3">
              {Object.entries(stats.jobs_last_7d)
                .sort(([, a], [, b]) => b - a)
                .map(([status, count]) => {
                  const jobColors: Record<string, string> = {
                    completed: 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20',
                    failed: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20',
                    running: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20',
                    stalled: 'text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20',
                    pending: 'text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-[#161B22]',
                    cancelled: 'text-gray-500 dark:text-gray-500 bg-gray-50 dark:bg-[#161B22]',
                  }
                  return (
                    <div key={status} className="flex items-center justify-between">
                      <span className="text-sm text-gray-600 dark:text-gray-400 capitalize">{status}</span>
                      <span className={`px-3 py-1 rounded-full text-sm font-medium ${jobColors[status] || 'text-gray-600 bg-gray-100'}`}>
                        {count}
                      </span>
                    </div>
                  )
                })}
            </div>
          ) : (
            <p className="text-gray-500 dark:text-gray-400">No jobs in the last 7 days</p>
          )}
        </div>
      </div>
    </div>
  )
}

export default Statistics
