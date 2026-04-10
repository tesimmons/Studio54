import { useQuery } from '@tanstack/react-query'
import { systemApi } from '../../../api/client'

interface StatisticsData {
  albums: { total: number; status_breakdown: Record<string, number> }
}

const STATUS_COLORS: Record<string, string> = {
  monitored: 'bg-blue-500',
  searching: 'bg-indigo-500',
  downloading: 'bg-purple-500',
  downloaded: 'bg-green-500',
  wanted: 'bg-yellow-500',
  failed: 'bg-red-500',
}

function HorizontalBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-20 text-sm text-gray-600 dark:text-gray-400 text-right truncate">{label}</span>
      <div className="flex-1 h-5 bg-gray-200 dark:bg-[#0D1117] rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all duration-500`} style={{ width: `${Math.max(pct, 1)}%` }} />
      </div>
      <span className="w-16 text-sm font-medium text-gray-900 dark:text-white text-right">{value.toLocaleString()}</span>
    </div>
  )
}

export default function AlbumStatusWidget({ libraryType }: { widgetId: string; isEditMode: boolean; libraryType?: 'music' | 'audiobook' }) {
  const { data: stats } = useQuery<StatisticsData>({
    queryKey: ['statistics', libraryType],
    queryFn: () => systemApi.getStatistics(libraryType),
    refetchInterval: 60000,
  })

  const breakdown = stats?.albums.status_breakdown || {}
  const albumMax = Object.values(breakdown).length > 0 ? Math.max(...Object.values(breakdown), 1) : 1

  return (
    <div className="h-full p-4 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Album Status</h2>
      <div className="flex-1 overflow-hidden space-y-1">
        {Object.entries(breakdown).length > 0 ? (
          Object.entries(breakdown)
            .sort(([, a], [, b]) => b - a)
            .map(([status, count]) => (
              <HorizontalBar key={status} label={status} value={count} max={albumMax} color={STATUS_COLORS[status] || 'bg-gray-400'} />
            ))
        ) : (
          <p className="text-gray-500 dark:text-gray-400">No albums yet</p>
        )}
      </div>
    </div>
  )
}
