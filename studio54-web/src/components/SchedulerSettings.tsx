import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { schedulerApi } from '../api/client'
import type { SchedulableTask, ScheduledJob } from '../api/client'
import { FiPlus, FiTrash2, FiEdit } from 'react-icons/fi'

const DAYS_OF_WEEK = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export default function SchedulerSettings() {
  const queryClient = useQueryClient()

  const [showAddScheduledJobModal, setShowAddScheduledJobModal] = useState(false)
  const [editingScheduledJob, setEditingScheduledJob] = useState<ScheduledJob | null>(null)
  const [sjName, setSjName] = useState('')
  const [sjTaskKey, setSjTaskKey] = useState('')
  const [sjFrequency, setSjFrequency] = useState('daily')
  const [sjHour, setSjHour] = useState(2)
  const [sjDayOfWeek, setSjDayOfWeek] = useState<number | null>(null)
  const [sjDayOfMonth, setSjDayOfMonth] = useState<number | null>(null)
  const [sjParams, setSjParams] = useState<Record<string, any>>({})

  const { data: schedulableTasks } = useQuery<SchedulableTask[]>({
    queryKey: ['schedulable-tasks'],
    queryFn: () => schedulerApi.getTasks(),
  })

  const { data: scheduledJobs, isLoading: scheduledJobsLoading } = useQuery<ScheduledJob[]>({
    queryKey: ['scheduled-jobs'],
    queryFn: () => schedulerApi.getJobs(),
    refetchInterval: 30000,
  })

  const createScheduledJobMutation = useMutation({
    mutationFn: () => schedulerApi.createJob({
      name: sjName,
      task_key: sjTaskKey,
      frequency: sjFrequency,
      run_at_hour: sjHour,
      day_of_week: sjFrequency === 'weekly' ? sjDayOfWeek : null,
      day_of_month: ['monthly', 'quarterly'].includes(sjFrequency) ? sjDayOfMonth : null,
      task_params: Object.keys(sjParams).length > 0 ? sjParams : null,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduled-jobs'] })
      toast.success('Scheduled job created')
      setShowAddScheduledJobModal(false)
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to create scheduled job'),
  })

  const updateScheduledJobMutation = useMutation({
    mutationFn: (vars: { id: string; body: any }) => schedulerApi.updateJob(vars.id, vars.body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduled-jobs'] })
      toast.success('Scheduled job updated')
      setShowAddScheduledJobModal(false)
      setEditingScheduledJob(null)
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to update scheduled job'),
  })

  const deleteScheduledJobMutation = useMutation({
    mutationFn: (id: string) => schedulerApi.deleteJob(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['scheduled-jobs'] })
      toast.success('Scheduled job deleted')
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to delete'),
  })

  const runNowMutation = useMutation({
    mutationFn: (id: string) => schedulerApi.runNow(id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['scheduled-jobs'] })
      toast.success(data.message || 'Task dispatched')
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to run task'),
  })

  const resetSchedulerForm = () => {
    setSjName(''); setSjTaskKey(''); setSjFrequency('daily'); setSjHour(2)
    setSjDayOfWeek(null); setSjDayOfMonth(null); setSjParams({})
    setEditingScheduledJob(null)
  }

  const openEditScheduledJob = (job: ScheduledJob) => {
    setEditingScheduledJob(job)
    setSjName(job.name); setSjTaskKey(job.task_key); setSjFrequency(job.frequency)
    setSjHour(job.run_at_hour); setSjDayOfWeek(job.day_of_week); setSjDayOfMonth(job.day_of_month)
    setSjParams(job.task_params || {})
    setShowAddScheduledJobModal(true)
  }

  const handleSaveScheduledJob = () => {
    if (editingScheduledJob) {
      updateScheduledJobMutation.mutate({
        id: editingScheduledJob.id,
        body: {
          name: sjName,
          frequency: sjFrequency,
          run_at_hour: sjHour,
          day_of_week: sjFrequency === 'weekly' ? sjDayOfWeek : null,
          day_of_month: ['monthly', 'quarterly'].includes(sjFrequency) ? sjDayOfMonth : null,
          task_params: Object.keys(sjParams).length > 0 ? sjParams : null,
        }
      })
    } else {
      createScheduledJobMutation.mutate()
    }
  }

  return (
    <>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Job Scheduler</h3>
          <button onClick={() => { resetSchedulerForm(); setShowAddScheduledJobModal(true) }} className="btn btn-primary flex items-center gap-2">
            <FiPlus className="w-4 h-4" /> Add Scheduled Job
          </button>
        </div>

        <p className="text-sm text-gray-500 dark:text-gray-400">
          Schedule routine tasks to run automatically on a daily, weekly, monthly, or quarterly basis.
          The scheduler checks for due jobs every 5 minutes.
        </p>

        {scheduledJobsLoading ? (
          <div className="text-center py-8 text-gray-500">Loading...</div>
        ) : !scheduledJobs?.length ? (
          <div className="card p-8 text-center text-gray-500 dark:text-gray-400">
            No scheduled jobs configured. Click "Add Scheduled Job" to create one.
          </div>
        ) : (
          <div className="card overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50 dark:bg-[#0D1117]/50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Task</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Frequency</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Next Run</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Last Run</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Enabled</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
                {scheduledJobs.map((job) => (
                  <tr key={job.id} className="hover:bg-gray-50 dark:hover:bg-[#1C2128]/30">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900 dark:text-white">{job.name}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">{job.task_name}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300 capitalize">
                      {job.frequency}
                      {job.frequency === 'weekly' && job.day_of_week != null && ` (${DAYS_OF_WEEK[job.day_of_week]})`}
                      {['monthly', 'quarterly'].includes(job.frequency) && job.day_of_month != null && ` (day ${job.day_of_month})`}
                      {` @ ${String(job.run_at_hour).padStart(2, '0')}:00`}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
                      {job.next_run_at ? new Date(job.next_run_at).toLocaleString() : '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
                      {job.last_run_at ? new Date(job.last_run_at).toLocaleString() : 'Never'}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        job.last_status?.includes('dispatched') ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300' :
                        job.last_status?.includes('error') || job.last_status?.includes('failed') ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300' :
                        'bg-gray-100 text-gray-800 dark:bg-[#0D1117] dark:text-gray-300'
                      }`}>
                        {job.last_status || '-'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => updateScheduledJobMutation.mutate({ id: job.id, body: { enabled: !job.enabled } })}
                        className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                          job.enabled ? 'bg-[#FF1493]' : 'bg-gray-300 dark:bg-gray-600'
                        }`}
                      >
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition duration-200 ease-in-out ${
                          job.enabled ? 'translate-x-4' : 'translate-x-0'
                        }`} />
                      </button>
                    </td>
                    <td className="px-4 py-3 text-right space-x-2">
                      <button onClick={() => runNowMutation.mutate(job.id)} className="text-xs text-[#FF1493] hover:text-[#d10f7a] dark:text-[#ff4da6]" title="Run now">Run</button>
                      <button onClick={() => openEditScheduledJob(job)} className="text-xs text-gray-600 hover:text-gray-800 dark:text-gray-400" title="Edit"><FiEdit className="w-3.5 h-3.5 inline" /></button>
                      <button onClick={() => { if (confirm(`Delete "${job.name}"?`)) deleteScheduledJobMutation.mutate(job.id) }} className="text-xs text-red-600 hover:text-red-800 dark:text-red-400" title="Delete"><FiTrash2 className="w-3.5 h-3.5 inline" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add/Edit Scheduled Job Modal */}
      {showAddScheduledJobModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={(e) => { if (e.target === e.currentTarget) { setShowAddScheduledJobModal(false); resetSchedulerForm() } }}>
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-xl p-6 w-full max-w-lg mx-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              {editingScheduledJob ? 'Edit Scheduled Job' : 'Add Scheduled Job'}
            </h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name</label>
                <input type="text" value={sjName} onChange={(e) => setSjName(e.target.value)} placeholder="e.g. Nightly File Link Check" className="input w-full" />
              </div>
              {!editingScheduledJob && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Task</label>
                  <select
                    value={sjTaskKey}
                    onChange={(e) => {
                      setSjTaskKey(e.target.value); setSjParams({})
                      if (!sjName) {
                        const task = schedulableTasks?.find(t => t.key === e.target.value)
                        if (task) setSjName(task.name)
                      }
                    }}
                    className="input w-full"
                  >
                    <option value="">Select a task...</option>
                    {schedulableTasks?.map((task) => (
                      <option key={task.key} value={task.key}>{task.name} — {task.description}</option>
                    ))}
                  </select>
                </div>
              )}
              {sjTaskKey && (
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {schedulableTasks?.find(t => t.key === sjTaskKey)?.description}
                </p>
              )}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Frequency</label>
                <select value={sjFrequency} onChange={(e) => setSjFrequency(e.target.value)} className="input w-full">
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Run at hour (UTC)</label>
                <select value={sjHour} onChange={(e) => setSjHour(Number(e.target.value))} className="input w-full">
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={i}>{String(i).padStart(2, '0')}:00</option>
                  ))}
                </select>
              </div>
              {sjFrequency === 'weekly' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Day of Week</label>
                  <select value={sjDayOfWeek ?? 0} onChange={(e) => setSjDayOfWeek(Number(e.target.value))} className="input w-full">
                    {DAYS_OF_WEEK.map((day, i) => (<option key={i} value={i}>{day}</option>))}
                  </select>
                </div>
              )}
              {['monthly', 'quarterly'].includes(sjFrequency) && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Day of Month (1-28)</label>
                  <input type="number" min={1} max={28} value={sjDayOfMonth ?? 1} onChange={(e) => setSjDayOfMonth(Number(e.target.value))} className="input w-full" />
                </div>
              )}
              {sjTaskKey && schedulableTasks?.find(t => t.key === sjTaskKey)?.params?.map((param) => (
                <div key={param.key}>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{param.label}</label>
                  <input type="number" value={sjParams[param.key] ?? param.default} onChange={(e) => setSjParams(prev => ({ ...prev, [param.key]: Number(e.target.value) }))} className="input w-full" />
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => { setShowAddScheduledJobModal(false); resetSchedulerForm() }} className="btn btn-secondary">Cancel</button>
              <button onClick={handleSaveScheduledJob} className="btn btn-primary" disabled={!sjName || !sjTaskKey || createScheduledJobMutation.isPending || updateScheduledJobMutation.isPending}>
                {(createScheduledJobMutation.isPending || updateScheduledJobMutation.isPending) ? 'Saving...' : editingScheduledJob ? 'Save Changes' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
