import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { storageMountsApi, systemApi } from '../api/client'
import type { StorageMount } from '../types'
import { FiPlus, FiTrash2, FiEdit, FiCheck, FiX, FiAlertTriangle, FiHardDrive, FiLock, FiRefreshCw } from 'react-icons/fi'

function StorageMountsSettings() {
  const queryClient = useQueryClient()

  // Modal state
  const [showAddModal, setShowAddModal] = useState(false)
  const [editingMount, setEditingMount] = useState<StorageMount | null>(null)

  // Form state
  const [formName, setFormName] = useState('')
  const [formHostPath, setFormHostPath] = useState('')
  const [formContainerPath, setFormContainerPath] = useState('')
  const [formReadOnly, setFormReadOnly] = useState(false)
  const [formMountType, setFormMountType] = useState<string>('generic')

  // Validation state
  const [pathValidation, setPathValidation] = useState<{ valid?: boolean; error?: string | null; free_space_gb?: number | null } | null>(null)
  const [validating, setValidating] = useState(false)

  // Apply/restart state
  const [showApplyConfirm, setShowApplyConfirm] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [restartError, setRestartError] = useState<string | null>(null)

  // Fetch mounts
  const { data, isLoading } = useQuery({
    queryKey: ['storageMounts'],
    queryFn: () => storageMountsApi.list(),
    refetchInterval: restarting ? false : 30000,
  })

  const mounts = data?.mounts ?? []
  const hasPendingChanges = data?.has_pending_changes ?? false
  const pendingCount = data?.pending_count ?? 0

  // Mutations
  const addMutation = useMutation({
    mutationFn: () => storageMountsApi.add({
      name: formName,
      host_path: formHostPath,
      container_path: formContainerPath,
      read_only: formReadOnly,
      mount_type: formMountType,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['storageMounts'] })
      toast.success('Mount added (pending apply)')
      closeModal()
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to add mount'),
  })

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!editingMount) throw new Error('No mount selected')
      return storageMountsApi.update(editingMount.id, {
        name: formName,
        read_only: formReadOnly,
        mount_type: formMountType,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['storageMounts'] })
      toast.success('Mount updated')
      closeModal()
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to update mount'),
  })

  const deleteMutation = useMutation({
    mutationFn: (mountId: string) => storageMountsApi.remove(mountId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['storageMounts'] })
      toast.success('Mount deleted')
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Failed to delete mount'),
  })

  const applyMutation = useMutation({
    mutationFn: () => storageMountsApi.apply(),
    onSuccess: () => {
      setShowApplyConfirm(false)
      setRestarting(true)
      setRestartError(null)
      pollHealth()
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to apply changes')
      setShowApplyConfirm(false)
    },
  })

  const rollbackMutation = useMutation({
    mutationFn: () => storageMountsApi.rollback(),
    onSuccess: () => {
      setRestarting(true)
      setRestartError(null)
      pollHealth()
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Rollback failed'),
  })

  // Poll /health after restart
  const pollHealth = () => {
    let attempts = 0
    const maxAttempts = 40 // 120s at 3s intervals
    const interval = setInterval(async () => {
      attempts++
      try {
        await systemApi.health()
        clearInterval(interval)
        setRestarting(false)
        toast.success('Service restarted successfully')
        queryClient.invalidateQueries({ queryKey: ['storageMounts'] })
      } catch {
        if (attempts >= maxAttempts) {
          clearInterval(interval)
          setRestarting(false)
          setRestartError('Service did not respond after 120 seconds.')
        }
      }
    }, 3000)
  }

  // Validate host path
  const handleValidatePath = async () => {
    if (!formHostPath) return
    setValidating(true)
    setPathValidation(null)
    try {
      const result = await storageMountsApi.validatePath(formHostPath)
      setPathValidation(result)
    } catch {
      setPathValidation({ valid: false, error: 'Validation request failed' })
    }
    setValidating(false)
  }

  // Auto-suggest container path from host path
  const handleHostPathChange = (value: string) => {
    setFormHostPath(value)
    setPathValidation(null)
    if (!formContainerPath || formContainerPath === '/' + (formHostPath.split('/').pop() || '')) {
      const basename = value.split('/').pop() || ''
      if (basename) {
        setFormContainerPath('/' + basename)
      }
    }
  }

  const closeModal = () => {
    setShowAddModal(false)
    setEditingMount(null)
    setFormName('')
    setFormHostPath('')
    setFormContainerPath('')
    setFormReadOnly(false)
    setFormMountType('generic')
    setPathValidation(null)
  }

  const openEditModal = (mount: StorageMount) => {
    setEditingMount(mount)
    setFormName(mount.name)
    setFormReadOnly(mount.read_only)
    setFormMountType(mount.mount_type)
    setShowAddModal(true)
  }

  const statusBadge = (s: string) => {
    switch (s) {
      case 'applied':
        return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300'
      case 'pending':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300'
      case 'failed':
        return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300'
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300'
    }
  }

  const typeBadge = (t: string) => {
    switch (t) {
      case 'music':
        return 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300'
      case 'audiobook':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300'
      default:
        return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
    }
  }

  // Restart overlay
  if (restarting) {
    return (
      <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
        <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl p-8 max-w-md w-full mx-4 text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493] mx-auto mb-4" />
          <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">
            Restarting Studio54...
          </h3>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Containers are being recreated with the new mount configuration.
            This typically takes ~30 seconds.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Storage Mounts</h2>
        <button
          className="btn btn-primary"
          onClick={() => { closeModal(); setShowAddModal(true) }}
        >
          <FiPlus className="w-4 h-4 mr-2" />
          Add Mount
        </button>
      </div>

      {/* Restart error */}
      {restartError && (
        <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <FiAlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
            <span className="font-medium text-red-800 dark:text-red-300">{restartError}</span>
          </div>
          <button
            onClick={() => rollbackMutation.mutate()}
            disabled={rollbackMutation.isPending}
            className="px-3 py-1.5 bg-red-600 text-white rounded-lg text-sm hover:bg-red-700 transition-colors"
          >
            {rollbackMutation.isPending ? 'Rolling back...' : 'Try Rollback'}
          </button>
        </div>
      )}

      {/* Pending changes banner */}
      {hasPendingChanges && (
        <div className="p-4 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 rounded-lg flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FiAlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400" />
            <span className="text-sm text-yellow-800 dark:text-yellow-300">
              {pendingCount} pending change{pendingCount !== 1 ? 's' : ''}. Apply to restart containers (~30s downtime).
            </span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowApplyConfirm(true)}
              className="px-3 py-1.5 bg-yellow-600 text-white rounded-lg text-sm hover:bg-yellow-700 transition-colors"
            >
              Apply Changes
            </button>
          </div>
        </div>
      )}

      {/* Mount cards */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]" />
        </div>
      ) : mounts.length === 0 ? (
        <div className="text-center py-12">
          <FiHardDrive className="w-12 h-12 text-gray-400 mx-auto mb-3" />
          <p className="text-gray-500 dark:text-gray-400">No storage mounts configured.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {mounts.map((mount) => (
            <div
              key={mount.id}
              className={`card p-4 ${mount.is_system ? 'opacity-60' : ''}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    {mount.is_system && <FiLock className="w-4 h-4 text-gray-400 flex-shrink-0" />}
                    <h3 className="font-medium text-gray-900 dark:text-white truncate">
                      {mount.name}
                    </h3>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${typeBadge(mount.mount_type)}`}>
                      {mount.mount_type}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusBadge(mount.status)}`}>
                      {mount.status}
                    </span>
                    {mount.read_only && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 font-medium">
                        read-only
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 dark:text-gray-400 font-mono truncate">
                    {mount.host_path} &rarr; {mount.container_path}
                  </p>
                  {mount.error_message && (
                    <p className="text-xs text-red-500 dark:text-red-400 mt-1">
                      {mount.error_message}
                    </p>
                  )}
                </div>
                {!mount.is_system && (
                  <div className="flex items-center gap-2 ml-4 flex-shrink-0">
                    <button
                      onClick={() => openEditModal(mount)}
                      className="p-2 rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-[#1C2128]"
                      title="Edit"
                    >
                      <FiEdit className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Delete mount "${mount.name}"? You must Apply Changes for this to take effect.`)) {
                          deleteMutation.mutate(mount.id)
                        }
                      }}
                      className="p-2 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                      title="Delete"
                    >
                      <FiTrash2 className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Apply Confirmation Modal */}
      {showApplyConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowApplyConfirm(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl max-w-md w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="flex-shrink-0 w-10 h-10 rounded-full bg-yellow-100 dark:bg-yellow-900/30 flex items-center justify-center">
                  <FiRefreshCw className="w-5 h-5 text-yellow-600 dark:text-yellow-400" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">Apply Mount Changes</h3>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
                This will update docker-compose.yml and restart the following containers:
              </p>
              <ul className="text-sm text-gray-600 dark:text-gray-400 list-disc list-inside mb-4 space-y-1">
                <li>studio54-service</li>
                <li>studio54-worker</li>
                <li>studio54-beat</li>
              </ul>
              <p className="text-sm text-yellow-600 dark:text-yellow-400 font-medium">
                Expect ~30 seconds of downtime.
              </p>
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 dark:border-[#30363D]">
              <button
                onClick={() => setShowApplyConfirm(false)}
                className="btn btn-secondary"
                disabled={applyMutation.isPending}
              >
                Cancel
              </button>
              <button
                onClick={() => applyMutation.mutate()}
                className="px-4 py-2 bg-[#FF1493] text-white rounded-lg hover:bg-[#d10f7a] transition-colors text-sm font-medium"
                disabled={applyMutation.isPending}
              >
                {applyMutation.isPending ? 'Applying...' : 'Apply & Restart'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add/Edit Mount Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => closeModal()}>
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl max-w-lg w-full mx-4" onClick={e => e.stopPropagation()}>
            <div className="p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h3 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center">
                <FiHardDrive className="w-5 h-5 mr-2 text-[#FF1493]" />
                {editingMount ? 'Edit Mount' : 'Add Storage Mount'}
              </h3>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name</label>
                <input
                  type="text"
                  className="input w-full"
                  value={formName}
                  onChange={e => setFormName(e.target.value)}
                  placeholder="e.g., Audiobooks Library"
                  autoFocus
                />
              </div>

              {!editingMount && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Host Path</label>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        className="input flex-1"
                        value={formHostPath}
                        onChange={e => handleHostPathChange(e.target.value)}
                        placeholder="/docker/studio54/audiobooks"
                      />
                      <button
                        onClick={handleValidatePath}
                        disabled={validating || !formHostPath}
                        className="px-3 py-2 bg-gray-100 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-[#30363D] transition-colors text-sm whitespace-nowrap disabled:opacity-50"
                      >
                        {validating ? 'Checking...' : 'Validate'}
                      </button>
                    </div>
                    {pathValidation && (
                      <div className={`mt-2 flex items-center gap-1.5 text-sm ${pathValidation.valid ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                        {pathValidation.valid ? (
                          <>
                            <FiCheck className="w-4 h-4" />
                            <span>Path exists{pathValidation.free_space_gb != null ? ` (${pathValidation.free_space_gb} GB free)` : ''}</span>
                          </>
                        ) : (
                          <>
                            <FiX className="w-4 h-4" />
                            <span>{pathValidation.error}</span>
                          </>
                        )}
                      </div>
                    )}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Container Path</label>
                    <input
                      type="text"
                      className="input w-full"
                      value={formContainerPath}
                      onChange={e => setFormContainerPath(e.target.value)}
                      placeholder="/audiobooks"
                    />
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      The path inside the container where this mount will be accessible.
                    </p>
                  </div>
                </>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Mount Type</label>
                <select
                  className="input w-full"
                  value={formMountType}
                  onChange={e => setFormMountType(e.target.value)}
                >
                  <option value="music">Music</option>
                  <option value="audiobook">Audiobook</option>
                  <option value="generic">Generic</option>
                </select>
              </div>

              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formReadOnly}
                  onChange={e => setFormReadOnly(e.target.checked)}
                  className="h-4 w-4 rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
                />
                <span className="text-sm text-gray-700 dark:text-gray-300">Read-only mount</span>
              </label>
            </div>
            <div className="flex justify-end p-6 border-t border-gray-200 dark:border-[#30363D] space-x-3">
              <button onClick={closeModal} className="btn btn-secondary">Cancel</button>
              <button
                onClick={() => editingMount ? updateMutation.mutate() : addMutation.mutate()}
                className="btn btn-primary"
                disabled={
                  (addMutation.isPending || updateMutation.isPending) ||
                  !formName ||
                  (!editingMount && (!formHostPath || !formContainerPath))
                }
              >
                {(addMutation.isPending || updateMutation.isPending) ? 'Saving...' : editingMount ? 'Save Changes' : 'Add Mount'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default StorageMountsSettings
