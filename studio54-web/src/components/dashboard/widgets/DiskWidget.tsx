import { useQuery } from '@tanstack/react-query'
import { systemApi } from '../../../api/client'
import { FiHardDrive } from 'react-icons/fi'
import type { SystemStats } from '../../../types'

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

function diskColor(percent: number): string {
  if (percent >= 85) return 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400'
  if (percent >= 70) return 'bg-yellow-50 dark:bg-yellow-900/20 text-yellow-600 dark:text-yellow-400'
  return 'bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400'
}

export default function DiskWidget({ widgetId }: { widgetId: string; isEditMode: boolean }) {
  const { data: stats } = useQuery<SystemStats>({
    queryKey: ['systemStats'],
    queryFn: () => systemApi.getStats(),
    refetchInterval: 30000,
  })

  const isSystem = widgetId === 'system-disk'
  const disk = isSystem ? stats?.disk?.root : stats?.disk?.docker
  const title = isSystem ? 'System Disk' : 'Storage Disk (/docker)'

  if (!disk) {
    return (
      <div className="h-full flex items-center justify-center p-4">
        <p className="text-sm text-gray-500 dark:text-gray-400">No disk data</p>
      </div>
    )
  }

  return (
    <div className="h-full flex items-center p-4">
      <div className="flex items-center justify-between w-full">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-600 dark:text-gray-400">{title}</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">{disk.percent}%</p>
          <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400 truncate">
            {formatBytes(disk.used_bytes)} / {formatBytes(disk.total_bytes)} ({formatBytes(disk.free_bytes)} free)
          </p>
        </div>
        <div className={`p-3 rounded-lg flex-shrink-0 ${diskColor(disk.percent)}`}>
          <FiHardDrive className="w-6 h-6" />
        </div>
      </div>
    </div>
  )
}
