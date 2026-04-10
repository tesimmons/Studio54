import { useQuery } from '@tanstack/react-query'
import { systemApi } from '../../../api/client'

interface StatisticsData {
  library: {
    format_distribution: Array<{ format: string; count: number }>
  }
}

const FORMAT_COLORS: Record<string, string> = {
  flac: 'bg-emerald-500', mp3: 'bg-blue-500', aac: 'bg-purple-500',
  m4a: 'bg-violet-500', ogg: 'bg-orange-500', wav: 'bg-cyan-500',
  opus: 'bg-pink-500', wma: 'bg-amber-500', unknown: 'bg-gray-400',
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

export default function FileFormatsWidget({ libraryType }: { widgetId: string; isEditMode: boolean; libraryType?: 'music' | 'audiobook' }) {
  const { data: stats } = useQuery<StatisticsData>({
    queryKey: ['statistics', libraryType],
    queryFn: () => systemApi.getStatistics(libraryType),
    refetchInterval: 60000,
  })

  const formats = stats?.library.format_distribution || []
  const formatMax = formats.length > 0 ? Math.max(...formats.map(f => f.count), 1) : 1

  return (
    <div className="h-full p-4 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">File Formats</h2>
      <div className="flex-1 overflow-y-auto space-y-1">
        {formats.length > 0 ? (
          formats.slice(0, 8).map(({ format, count }) => (
            <HorizontalBar key={format} label={format.toUpperCase()} value={count} max={formatMax} color={FORMAT_COLORS[format.toLowerCase()] || 'bg-gray-400'} />
          ))
        ) : (
          <p className="text-gray-500 dark:text-gray-400">No library files scanned</p>
        )}
      </div>
    </div>
  )
}
