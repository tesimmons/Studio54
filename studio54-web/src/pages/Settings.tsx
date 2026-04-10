import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast, { Toaster } from 'react-hot-toast'
import api, { notificationsApi, adminApi, settingsApi, authApi } from '../api/client'
import type { MusicBrainzSettings } from '../api/client'
import { FiPlus, FiTrash2, FiCheck, FiX, FiAlertCircle, FiEdit, FiEye, FiEyeOff, FiBell, FiSend, FiUsers, FiShield, FiSettings, FiFileText, FiChevronLeft, FiFilter, FiDownload } from 'react-icons/fi'
import type { NotificationProfile, AuthUser, UserRole } from '../types'
import { NOTIFICATION_EVENTS } from '../types'
import MediaManagement from '../components/MediaManagement'
import WorkersSettings from '../components/WorkersSettings'
import SchedulerSettings from '../components/SchedulerSettings'
import DownloadClientsSettings from '../components/DownloadClientsSettings'
import IndexersSettings from '../components/IndexersSettings'
import QualityProfilesSettings from '../components/QualityProfilesSettings'
import StorageMountsSettings from '../components/StorageMountsSettings'
import { useAuth } from '../contexts/AuthContext'

interface LoggingLevel {
  service: string
  level: string
  effective_level: number
}

interface LogEntry {
  job_id: string
  job_type: string
  description: string
  status: string
  created_at: string | null
  completed_at: string | null
  log_file_path: string
  current_action?: string
  source: string
}

interface LogListResponse {
  logs: LogEntry[]
  total: number
  offset: number
  limit: number
  job_types: { value: string; label: string }[]
}

function LoggingTab({
  loggingMessage, setLoggingMessage,
}: {
  logLevel?: string
  setLogLevel?: (l: string) => void
  loggingMessage: string | null
  setLoggingMessage: (m: string | null) => void
}) {
  const queryClient = useQueryClient()
  const [logTypeFilter, setLogTypeFilter] = useState('')
  const [logPage, setLogPage] = useState(0)
  const [viewingLogId, setViewingLogId] = useState<string | null>(null)
  const [viewingLogType, setViewingLogType] = useState<string>('')
  const LOG_PAGE_SIZE = 25

  // Live logs state
  const [liveLogLevel, setLiveLogLevel] = useState('')
  const [liveLogLogger, setLiveLogLogger] = useState('')
  const [showLiveLogs, setShowLiveLogs] = useState(false)

  const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

  const { data: loggingLevels } = useQuery<LoggingLevel[]>({
    queryKey: ['loggingLevels'],
    queryFn: async () => {
      const response = await api.get('/admin/logging')
      return response.data
    },
    refetchInterval: 30000,
  })

  const { data: loggerDescs } = useQuery<Record<string, string>>({
    queryKey: ['loggerDescriptions'],
    queryFn: async () => {
      const response = await api.get('/admin/logging/descriptions')
      return response.data.loggers
    },
    staleTime: 300000,
  })

  const { data: logList, isLoading: logsLoading } = useQuery<LogListResponse>({
    queryKey: ['admin-logs', logTypeFilter, logPage],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (logTypeFilter) params.set('job_type', logTypeFilter)
      params.set('limit', String(LOG_PAGE_SIZE))
      params.set('offset', String(logPage * LOG_PAGE_SIZE))
      const response = await api.get(`/admin/logs?${params}`)
      return response.data
    },
  })

  const { data: logContent, isLoading: contentLoading } = useQuery({
    queryKey: ['admin-log-content', viewingLogId],
    queryFn: async () => {
      const response = await api.get(`/admin/logs/${viewingLogId}/content?lines=1000`)
      return response.data
    },
    enabled: !!viewingLogId,
  })

  const { data: liveLogs, isLoading: liveLogsLoading } = useQuery<{ lines: string[]; total: number }>({
    queryKey: ['live-logs', liveLogLevel, liveLogLogger],
    queryFn: async () => {
      const params = new URLSearchParams()
      params.set('lines', '500')
      if (liveLogLevel) params.set('level', liveLogLevel)
      if (liveLogLogger) params.set('logger_name', liveLogLogger)
      const response = await api.get(`/admin/logging/live?${params}`)
      return response.data
    },
    enabled: showLiveLogs,
    refetchInterval: showLiveLogs ? 5000 : false,
  })

  const changeServiceLevel = useMutation({
    mutationFn: async ({ service, level }: { service: string; level: string }) => {
      const response = await api.post('/admin/logging', { service, level })
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['loggingLevels'] })
      setLoggingMessage(`${data.service} level changed to ${data.level}`)
      setTimeout(() => setLoggingMessage(null), 3000)
    },
  })

  const resetLogging = useMutation({
    mutationFn: async () => {
      const response = await api.post('/admin/logging/reset')
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['loggingLevels'] })
      setLoggingMessage('Logging levels reset to defaults')
      setTimeout(() => setLoggingMessage(null), 3000)
    },
  })

  const statusColor = (s: string) => {
    switch (s) {
      case 'completed': return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
      case 'failed': return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300'
      case 'running': return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300'
      case 'pending': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300'
      default: return 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300'
    }
  }

  const formatDate = (iso: string | null) => {
    if (!iso) return '—'
    const d = new Date(iso)
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  const levelBadgeColor = (level: string) => {
    switch (level) {
      case 'DEBUG': return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
      case 'INFO': return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300'
      case 'WARNING': return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300'
      case 'ERROR': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
      case 'CRITICAL': return 'bg-red-200 text-red-800 dark:bg-red-900/50 dark:text-red-200'
      default: return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
    }
  }

  const totalPages = logList ? Math.ceil(logList.total / LOG_PAGE_SIZE) : 0

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Logging</h2>

      {loggingMessage && (
        <div className="p-3 bg-green-100 dark:bg-green-900/30 border border-green-500 rounded-lg">
          <p className="text-sm text-green-800 dark:text-green-200">{loggingMessage}</p>
        </div>
      )}

      {/* Service Log Levels */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center">
            <FiSettings className="w-5 h-5 mr-2 text-blue-600 dark:text-blue-400" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Service Log Levels</h3>
          </div>
          <button
            onClick={() => resetLogging.mutate()}
            disabled={resetLogging.isPending}
            className="btn-secondary text-sm"
          >
            Reset All to Defaults
          </button>
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
          Each service logger can be set independently. Changes apply to all workers in real-time.
        </p>

        <div className="space-y-3">
          {loggingLevels?.map((logger) => (
            <div key={logger.service} className="flex items-center gap-4 py-2 border-b border-gray-100 dark:border-[#21262D] last:border-0">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-mono font-medium text-gray-900 dark:text-white">
                    {logger.service}
                  </span>
                  <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${levelBadgeColor(logger.level)}`}>
                    {logger.level}
                  </span>
                </div>
                {loggerDescs?.[logger.service] && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    {loggerDescs[logger.service]}
                  </p>
                )}
              </div>
              <select
                value={logger.level}
                onChange={(e) => changeServiceLevel.mutate({ service: logger.service, level: e.target.value })}
                disabled={changeServiceLevel.isPending}
                className="input text-sm w-32"
              >
                {LOG_LEVELS.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
            </div>
          ))}
        </div>
      </div>

      {/* Live Service Logs */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center">
            <FiEye className="w-5 h-5 mr-2 text-green-600 dark:text-green-400" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Live Service Logs</h3>
          </div>
          <button
            onClick={() => setShowLiveLogs(!showLiveLogs)}
            className={`text-sm px-3 py-1.5 rounded-lg font-medium transition-colors ${
              showLiveLogs
                ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
            }`}
          >
            {showLiveLogs ? 'Streaming...' : 'Start Streaming'}
          </button>
        </div>

        {showLiveLogs && (
          <>
            <div className="flex items-center gap-3 mb-3">
              <FiFilter className="w-4 h-4 text-gray-400" />
              <select
                value={liveLogLevel}
                onChange={(e) => setLiveLogLevel(e.target.value)}
                className="input text-sm"
              >
                <option value="">All Levels</option>
                {LOG_LEVELS.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
              <select
                value={liveLogLogger}
                onChange={(e) => setLiveLogLogger(e.target.value)}
                className="input text-sm"
              >
                <option value="">All Loggers</option>
                {loggingLevels?.map((l) => (
                  <option key={l.service} value={l.service}>{l.service}</option>
                ))}
              </select>
              <span className="text-xs text-gray-400 ml-auto">
                {liveLogs?.total || 0} lines — refreshes every 5s
              </span>
            </div>
            {liveLogsLoading && !liveLogs ? (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-green-500" />
              </div>
            ) : (
              <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-auto max-h-[500px] text-xs font-mono leading-relaxed whitespace-pre-wrap">
                {liveLogs?.lines?.length ? liveLogs.lines.join('\n') : 'No log output yet. Waiting for activity...'}
              </pre>
            )}
          </>
        )}

        {!showLiveLogs && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Click "Start Streaming" to view live service log output. Logs are buffered in memory (last 2,000 lines) and can be filtered by level or logger.
          </p>
        )}
      </div>

      {/* Log Files Viewer */}
      <div className="card p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center">
            <FiFileText className="w-5 h-5 mr-2 text-gray-600 dark:text-gray-400" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              {viewingLogId ? 'Log Viewer' : 'Job Log Files'}
            </h3>
          </div>
          {viewingLogId && (
            <button
              onClick={() => { setViewingLogId(null); setViewingLogType('') }}
              className="btn-secondary text-sm flex items-center gap-1"
            >
              <FiChevronLeft className="w-4 h-4" /> Back to List
            </button>
          )}
        </div>

        {viewingLogId ? (
          /* Log Content Viewer */
          <div>
            <div className="flex items-center gap-3 mb-3">
              <span className="text-sm text-gray-500 dark:text-gray-400">
                {viewingLogType}
              </span>
              <span className="text-xs font-mono text-gray-400 dark:text-gray-500">
                {viewingLogId}
              </span>
              {logContent?.total_lines != null && (
                <span className="text-xs text-gray-400">
                  {logContent.total_lines} lines
                </span>
              )}
              <a
                href={`${api.defaults.baseURL}/jobs/${viewingLogId}/log`}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto btn-secondary text-xs flex items-center gap-1"
              >
                <FiDownload className="w-3 h-3" /> Download
              </a>
            </div>
            {contentLoading ? (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500" />
              </div>
            ) : logContent?.log_available ? (
              <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-auto max-h-[600px] text-xs font-mono leading-relaxed whitespace-pre-wrap">
                {logContent.content}
              </pre>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400 py-4">Log file not available.</p>
            )}
          </div>
        ) : (
          /* Log File List */
          <div>
            <div className="flex items-center gap-3 mb-4">
              <FiFilter className="w-4 h-4 text-gray-400" />
              <select
                value={logTypeFilter}
                onChange={(e) => { setLogTypeFilter(e.target.value); setLogPage(0) }}
                className="input text-sm"
              >
                <option value="">All Job Types</option>
                {logList?.job_types?.map((jt) => (
                  <option key={jt.value} value={jt.value}>{jt.label}</option>
                ))}
              </select>
              <span className="text-sm text-gray-500 dark:text-gray-400 ml-auto">
                {logList?.total ?? 0} log files
              </span>
            </div>

            {logsLoading ? (
              <div className="flex justify-center py-8">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500" />
              </div>
            ) : !logList?.logs?.length ? (
              <p className="text-sm text-gray-500 dark:text-gray-400 py-4">No log files found.</p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="min-w-full">
                    <thead>
                      <tr className="border-b border-gray-200 dark:border-[#30363D]">
                        <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Type</th>
                        <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Description</th>
                        <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Status</th>
                        <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Date</th>
                        <th className="text-right py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {logList.logs.map((log) => (
                        <tr
                          key={log.job_id}
                          className="border-b border-gray-100 dark:border-[#21262D] hover:bg-gray-50 dark:hover:bg-[#161B22] cursor-pointer"
                          onClick={() => { setViewingLogId(log.job_id); setViewingLogType(log.description) }}
                        >
                          <td className="py-2 px-3">
                            <span className="text-xs font-mono bg-gray-100 dark:bg-[#161B22] text-gray-600 dark:text-gray-400 px-2 py-0.5 rounded">
                              {log.job_type}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-sm text-gray-700 dark:text-gray-300">
                            {log.description}
                          </td>
                          <td className="py-2 px-3">
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusColor(log.status)}`}>
                              {log.status}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">
                            {formatDate(log.created_at)}
                          </td>
                          <td className="py-2 px-3 text-right">
                            <button className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 text-sm">
                              View
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {totalPages > 1 && (
                  <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-200 dark:border-[#30363D]">
                    <button
                      onClick={() => setLogPage(p => Math.max(0, p - 1))}
                      disabled={logPage === 0}
                      className="btn-secondary text-sm disabled:opacity-40"
                    >
                      Previous
                    </button>
                    <span className="text-sm text-gray-500 dark:text-gray-400">
                      Page {logPage + 1} of {totalPages}
                    </span>
                    <button
                      onClick={() => setLogPage(p => Math.min(totalPages - 1, p + 1))}
                      disabled={logPage >= totalPages - 1}
                      className="btn-secondary text-sm disabled:opacity-40"
                    >
                      Next
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Settings() {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const [activeTab, setActiveTab] = useState<'media-management' | 'storage' | 'notifications' | 'musicbrainz' | 'users' | 'system' | 'download-clients' | 'indexers' | 'quality-profiles' | 'logging'>('media-management')

  // System tab state
  const [keepPlaylists, setKeepPlaylists] = useState(false)
  const [keepWatchedArtists, setKeepWatchedArtists] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [showGpuMonitoring, setShowGpuMonitoring] = useState(() => localStorage.getItem('studio54-show-gpu') === 'true')

  // Logging state
  const [logLevel, setLogLevel] = useState<string>('ERROR')
  const [loggingMessage, setLoggingMessage] = useState<string | null>(null)

  // Notification profile state
  const [showAddNotificationModal, setShowAddNotificationModal] = useState(false)
  const [editingNotification, setEditingNotification] = useState<NotificationProfile | null>(null)
  const [notifName, setNotifName] = useState('')
  const [notifProvider, setNotifProvider] = useState<'webhook' | 'discord' | 'slack'>('webhook')
  const [notifWebhookUrl, setNotifWebhookUrl] = useState('')
  const [notifEnabled, setNotifEnabled] = useState(true)
  const [notifEvents, setNotifEvents] = useState<string[]>([])

  // User management state
  const [showAddUserModal, setShowAddUserModal] = useState(false)
  const [showEditUserModal, setShowEditUserModal] = useState(false)
  const [editingUser, setEditingUser] = useState<AuthUser | null>(null)
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newDisplayName, setNewDisplayName] = useState('')
  const [newRole, setNewRole] = useState<UserRole>('partygoer')
  const [editDisplayName, setEditDisplayName] = useState('')
  const [editRole, setEditRole] = useState<UserRole>('partygoer')
  const [editPassword, setEditPassword] = useState('')
  const [editIsActive, setEditIsActive] = useState(true)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showEditPassword, setShowEditPassword] = useState(false)
  const [confirmDeleteUser, setConfirmDeleteUser] = useState<string | null>(null)

  // Fetch notification profiles
  const { data: notifications, isLoading: notificationsLoading } = useQuery<NotificationProfile[]>({
    queryKey: ['notifications'],
    queryFn: () => notificationsApi.list(),
    enabled: activeTab === 'notifications',
  })

  // Fetch MusicBrainz settings
  const { data: mbSettings, isLoading: mbSettingsLoading } = useQuery<MusicBrainzSettings>({
    queryKey: ['musicbrainzSettings'],
    queryFn: () => settingsApi.getMusicBrainz(),
    enabled: activeTab === 'musicbrainz',
    refetchInterval: activeTab === 'musicbrainz' ? 30000 : false,
  })

  const [mbTestResult, setMbTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [mbTesting, setMbTesting] = useState(false)

  // MusicBrainz search state
  const [mbSearchType, setMbSearchType] = useState<'artist' | 'album' | 'track'>('artist')
  const [mbSearchQuery, setMbSearchQuery] = useState('')
  const [mbArtistFilter, setMbArtistFilter] = useState('')
  const [mbSearchResults, setMbSearchResults] = useState<any[] | null>(null)
  const [mbSearching, setMbSearching] = useState(false)

  const updateMbSettingsMutation = useMutation({
    mutationFn: (settings: { local_db_enabled?: boolean; api_rate_limit?: number }) =>
      settingsApi.updateMusicBrainz(settings),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['musicbrainzSettings'] })
      toast.success('MusicBrainz settings updated')
    },
    onError: () => toast.error('Failed to update MusicBrainz settings'),
  })

  // Fetch users
  const { data: users, isLoading: usersLoading } = useQuery<AuthUser[]>({
    queryKey: ['users'],
    queryFn: () => authApi.listUsers(),
    enabled: activeTab === 'users',
  })

  const createUserMutation = useMutation({
    mutationFn: () => authApi.createUser({ username: newUsername, password: newPassword, display_name: newDisplayName || undefined, role: newRole }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast.success('User created')
      setShowAddUserModal(false)
      setNewUsername(''); setNewPassword(''); setNewDisplayName(''); setNewRole('partygoer')
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to create user'),
  })

  const updateUserMutation = useMutation({
    mutationFn: () => {
      if (!editingUser) throw new Error('No user selected')
      const updates: any = { display_name: editDisplayName }
      if (editingUser.id !== currentUser?.id) {
        updates.role = editRole
        updates.is_active = editIsActive
      }
      if (editPassword) updates.password = editPassword
      return authApi.updateUser(editingUser.id, updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast.success('User updated')
      setShowEditUserModal(false)
      setEditingUser(null)
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to update user'),
  })

  const deleteUserMutation = useMutation({
    mutationFn: (userId: string) => authApi.deleteUser(userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      toast.success('User deleted')
      setConfirmDeleteUser(null)
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to delete user'),
  })

  // Notification mutations
  const addNotificationMutation = useMutation({
    mutationFn: () => notificationsApi.create({
      name: notifName,
      provider: notifProvider,
      webhook_url: notifWebhookUrl,
      is_enabled: notifEnabled,
      events: notifEvents,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
      setShowAddNotificationModal(false)
      resetNotifForm()
      toast.success('Notification profile created')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to create notification profile'),
  })

  const updateNotificationMutation = useMutation({
    mutationFn: ({ id, updates }: { id: string; updates: any }) =>
      notificationsApi.update(id, updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
      toast.success('Notification profile updated')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to update notification profile'),
  })

  const deleteNotificationMutation = useMutation({
    mutationFn: (id: string) => notificationsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
      toast.success('Notification profile deleted')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to delete notification profile'),
  })

  const testNotificationMutation = useMutation({
    mutationFn: (id: string) => notificationsApi.test(id),
    onSuccess: (data) => {
      if (data.success) { toast.success(data.message) } else { toast.error(data.message) }
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Test failed'),
  })

  // Clear library mutation
  const clearLibraryMutation = useMutation({
    mutationFn: () => adminApi.clearLibrary({
      keep_playlists: keepPlaylists,
      keep_watched_artists: keepWatchedArtists,
    }),
    onSuccess: (data) => {
      toast.success(data.message)
      setShowClearConfirm(false)
      queryClient.invalidateQueries()
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to clear library')
      setShowClearConfirm(false)
    },
  })

  const resetNotifForm = () => {
    setNotifName(''); setNotifProvider('webhook'); setNotifWebhookUrl('')
    setNotifEnabled(true); setNotifEvents([]); setEditingNotification(null)
  }

  const openEditNotification = (profile: NotificationProfile) => {
    setEditingNotification(profile)
    setNotifName(profile.name); setNotifProvider(profile.provider)
    setNotifWebhookUrl(''); setNotifEnabled(profile.is_enabled)
    setNotifEvents(profile.events || [])
    setShowAddNotificationModal(true)
  }

  const handleSaveNotification = () => {
    if (editingNotification) {
      const updates: any = {
        name: notifName, provider: notifProvider,
        is_enabled: notifEnabled, events: notifEvents,
      }
      if (notifWebhookUrl) updates.webhook_url = notifWebhookUrl
      updateNotificationMutation.mutate({ id: editingNotification.id, updates })
      setShowAddNotificationModal(false)
      resetNotifForm()
    } else {
      addNotificationMutation.mutate()
    }
  }

  const toggleNotifEvent = (event: string) => {
    setNotifEvents(prev => prev.includes(event) ? prev.filter(e => e !== event) : [...prev, event])
  }

  return (
    <div className="space-y-6">
      <Toaster position="top-right" />

      {/* Header */}
      <div>
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Settings</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">Configure media management, notifications, and system settings</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-[#30363D]">
        <nav className="-mb-px flex flex-wrap gap-x-6 gap-y-0">
          {([
            { key: 'media-management' as const, label: 'Media Management' },
            { key: 'storage' as const, label: 'Storage' },
            { key: 'notifications' as const, label: 'Notifications' },
            { key: 'musicbrainz' as const, label: 'MusicBrainz' },
            { key: 'users' as const, label: 'Users' },
            { key: 'system' as const, label: 'System' },
            { key: 'download-clients' as const, label: 'Download Clients' },
            { key: 'indexers' as const, label: 'Indexers' },
            { key: 'quality-profiles' as const, label: 'Quality Profiles' },
            { key: 'logging' as const, label: 'Logging' },
          ]).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
                activeTab === key
                  ? 'border-[#FF1493] text-[#FF1493]'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div>
        {/* Media Management Tab */}
        {activeTab === 'media-management' && (
          <MediaManagement />
        )}

        {/* Storage Tab */}
        {activeTab === 'storage' && (
          <StorageMountsSettings />
        )}

        {/* Notifications Tab */}
        {activeTab === 'notifications' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Notifications</h2>
              <button className="btn btn-primary" onClick={() => { resetNotifForm(); setShowAddNotificationModal(true) }}>
                <FiPlus className="w-4 h-4 mr-2" />
                Add Notification
              </button>
            </div>

            {notificationsLoading ? (
              <div className="flex justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
              </div>
            ) : notifications && notifications.length > 0 ? (
              <div className="space-y-3">
                {notifications.map((profile) => (
                  <div key={profile.id} className="card p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          <FiBell className={`w-5 h-5 ${profile.is_enabled ? 'text-green-500' : 'text-gray-400'}`} />
                          <div>
                            <h3 className="font-medium text-gray-900 dark:text-white">{profile.name}</h3>
                            <p className="text-sm text-gray-500 dark:text-gray-400">
                              {profile.provider.charAt(0).toUpperCase() + profile.provider.slice(1)} &middot;{' '}
                              {(profile.events || []).length} event{(profile.events || []).length !== 1 ? 's' : ''}
                            </p>
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {(profile.events || []).map(event => (
                            <span key={event} className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-800 dark:bg-[#0D1117] dark:text-gray-300">
                              {NOTIFICATION_EVENTS.find(e => e.value === event)?.label || event}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 ml-4">
                        <button
                          onClick={() => updateNotificationMutation.mutate({ id: profile.id, updates: { is_enabled: !profile.is_enabled } })}
                          className={`p-2 rounded-lg ${profile.is_enabled ? 'text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20' : 'text-gray-400 hover:bg-gray-100 dark:hover:bg-[#1C2128]'}`}
                          title={profile.is_enabled ? 'Disable' : 'Enable'}
                        >
                          {profile.is_enabled ? <FiCheck className="w-4 h-4" /> : <FiX className="w-4 h-4" />}
                        </button>
                        <button onClick={() => testNotificationMutation.mutate(profile.id)} className="p-2 rounded-lg text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20" title="Send test notification" disabled={testNotificationMutation.isPending}>
                          <FiSend className="w-4 h-4" />
                        </button>
                        <button onClick={() => openEditNotification(profile)} className="p-2 rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-[#1C2128]" title="Edit">
                          <FiEdit className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => { if (confirm(`Delete notification profile "${profile.name}"?`)) deleteNotificationMutation.mutate(profile.id) }}
                          className="p-2 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20" title="Delete"
                        >
                          <FiTrash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <FiBell className="w-12 h-12 text-gray-400 mx-auto mb-3" />
                <p className="text-gray-500 dark:text-gray-400">No notification profiles configured.</p>
                <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
                  Add a webhook, Discord, or Slack endpoint to receive notifications.
                </p>
              </div>
            )}
          </div>
        )}

        {/* MusicBrainz Tab */}
        {activeTab === 'musicbrainz' && (
          <div className="space-y-6">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">MusicBrainz</h2>

            {mbSettingsLoading ? (
              <div className="text-gray-500 dark:text-gray-400">Loading...</div>
            ) : mbSettings ? (
              <>
                {/* Local Database Card */}
                <div className="card p-6">
                  <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">Local Database Mirror</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                    A local MusicBrainz database eliminates API rate limits, enabling parallel imports
                    and instant metadata lookups. Requires ~70 GB disk space.
                  </p>

                  <label className="flex items-center gap-3 cursor-pointer mb-4">
                    <input
                      type="checkbox"
                      checked={mbSettings.local_db_enabled}
                      onChange={(e) => updateMbSettingsMutation.mutate({ local_db_enabled: e.target.checked })}
                      className="h-4 w-4 rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
                    />
                    <span className="text-sm font-medium text-gray-900 dark:text-white">Use Local MusicBrainz Database</span>
                  </label>

                  <div className="flex items-center gap-2 mb-4">
                    <div className={`w-3 h-3 rounded-full ${
                      mbSettings.local_db_status === 'connected' ? 'bg-green-500' :
                      mbSettings.local_db_status === 'loading' ? 'bg-yellow-500 animate-pulse' :
                      mbSettings.local_db_status === 'disconnected' ? 'bg-red-500' :
                      'bg-gray-400'
                    }`} />
                    <span className="text-sm text-gray-700 dark:text-gray-300">
                      {mbSettings.local_db_status === 'connected' ? 'Connected' :
                       mbSettings.local_db_status === 'loading' ? 'Loading (initial data import in progress)' :
                       mbSettings.local_db_status === 'disconnected' ? 'Disconnected' :
                       'Not Configured'}
                    </span>
                    <button
                      onClick={async () => {
                        setMbTesting(true); setMbTestResult(null)
                        try {
                          const result = await settingsApi.testMusicBrainzConnection()
                          setMbTestResult(result)
                        } catch { setMbTestResult({ success: false, message: 'Connection test failed' }) }
                        setMbTesting(false)
                      }}
                      disabled={mbTesting}
                      className="ml-2 px-3 py-1 text-xs bg-gray-100 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-[#30363D] transition-colors"
                    >
                      {mbTesting ? 'Testing...' : 'Test Connection'}
                    </button>
                  </div>

                  {mbTestResult && (
                    <div className={`text-sm p-3 rounded mb-4 ${
                      mbTestResult.success
                        ? 'bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400'
                        : 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400'
                    }`}>
                      {mbTestResult.message}
                    </div>
                  )}

                  {mbSettings.local_db_stats && mbSettings.local_db_status === 'connected' && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                      <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3">
                        <div className="text-2xl font-bold text-gray-900 dark:text-white">
                          {(mbSettings.local_db_stats.artists / 1000000).toFixed(1)}M
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">Artists</div>
                      </div>
                      <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3">
                        <div className="text-2xl font-bold text-gray-900 dark:text-white">
                          {(mbSettings.local_db_stats.recordings / 1000000).toFixed(1)}M
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">Recordings</div>
                      </div>
                      <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3">
                        <div className="text-2xl font-bold text-gray-900 dark:text-white">
                          {(mbSettings.local_db_stats.releases / 1000000).toFixed(1)}M
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">Releases</div>
                      </div>
                      <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3">
                        <div className="text-sm font-medium text-gray-900 dark:text-white">
                          {mbSettings.local_db_stats.last_replication
                            ? new Date(mbSettings.local_db_stats.last_replication).toLocaleDateString()
                            : 'N/A'}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">Last Replication</div>
                      </div>
                    </div>
                  )}

                  {mbSettings.local_db_status === 'not_configured' && (
                    <div className="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                      <p className="text-sm text-blue-700 dark:text-blue-400 font-medium mb-2">Setup Instructions</p>
                      <p className="text-sm text-blue-600 dark:text-blue-300">Run the setup script from the project root:</p>
                      <code className="block mt-2 text-sm bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-200 p-2 rounded font-mono">
                        ./scripts/setup-musicbrainz-db.sh
                      </code>
                      <p className="text-xs text-blue-500 dark:text-blue-400 mt-2">
                        Requires a MetaBrainz replication token (free for personal use) and ~70 GB disk space.
                      </p>
                    </div>
                  )}
                </div>

                {/* API Rate Limit Card */}
                <div className="card p-6">
                  <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">API Rate Limit</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                    Rate limit for remote MusicBrainz API requests (used as fallback when local DB is unavailable).
                    MusicBrainz allows 1 request per second for well-behaved clients.
                  </p>
                  <div className="flex items-center gap-3">
                    <input
                      type="number"
                      value={mbSettings.api_rate_limit}
                      onChange={(e) => {
                        const val = parseFloat(e.target.value)
                        if (!isNaN(val) && val >= 0.1 && val <= 10) updateMbSettingsMutation.mutate({ api_rate_limit: val })
                      }}
                      min={0.1} max={10} step={0.1}
                      className="w-24 px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
                    />
                    <span className="text-sm text-gray-500 dark:text-gray-400">requests/second</span>
                  </div>
                </div>

                {/* Search Local Database Card */}
                {mbSettings.local_db_status === 'connected' && (
                  <div className="card p-6">
                    <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">Search Local Database</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                      Query the local MusicBrainz database directly for artists, albums, or tracks.
                    </p>

                    <div className="flex flex-col sm:flex-row gap-3 mb-4">
                      <select
                        value={mbSearchType}
                        onChange={(e) => {
                          setMbSearchType(e.target.value as 'artist' | 'album' | 'track')
                          setMbSearchResults(null)
                        }}
                        className="px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
                      >
                        <option value="artist">Artist</option>
                        <option value="album">Album</option>
                        <option value="track">Track</option>
                      </select>

                      <input
                        type="text"
                        value={mbSearchQuery}
                        onChange={(e) => setMbSearchQuery(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && mbSearchQuery.trim()) {
                            setMbSearching(true)
                            settingsApi.searchMusicBrainzLocal({
                              query: mbSearchQuery.trim(),
                              search_type: mbSearchType,
                              artist_filter: mbArtistFilter.trim() || undefined,
                              limit: 15,
                            }).then(r => setMbSearchResults(r.results))
                              .catch(() => toast.error('Search failed'))
                              .finally(() => setMbSearching(false))
                          }
                        }}
                        placeholder={`Search ${mbSearchType}s...`}
                        className="flex-1 px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
                      />

                      {mbSearchType !== 'artist' && (
                        <input
                          type="text"
                          value={mbArtistFilter}
                          onChange={(e) => setMbArtistFilter(e.target.value)}
                          placeholder="Artist filter (optional)"
                          className="sm:w-48 px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
                        />
                      )}

                      <button
                        onClick={() => {
                          if (!mbSearchQuery.trim()) return
                          setMbSearching(true)
                          settingsApi.searchMusicBrainzLocal({
                            query: mbSearchQuery.trim(),
                            search_type: mbSearchType,
                            artist_filter: mbArtistFilter.trim() || undefined,
                            limit: 15,
                          }).then(r => setMbSearchResults(r.results))
                            .catch(() => toast.error('Search failed'))
                            .finally(() => setMbSearching(false))
                        }}
                        disabled={mbSearching || !mbSearchQuery.trim()}
                        className="px-4 py-2 bg-[#FF1493] text-white rounded-lg text-sm hover:bg-[#d10f7a] disabled:opacity-50 transition-colors whitespace-nowrap"
                      >
                        {mbSearching ? 'Searching...' : 'Search'}
                      </button>
                    </div>

                    {/* Results Table */}
                    {mbSearchResults !== null && (
                      <div className="overflow-x-auto">
                        {mbSearchResults.length === 0 ? (
                          <p className="text-sm text-gray-500 dark:text-gray-400 py-4 text-center">No results found.</p>
                        ) : (
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="border-b border-gray-200 dark:border-[#30363D]">
                                {mbSearchType === 'artist' && (
                                  <>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Name</th>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Type</th>
                                    <th className="text-right py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Score</th>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">MBID</th>
                                  </>
                                )}
                                {mbSearchType === 'album' && (
                                  <>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Title</th>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Artist</th>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Type</th>
                                    <th className="text-center py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Year</th>
                                    <th className="text-right py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Score</th>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">MBID</th>
                                  </>
                                )}
                                {mbSearchType === 'track' && (
                                  <>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Title</th>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Artist</th>
                                    <th className="text-right py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Duration</th>
                                    <th className="text-right py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">Score</th>
                                    <th className="text-left py-2 px-2 text-gray-500 dark:text-gray-400 font-medium">MBID</th>
                                  </>
                                )}
                              </tr>
                            </thead>
                            <tbody>
                              {mbSearchResults.map((r: any, i: number) => (
                                <tr key={r.id + '-' + i} className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-[#1C2128]">
                                  {mbSearchType === 'artist' && (
                                    <>
                                      <td className="py-2 px-2 text-gray-900 dark:text-white font-medium">{r.name}</td>
                                      <td className="py-2 px-2 text-gray-500 dark:text-gray-400">{r.type || '-'}</td>
                                      <td className="py-2 px-2 text-right text-gray-500 dark:text-gray-400">{r.score}%</td>
                                      <td className="py-2 px-2 text-gray-400 dark:text-gray-500 font-mono text-xs truncate max-w-[200px]" title={r.id}>{r.id}</td>
                                    </>
                                  )}
                                  {mbSearchType === 'album' && (
                                    <>
                                      <td className="py-2 px-2 text-gray-900 dark:text-white font-medium">{r.title}</td>
                                      <td className="py-2 px-2 text-gray-500 dark:text-gray-400">{r.artist_name || '-'}</td>
                                      <td className="py-2 px-2 text-gray-500 dark:text-gray-400">{r.primary_type || '-'}</td>
                                      <td className="py-2 px-2 text-center text-gray-500 dark:text-gray-400">{r.first_release_year || '-'}</td>
                                      <td className="py-2 px-2 text-right text-gray-500 dark:text-gray-400">{r.score}%</td>
                                      <td className="py-2 px-2 text-gray-400 dark:text-gray-500 font-mono text-xs truncate max-w-[200px]" title={r.id}>{r.id}</td>
                                    </>
                                  )}
                                  {mbSearchType === 'track' && (
                                    <>
                                      <td className="py-2 px-2 text-gray-900 dark:text-white font-medium">{r.title}</td>
                                      <td className="py-2 px-2 text-gray-500 dark:text-gray-400">{r.artist_name || '-'}</td>
                                      <td className="py-2 px-2 text-right text-gray-500 dark:text-gray-400">
                                        {r.length ? `${Math.floor(r.length / 60000)}:${String(Math.floor((r.length % 60000) / 1000)).padStart(2, '0')}` : '-'}
                                      </td>
                                      <td className="py-2 px-2 text-right text-gray-500 dark:text-gray-400">{r.score}%</td>
                                      <td className="py-2 px-2 text-gray-400 dark:text-gray-500 font-mono text-xs truncate max-w-[200px]" title={r.id}>{r.id}</td>
                                    </>
                                  )}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <div className="text-red-500">Failed to load MusicBrainz settings</div>
            )}
          </div>
        )}

        {/* Users Tab */}
        {activeTab === 'users' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold text-gray-900 dark:text-white">User Management</h2>
              <button className="btn btn-primary" onClick={() => { setNewUsername(''); setNewPassword(''); setNewDisplayName(''); setNewRole('partygoer'); setShowNewPassword(false); setShowAddUserModal(true) }}>
                <FiPlus className="w-4 h-4 mr-2" />
                Add User
              </button>
            </div>

            {usersLoading ? (
              <div className="text-gray-500 dark:text-gray-400">Loading users...</div>
            ) : (
              <div className="card overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-[#30363D]">
                  <thead className="bg-gray-50 dark:bg-[#161B22]">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Username</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Display Name</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Role</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Last Login</th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-[#161B22] divide-y divide-gray-200 dark:divide-[#30363D]">
                    {users?.map((u) => (
                      <tr key={u.id}>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                          {u.username}
                          {u.id === currentUser?.id && (
                            <span className="ml-2 text-[10px] px-1.5 py-0.5 bg-[#FF1493]/10 dark:bg-[#FF1493]/15 text-[#d10f7a] dark:text-[#ff4da6] rounded font-semibold">YOU</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">{u.display_name || '—'}</td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className={`inline-flex px-2 py-0.5 rounded text-xs font-semibold ${
                            u.role === 'director' ? 'bg-amber-500/20 text-amber-400' :
                            u.role === 'dj' ? 'bg-blue-500/20 text-blue-400' :
                            'bg-green-500/20 text-green-400'
                          }`}>
                            {u.role === 'director' ? 'Club Director' : u.role === 'dj' ? 'DJ' : 'Partygoer'}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {u.is_active ? (
                            <span className="inline-flex items-center text-xs text-green-500"><FiCheck className="w-3 h-3 mr-1" /> Active</span>
                          ) : (
                            <span className="inline-flex items-center text-xs text-red-400"><FiX className="w-3 h-3 mr-1" /> Disabled</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                          {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : 'Never'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right space-x-2">
                          <button
                            onClick={() => {
                              setEditingUser(u); setEditDisplayName(u.display_name || '')
                              setEditRole(u.role); setEditIsActive(u.is_active)
                              setEditPassword(''); setShowEditPassword(false); setShowEditUserModal(true)
                            }}
                            className="text-gray-400 hover:text-[#FF1493] transition-colors" title="Edit user"
                          >
                            <FiEdit className="w-4 h-4" />
                          </button>
                          {u.id !== currentUser?.id && (
                            confirmDeleteUser === u.id ? (
                              <span className="inline-flex items-center space-x-1">
                                <button onClick={() => deleteUserMutation.mutate(u.id)} className="text-red-500 hover:text-red-400" title="Confirm delete"><FiCheck className="w-4 h-4" /></button>
                                <button onClick={() => setConfirmDeleteUser(null)} className="text-gray-400 hover:text-gray-300" title="Cancel"><FiX className="w-4 h-4" /></button>
                              </span>
                            ) : (
                              <button onClick={() => setConfirmDeleteUser(u.id)} className="text-gray-400 hover:text-red-500 transition-colors" title="Delete user">
                                <FiTrash2 className="w-4 h-4" />
                              </button>
                            )
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Add User Modal */}
        {showAddUserModal && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowAddUserModal(false)}>
            <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl max-w-md w-full mx-4" onClick={e => e.stopPropagation()}>
              <div className="p-6 border-b border-gray-200 dark:border-[#30363D]">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
                  <FiUsers className="w-5 h-5 mr-2 text-[#FF1493]" /> Add User
                </h3>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Username</label>
                  <input type="text" className="input w-full" value={newUsername} onChange={e => setNewUsername(e.target.value)} placeholder="username" autoFocus />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Password</label>
                  <div className="relative">
                    <input type={showNewPassword ? 'text' : 'password'} className="input w-full pr-10" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="password" />
                    <button type="button" onClick={() => setShowNewPassword(!showNewPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-300">
                      {showNewPassword ? <FiEyeOff className="w-4 h-4" /> : <FiEye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Display Name</label>
                  <input type="text" className="input w-full" value={newDisplayName} onChange={e => setNewDisplayName(e.target.value)} placeholder="optional" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Role</label>
                  <select className="input w-full" value={newRole} onChange={e => setNewRole(e.target.value as UserRole)}>
                    <option value="partygoer">Partygoer</option>
                    <option value="dj">DJ</option>
                    <option value="director">Club Director</option>
                  </select>
                  <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                    {newRole === 'director' ? 'Full access to everything' : newRole === 'dj' ? 'Can browse, play, download, edit metadata, sync artists' : 'Browse and listen only'}
                  </p>
                </div>
              </div>
              <div className="flex justify-end p-6 border-t border-gray-200 dark:border-[#30363D] space-x-3">
                <button onClick={() => setShowAddUserModal(false)} className="btn btn-secondary">Cancel</button>
                <button onClick={() => createUserMutation.mutate()} className="btn btn-primary" disabled={createUserMutation.isPending || !newUsername || !newPassword}>
                  {createUserMutation.isPending ? 'Creating...' : 'Create User'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Edit User Modal */}
        {showEditUserModal && editingUser && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowEditUserModal(false)}>
            <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl max-w-md w-full mx-4" onClick={e => e.stopPropagation()}>
              <div className="p-6 border-b border-gray-200 dark:border-[#30363D]">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
                  <FiEdit className="w-5 h-5 mr-2 text-[#FF1493]" /> Edit User: {editingUser.username}
                </h3>
              </div>
              <div className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Display Name</label>
                  <input type="text" className="input w-full" value={editDisplayName} onChange={e => setEditDisplayName(e.target.value)} />
                </div>
                {editingUser.id !== currentUser?.id && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Role</label>
                      <select className="input w-full" value={editRole} onChange={e => setEditRole(e.target.value as UserRole)}>
                        <option value="partygoer">Partygoer</option>
                        <option value="dj">DJ</option>
                        <option value="director">Club Director</option>
                      </select>
                    </div>
                    <div className="flex items-center gap-3">
                      <input type="checkbox" id="edit-active" checked={editIsActive} onChange={e => setEditIsActive(e.target.checked)} className="h-4 w-4 rounded border-gray-300 text-[#FF1493]" />
                      <label htmlFor="edit-active" className="text-sm text-gray-700 dark:text-gray-300">Account active</label>
                    </div>
                  </>
                )}
                {editingUser.id === currentUser?.id && (
                  <p className="text-xs text-amber-500 flex items-center"><FiShield className="w-3 h-3 mr-1" /> You cannot change your own role or deactivate your account</p>
                )}
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">New Password (leave blank to keep current)</label>
                  <div className="relative">
                    <input type={showEditPassword ? 'text' : 'password'} className="input w-full pr-10" value={editPassword} onChange={e => setEditPassword(e.target.value)} placeholder="unchanged" />
                    <button type="button" onClick={() => setShowEditPassword(!showEditPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-300">
                      {showEditPassword ? <FiEyeOff className="w-4 h-4" /> : <FiEye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
              </div>
              <div className="flex justify-end p-6 border-t border-gray-200 dark:border-[#30363D] space-x-3">
                <button onClick={() => setShowEditUserModal(false)} className="btn btn-secondary">Cancel</button>
                <button onClick={() => updateUserMutation.mutate()} className="btn btn-primary" disabled={updateUserMutation.isPending}>
                  {updateUserMutation.isPending ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Download Clients Tab */}
        {activeTab === 'download-clients' && <DownloadClientsSettings />}

        {/* Indexers Tab */}
        {activeTab === 'indexers' && <IndexersSettings />}

        {/* Quality Profiles Tab */}
        {activeTab === 'quality-profiles' && <QualityProfilesSettings />}

        {/* System Tab */}
        {activeTab === 'system' && (
          <div className="space-y-6">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white">System</h2>

            {/* GPU Monitoring Toggle */}
            <div className="card p-6">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">System Monitor</h3>
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={showGpuMonitoring}
                  onChange={(e) => {
                    const val = e.target.checked
                    setShowGpuMonitoring(val)
                    localStorage.setItem('studio54-show-gpu', val ? 'true' : 'false')
                  }}
                  className="mt-1 h-4 w-4 rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
                />
                <div>
                  <span className="text-sm font-medium text-gray-900 dark:text-white">Show GPU monitoring</span>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Enable GPU utilization display in the system monitor bar (requires GPU-enabled machine)
                  </p>
                </div>
              </label>
            </div>

            {/* Clear Library Card */}
            <div className="card p-6">
              <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-2">Clear Library Database</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
                Removes all artists, albums, tracks, downloads, and job history from the database.
                No files on disk will be deleted. Settings, indexers, download clients, root folders,
                and quality profiles are preserved.
              </p>

              <div className="space-y-4 mb-6">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" checked={keepPlaylists} onChange={(e) => setKeepPlaylists(e.target.checked)} className="mt-1 h-4 w-4 rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]" />
                  <div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">Keep playlists</span>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Playlist definitions will be preserved, but track associations will be cleared since tracks are deleted.</p>
                  </div>
                </label>
                <label className="flex items-start gap-3 cursor-pointer">
                  <input type="checkbox" checked={keepWatchedArtists} onChange={(e) => setKeepWatchedArtists(e.target.checked)} className="mt-1 h-4 w-4 rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]" />
                  <div>
                    <span className="text-sm font-medium text-gray-900 dark:text-white">Keep watched artists</span>
                    <p className="text-xs text-gray-500 dark:text-gray-400">Monitored artists will be preserved but their albums and tracks will be cleared.</p>
                  </div>
                </label>
              </div>

              <button
                onClick={() => setShowClearConfirm(true)}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm font-medium"
                disabled={clearLibraryMutation.isPending}
              >
                {clearLibraryMutation.isPending ? 'Clearing...' : 'Clear Library'}
              </button>
            </div>

            {/* Workers Section */}
            <WorkersSettings />

            {/* Scheduler Section */}
            <SchedulerSettings />
          </div>
        )}
        {/* Logging Tab */}
        {activeTab === 'logging' && (
          <LoggingTab
            logLevel={logLevel}
            setLogLevel={setLogLevel}
            loggingMessage={loggingMessage}
            setLoggingMessage={setLoggingMessage}
          />
        )}
      </div>

      {/* Clear Library Confirmation Modal */}
      {showClearConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-md w-full mx-4">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center">
                  <FiAlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Clear Library Database</h3>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">Are you sure? This will delete all library data including:</p>
              <ul className="text-sm text-gray-600 dark:text-gray-400 list-disc list-inside mb-4 space-y-1">
                {!keepWatchedArtists && <li>All artists</li>}
                {keepWatchedArtists && <li>Unmonitored artists (watched artists kept)</li>}
                <li>All albums and tracks</li>
                <li>All downloads and job history</li>
                {!keepPlaylists && <li>All playlists</li>}
              </ul>
              <p className="text-sm font-medium text-red-600 dark:text-red-400">This action cannot be undone.</p>
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-[#30363D]">
              <button onClick={() => setShowClearConfirm(false)} className="btn btn-secondary" disabled={clearLibraryMutation.isPending}>Cancel</button>
              <button
                onClick={() => clearLibraryMutation.mutate()}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm font-medium"
                disabled={clearLibraryMutation.isPending}
              >
                {clearLibraryMutation.isPending ? 'Clearing...' : 'Yes, Clear Library'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add/Edit Notification Modal */}
      {showAddNotificationModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={(e) => { if (e.target === e.currentTarget) { setShowAddNotificationModal(false); resetNotifForm() } }}>
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-xl p-6 w-full max-w-lg mx-4">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
              {editingNotification ? 'Edit Notification Profile' : 'Add Notification Profile'}
            </h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name</label>
                <input type="text" value={notifName} onChange={(e) => setNotifName(e.target.value)} className="input w-full" placeholder="My Discord Webhook" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Provider</label>
                <select value={notifProvider} onChange={(e) => setNotifProvider(e.target.value as 'webhook' | 'discord' | 'slack')} className="input w-full">
                  <option value="webhook">Webhook (Generic JSON)</option>
                  <option value="discord">Discord</option>
                  <option value="slack">Slack</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Webhook URL {editingNotification && <span className="text-gray-400">(leave blank to keep current)</span>}
                </label>
                <input
                  type="url" value={notifWebhookUrl} onChange={(e) => setNotifWebhookUrl(e.target.value)} className="input w-full"
                  placeholder={notifProvider === 'discord' ? 'https://discord.com/api/webhooks/...' : notifProvider === 'slack' ? 'https://hooks.slack.com/services/...' : 'https://example.com/webhook'}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Events</label>
                <div className="grid grid-cols-2 gap-2">
                  {NOTIFICATION_EVENTS.map(event => (
                    <label key={event.value} className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={notifEvents.includes(event.value)} onChange={() => toggleNotifEvent(event.value)} className="rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]" />
                      <span className="text-sm text-gray-700 dark:text-gray-300">{event.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={notifEnabled} onChange={(e) => setNotifEnabled(e.target.checked)} className="rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]" />
                <span className="text-sm text-gray-700 dark:text-gray-300">Enabled</span>
              </label>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button className="btn btn-secondary" onClick={() => { setShowAddNotificationModal(false); resetNotifForm() }}>Cancel</button>
              <button
                className="btn btn-primary" onClick={handleSaveNotification}
                disabled={(addNotificationMutation.isPending || updateNotificationMutation.isPending) || !notifName || (!editingNotification && !notifWebhookUrl)}
              >
                {(addNotificationMutation.isPending || updateNotificationMutation.isPending) ? 'Saving...' : editingNotification ? 'Save Changes' : 'Create Profile'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Settings
