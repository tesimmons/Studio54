import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { queueStatusApi } from '../api/client'
import type { QueueStatusResponse } from '../api/client'
import {
  FiBox,
  FiCpu,
  FiLayers,
  FiTrash2,
  FiRefreshCw,
  FiSearch,
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
} from 'react-icons/fi'
import toast from 'react-hot-toast'

// Queue display metadata
const QUEUE_INFO: Record<string, { label: string; description: string; color: string }> = {
  monitoring: { label: 'Monitoring', description: 'Health checks, stalled job detection', color: 'blue' },
  downloads: { label: 'Downloads', description: 'SABnzbd interaction, download management', color: 'green' },
  search: { label: 'Search', description: 'Album search with decision engine', color: 'purple' },
  sync: { label: 'Sync', description: 'MusicBrainz artist/album sync', color: 'orange' },
  organization: { label: 'Organization', description: 'File linking, renaming, organizing', color: 'yellow' },
  celery: { label: 'Default', description: 'Import tasks, general fallback', color: 'gray' },
  library: { label: 'Library', description: 'Library scanning tasks', color: 'teal' },
  ingest_fast: { label: 'Fast Ingest', description: 'V2 scanner fast ingest', color: 'cyan' },
  index_metadata: { label: 'Metadata Index', description: 'Metadata indexing batches', color: 'indigo' },
  fetch_images: { label: 'Fetch Images', description: 'Image fetching batches', color: 'pink' },
  calculate_hashes: { label: 'Hashes', description: 'File hash calculation', color: 'red' },
  scan: { label: 'Scan', description: 'V2 scanner coordination', color: 'emerald' },
}

function getHealthStatus(depth: number): 'healthy' | 'warning' | 'critical' {
  if (depth === 0) return 'healthy'
  if (depth <= 50) return 'warning'
  return 'critical'
}

function formatRuntime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function formatTaskName(fullName: string): string {
  // "app.tasks.download_tasks.monitor_active_downloads" -> "monitor_active_downloads"
  const parts = fullName.split('.')
  return parts[parts.length - 1]
}

function QueueStatus() {
  const queryClient = useQueryClient()
  const [confirmPurge, setConfirmPurge] = useState<string | null>(null)

  const { data, isLoading, isError } = useQuery<QueueStatusResponse>({
    queryKey: ['queue-status'],
    queryFn: queueStatusApi.getStatus,
    refetchInterval: 5000,
  })

  const purgeMutation = useMutation({
    mutationFn: queueStatusApi.purgeQueue,
    onSuccess: (result, queueName) => {
      toast.success(`Purged ${result.messages_purged} messages from ${queueName}`)
      queryClient.invalidateQueries({ queryKey: ['queue-status'] })
      setConfirmPurge(null)
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to purge queue')
      setConfirmPurge(null)
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <FiRefreshCw className="w-8 h-8 text-gray-400 animate-spin" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="card p-6 text-center">
        <FiAlertTriangle className="w-12 h-12 text-red-400 mx-auto mb-3" />
        <p className="text-gray-600 dark:text-gray-400">Failed to load queue status. Is the service running?</p>
      </div>
    )
  }

  const { summary, queues, workers } = data

  // Sort queues: non-empty first, then alphabetical
  const sortedQueues = Object.entries(queues).sort(([, a], [, b]) => b - a)

  // Overall health
  const totalBacklog = summary.total_pending
  const overallHealth = totalBacklog === 0 ? 'healthy' : totalBacklog <= 100 ? 'warning' : 'critical'

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <SummaryCard
          title="Pending Tasks"
          value={summary.total_pending}
          icon={<FiLayers className="w-5 h-5" />}
          color={overallHealth === 'healthy' ? 'green' : overallHealth === 'warning' ? 'yellow' : 'red'}
        />
        <SummaryCard
          title="Active Tasks"
          value={summary.total_active}
          icon={<FiCpu className="w-5 h-5" />}
          color="blue"
        />
        <SummaryCard
          title="Reserved"
          value={summary.total_reserved}
          icon={<FiClock className="w-5 h-5" />}
          color="purple"
        />
        <SummaryCard
          title="Workers"
          value={summary.total_workers}
          icon={<FiBox className="w-5 h-5" />}
          color={summary.total_workers > 0 ? 'green' : 'red'}
        />
        <SummaryCard
          title="Search Locks"
          value={summary.active_search_locks}
          icon={<FiSearch className="w-5 h-5" />}
          color={summary.active_search_locks > 5 ? 'yellow' : 'gray'}
        />
      </div>

      {/* Queue Depths */}
      <div className="card">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-[#30363D] flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Queue Depths</h3>
          <span className="text-xs text-gray-500 dark:text-gray-400">
            Auto-refreshing every 5s
          </span>
        </div>
        <div className="divide-y divide-gray-100 dark:divide-[#30363D]/50">
          {sortedQueues.map(([queueName, depth]) => {
            const info = QUEUE_INFO[queueName] || { label: queueName, description: '', color: 'gray' }
            const health = getHealthStatus(depth)

            return (
              <div key={queueName} className="px-6 py-3 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                <div className="flex items-center space-x-3 min-w-0 flex-1">
                  {health === 'healthy' && <FiCheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />}
                  {health === 'warning' && <FiAlertTriangle className="w-4 h-4 text-yellow-500 flex-shrink-0" />}
                  {health === 'critical' && <FiAlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0" />}
                  <div className="min-w-0">
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {info.label}
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400 ml-2">
                      {info.description}
                    </span>
                  </div>
                </div>

                <div className="flex items-center space-x-4">
                  {/* Depth bar */}
                  <div className="w-32 hidden sm:block">
                    <div className="h-2 bg-gray-200 dark:bg-[#0D1117] rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          health === 'healthy' ? 'bg-green-500' :
                          health === 'warning' ? 'bg-yellow-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${Math.min(100, (depth / Math.max(totalBacklog, 1)) * 100)}%` }}
                      />
                    </div>
                  </div>

                  {/* Count */}
                  <span className={`text-sm font-mono font-semibold w-16 text-right ${
                    health === 'healthy' ? 'text-green-600 dark:text-green-400' :
                    health === 'warning' ? 'text-yellow-600 dark:text-yellow-400' :
                    'text-red-600 dark:text-red-400'
                  }`}>
                    {depth.toLocaleString()}
                  </span>

                  {/* Purge button (only for non-empty queues) */}
                  {depth > 0 && (
                    confirmPurge === queueName ? (
                      <div className="flex items-center space-x-1">
                        <button
                          onClick={() => purgeMutation.mutate(queueName)}
                          className="px-2 py-1 text-xs bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
                          disabled={purgeMutation.isPending}
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setConfirmPurge(null)}
                          className="px-2 py-1 text-xs bg-gray-300 dark:bg-gray-600 text-gray-700 dark:text-gray-300 rounded hover:bg-gray-400 dark:hover:bg-gray-500 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmPurge(queueName)}
                        className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                        title={`Purge ${depth} messages from ${info.label}`}
                      >
                        <FiTrash2 className="w-4 h-4" />
                      </button>
                    )
                  )}
                  {depth === 0 && <div className="w-6" />}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Workers */}
      <div className="card">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-[#30363D]">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Workers</h3>
        </div>
        {workers.length === 0 ? (
          <div className="px-6 py-8 text-center">
            <FiAlertTriangle className="w-8 h-8 text-red-400 mx-auto mb-2" />
            <p className="text-sm text-gray-500 dark:text-gray-400">No workers responding</p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-[#30363D]/50">
            {workers.map((worker) => (
              <div key={worker.name} className="px-6 py-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center space-x-2">
                    <FiCpu className="w-4 h-4 text-green-500" />
                    <span className="text-sm font-medium text-gray-900 dark:text-white">
                      {worker.name}
                    </span>
                  </div>
                  <div className="flex items-center space-x-4 text-xs text-gray-500 dark:text-gray-400">
                    <span>Pool: {worker.pool_size}</span>
                    <span>Active: {worker.active_tasks}</span>
                    <span>Reserved: {worker.reserved_tasks}</span>
                    <span>Completed: {worker.tasks_completed.toLocaleString()}</span>
                  </div>
                </div>

                {/* Active tasks */}
                {worker.active_task_names.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {worker.active_task_names.map((task) => (
                      <div
                        key={task.id}
                        className="flex items-center justify-between bg-gray-50 dark:bg-[#161B22]/50 rounded px-3 py-1.5 text-xs"
                      >
                        <span className="font-mono text-gray-700 dark:text-gray-300">
                          {formatTaskName(task.name)}
                        </span>
                        {task.runtime > 0 && (
                          <span className={`font-mono ${
                            task.runtime > 300 ? 'text-red-500' :
                            task.runtime > 60 ? 'text-yellow-500' : 'text-gray-500 dark:text-gray-400'
                          }`}>
                            {formatRuntime(task.runtime)}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SummaryCard({
  title,
  value,
  icon,
  color,
}: {
  title: string
  value: number
  icon: React.ReactNode
  color: string
}) {
  const colorMap: Record<string, string> = {
    green: 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400',
    blue: 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400',
    purple: 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400',
    yellow: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400',
    red: 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400',
    gray: 'bg-gray-100 dark:bg-[#0D1117]/50 text-gray-600 dark:text-gray-400',
  }

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">{title}</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-white">
            {value.toLocaleString()}
          </p>
        </div>
        <div className={`p-2 rounded-lg ${colorMap[color] || colorMap.gray}`}>
          {icon}
        </div>
      </div>
    </div>
  )
}

export default QueueStatus
