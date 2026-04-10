import { useQuery } from '@tanstack/react-query'
import { systemApi } from '../../../api/client'
import type { SystemStats } from '../../../types'

export default function ActiveDownloadsWidget({ libraryType }: { widgetId: string; isEditMode: boolean; libraryType?: 'music' | 'audiobook' }) {
  const { data: stats } = useQuery<SystemStats>({
    queryKey: ['systemStats', libraryType],
    queryFn: () => systemApi.getStats(libraryType),
    refetchInterval: 30000,
  })

  return (
    <div className="h-full p-4 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Active Downloads</h2>
      {stats && stats.active_downloads > 0 ? (
        <div className="flex-1 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-gray-600 dark:text-gray-400">Downloading</span>
            <span className="font-medium text-gray-900 dark:text-white">{stats.active_downloads}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-600 dark:text-gray-400">Completed</span>
            <span className="font-medium text-green-600 dark:text-green-400">{stats.completed_downloads}</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-600 dark:text-gray-400">Failed</span>
            <span className="font-medium text-red-600 dark:text-red-400">{stats.failed_downloads}</span>
          </div>
        </div>
      ) : (
        <p className="text-gray-500 dark:text-gray-400">No active downloads</p>
      )}
    </div>
  )
}
