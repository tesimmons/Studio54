import { useQuery } from '@tanstack/react-query'
import api from '../../../api/client'

interface StatisticsData {
  jobs_last_7d: Record<string, number>
}

const JOB_COLORS: Record<string, string> = {
  completed: 'text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-900/20',
  failed: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20',
  running: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20',
  stalled: 'text-yellow-600 dark:text-yellow-400 bg-yellow-50 dark:bg-yellow-900/20',
  pending: 'text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-[#161B22]',
  cancelled: 'text-gray-500 dark:text-gray-500 bg-gray-50 dark:bg-[#161B22]',
}

export default function JobsWidget() {
  const { data: stats } = useQuery<StatisticsData>({
    queryKey: ['statistics'],
    queryFn: async () => { const { data } = await api.get('/statistics'); return data },
    refetchInterval: 60000,
  })

  const jobs = stats?.jobs_last_7d || {}

  return (
    <div className="h-full p-4 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Jobs (Last 7 Days)</h2>
      {Object.keys(jobs).length > 0 ? (
        <div className="flex-1 overflow-y-auto space-y-3">
          {Object.entries(jobs)
            .sort(([, a], [, b]) => b - a)
            .map(([status, count]) => (
              <div key={status} className="flex items-center justify-between">
                <span className="text-sm text-gray-600 dark:text-gray-400 capitalize">{status}</span>
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${JOB_COLORS[status] || 'text-gray-600 bg-gray-100'}`}>
                  {count}
                </span>
              </div>
            ))}
        </div>
      ) : (
        <p className="text-gray-500 dark:text-gray-400">No jobs in the last 7 days</p>
      )}
    </div>
  )
}
