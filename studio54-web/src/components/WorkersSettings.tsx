import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { workersApi } from '../api/client'
import type { WorkerSettings as WorkerSettingsType } from '../api/client'

export default function WorkersSettings() {
  const queryClient = useQueryClient()

  const { data: workerSettings, isLoading: workerSettingsLoading } = useQuery<WorkerSettingsType>({
    queryKey: ['workerSettings'],
    queryFn: () => workersApi.getSettings(),
    refetchInterval: 10000,
  })

  const updateWorkerSettingsMutation = useMutation({
    mutationFn: (settings: { enabled?: boolean; max_workers?: number }) =>
      workersApi.updateSettings(settings),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workerSettings'] })
      toast.success('Worker settings updated')
    },
    onError: () => toast.error('Failed to update worker settings'),
  })

  const scaleWorkersMutation = useMutation({
    mutationFn: (target: number) => workersApi.scale(target),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workerSettings'] })
      toast.success('Workers scaled')
    },
    onError: () => toast.error('Failed to scale workers'),
  })

  if (workerSettingsLoading) {
    return <div className="text-gray-500 dark:text-gray-400">Loading workers...</div>
  }

  if (!workerSettings) {
    return <div className="text-red-500">Failed to load worker settings</div>
  }

  return (
    <div className="space-y-6">
      <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Workers</h3>

      {/* Autoscale Config Card */}
      <div className="card p-6">
        <h4 className="text-base font-medium text-gray-900 dark:text-white mb-4">Autoscaling</h4>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
          Automatically scale Celery worker containers based on load. When all workers are at
          capacity (8 tasks) for 5+ minutes, a new worker is spawned. Idle workers are removed
          after 10 minutes.
        </p>

        <label className="flex items-center gap-3 cursor-pointer mb-4">
          <input
            type="checkbox"
            checked={workerSettings.enabled}
            onChange={(e) => updateWorkerSettingsMutation.mutate({ enabled: e.target.checked })}
            className="h-4 w-4 rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
          />
          <span className="text-sm font-medium text-gray-900 dark:text-white">Enable Autoscaling</span>
        </label>

        <div className="flex items-center gap-3 mb-4">
          <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Max Workers</label>
          <input
            type="number"
            value={workerSettings.max_workers}
            onChange={(e) => {
              const val = parseInt(e.target.value)
              if (!isNaN(val) && val >= 1 && val <= 10) updateWorkerSettingsMutation.mutate({ max_workers: val })
            }}
            min={1} max={10}
            className="w-20 px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
          />
          <span className="text-sm text-gray-500 dark:text-gray-400">containers (1-10)</span>
        </div>
      </div>

      {/* Live Status Card */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <h4 className="text-base font-medium text-gray-900 dark:text-white">Live Status</h4>
          <div className="flex items-center gap-2">
            <button
              onClick={() => scaleWorkersMutation.mutate(workerSettings.current_workers + 1)}
              disabled={scaleWorkersMutation.isPending || workerSettings.current_workers >= 10}
              className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              + Add Worker
            </button>
            <button
              onClick={() => scaleWorkersMutation.mutate(Math.max(1, workerSettings.current_workers - 1))}
              disabled={scaleWorkersMutation.isPending || workerSettings.current_workers <= 1}
              className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 transition-colors"
            >
              - Remove Worker
            </button>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3">
            <div className="text-2xl font-bold text-gray-900 dark:text-white">{workerSettings.current_workers}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400">Worker Containers</div>
          </div>
          <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3">
            <div className="text-2xl font-bold text-gray-900 dark:text-white">{workerSettings.total_active_tasks}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400">Active Tasks</div>
          </div>
          <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3">
            <div className="text-2xl font-bold text-gray-900 dark:text-white">{workerSettings.current_workers * 8}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400">Total Capacity</div>
          </div>
        </div>

        {workerSettings.workers.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-[#30363D]">
                  <th className="text-left py-2 px-3 text-gray-600 dark:text-gray-400 font-medium">Worker</th>
                  <th className="text-left py-2 px-3 text-gray-600 dark:text-gray-400 font-medium">Active Tasks</th>
                  <th className="text-left py-2 px-3 text-gray-600 dark:text-gray-400 font-medium">Load</th>
                  <th className="text-left py-2 px-3 text-gray-600 dark:text-gray-400 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {workerSettings.workers.map((worker) => {
                  const loadPct = (worker.active_tasks / 8) * 100
                  const isIdle = worker.active_tasks === 0
                  const isAtCapacity = worker.active_tasks >= 8
                  return (
                    <tr key={worker.name} className="border-b border-gray-100 dark:border-[#30363D]/50">
                      <td className="py-2 px-3 text-gray-900 dark:text-white font-mono text-xs">
                        {worker.name.split('@')[1] || worker.name}
                      </td>
                      <td className="py-2 px-3 text-gray-700 dark:text-gray-300">{worker.active_tasks} / 8</td>
                      <td className="py-2 px-3">
                        <div className="w-full bg-gray-200 dark:bg-gray-600 rounded-full h-2.5">
                          <div
                            className={`h-2.5 rounded-full transition-all ${
                              isAtCapacity ? 'bg-red-500' : loadPct > 50 ? 'bg-yellow-500' : 'bg-green-500'
                            }`}
                            style={{ width: `${Math.max(loadPct, 2)}%` }}
                          />
                        </div>
                      </td>
                      <td className="py-2 px-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          isAtCapacity ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400'
                          : isIdle ? 'bg-gray-100 dark:bg-[#0D1117] text-gray-600 dark:text-gray-400'
                          : 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                        }`}>
                          {isAtCapacity ? 'At Capacity' : isIdle ? 'Idle' : 'Active'}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
            No workers reporting. Workers may still be starting up.
          </div>
        )}

        {(workerSettings.at_capacity_since || workerSettings.idle_since) && (
          <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-sm text-blue-700 dark:text-blue-400">
            {workerSettings.at_capacity_since && (
              <p>At capacity since: {new Date(workerSettings.at_capacity_since * 1000).toLocaleTimeString()}
                {' '}({Math.round((Date.now() / 1000 - workerSettings.at_capacity_since) / 60)}m ago — scales up at 5m)
              </p>
            )}
            {workerSettings.idle_since && (
              <p>Idle worker since: {new Date(workerSettings.idle_since * 1000).toLocaleTimeString()}
                {' '}({Math.round((Date.now() / 1000 - workerSettings.idle_since) / 60)}m ago — scales down at 10m)
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
