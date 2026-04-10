import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { FiDownload } from 'react-icons/fi'
import { systemApi } from '../../../api/client'

interface StatisticsData {
  downloads: {
    daily_trend: Array<{ date: string; completed: number; failed: number }>
  }
}

export default function DownloadTrendWidget({ libraryType }: { widgetId: string; isEditMode: boolean; libraryType?: 'music' | 'audiobook' }) {
  const navigate = useNavigate()
  const { data: stats } = useQuery<StatisticsData>({
    queryKey: ['statistics', libraryType],
    queryFn: () => systemApi.getStatistics(libraryType),
    refetchInterval: 60000,
  })

  const trend = stats?.downloads.daily_trend || []
  const trendMax = trend.length > 0 ? Math.max(...trend.map(d => d.completed + d.failed), 1) : 1

  return (
    <div className="h-full p-4 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">
        <FiDownload className="inline w-5 h-5 mr-2 -mt-0.5" />
        Download Trend (Last 30 Days)
      </h2>
      {trend.length > 0 ? (
        <>
          <div className="flex items-end gap-1 flex-1 min-h-0">
            {trend.map((day) => {
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
                        onClick={() => navigate(`/activity?tab=downloads&status_filter=completed&date_from=${day.date}&date_to=${day.date}`)}
                      />
                    )}
                    {day.failed > 0 && (
                      <div
                        className="w-full bg-red-500 cursor-pointer hover:bg-red-400 transition-colors"
                        style={{ height: `${(failedH / totalH) * 100}%`, minHeight: '2px' }}
                        onClick={() => navigate(`/activity?tab=downloads&status_filter=failed&date_from=${day.date}&date_to=${day.date}`)}
                      />
                    )}
                  </div>
                  <div className="absolute bottom-full mb-2 hidden group-hover:block bg-gray-800 text-white text-xs rounded px-2 py-1 whitespace-nowrap z-10">
                    {day.date}: {day.completed} ok, {day.failed} fail
                  </div>
                </div>
              )
            })}
          </div>
          <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-green-500 rounded inline-block" /> Completed</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 bg-red-500 rounded inline-block" /> Failed</span>
          </div>
        </>
      ) : (
        <p className="text-gray-500 dark:text-gray-400">No download data in the last 30 days</p>
      )}
    </div>
  )
}
