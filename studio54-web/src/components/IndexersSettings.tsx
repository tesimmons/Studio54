import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { indexersApi } from '../api/client'
import { FiPlus, FiTrash2, FiCheck, FiX, FiAlertCircle, FiEdit, FiRefreshCw, FiEye, FiEyeOff } from 'react-icons/fi'
import type { Indexer } from '../types'

export default function IndexersSettings() {
  const queryClient = useQueryClient()

  const [showAddIndexerModal, setShowAddIndexerModal] = useState(false)
  const [showEditIndexerModal, setShowEditIndexerModal] = useState(false)
  const [editingIndexer, setEditingIndexer] = useState<Indexer | null>(null)

  const [indexerName, setIndexerName] = useState('')
  const [indexerBaseUrl, setIndexerBaseUrl] = useState('')
  const [indexerApiKey, setIndexerApiKey] = useState('')
  const [indexerPriority, setIndexerPriority] = useState(100)
  const [indexerEnabled, setIndexerEnabled] = useState(true)
  const [indexerTestResult, setIndexerTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({})
  const [testing, setTesting] = useState<string | null>(null)
  const [showIndexerApiKey, setShowIndexerApiKey] = useState(false)
  const [loadingApiKey, setLoadingApiKey] = useState(false)

  const { data: indexers, isLoading: indexersLoading } = useQuery<Indexer[]>({
    queryKey: ['indexers'],
    queryFn: () => indexersApi.list(false),
  })

  const testIndexerMutation = useMutation({
    mutationFn: async () => {
      return indexersApi.testConfig({
        name: indexerName,
        base_url: indexerBaseUrl,
        api_key: indexerApiKey,
        indexer_type: 'newznab',
        priority: indexerPriority,
        is_enabled: indexerEnabled,
        categories: [3000, 3010, 3020, 3030, 3040],
        rate_limit_per_second: 5,
      })
    },
    onSuccess: (result) => setIndexerTestResult(result),
    onError: () => setIndexerTestResult({ success: false, message: 'Test failed: Unable to connect to server' }),
  })

  const addIndexerMutation = useMutation({
    mutationFn: async () => {
      return indexersApi.add({
        name: indexerName,
        base_url: indexerBaseUrl,
        api_key: indexerApiKey,
        indexer_type: 'newznab',
        priority: indexerPriority,
        is_enabled: indexerEnabled,
        categories: [3000, 3010, 3020, 3030, 3040],
        rate_limit_per_second: 5,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['indexers'] })
      setShowAddIndexerModal(false)
      toast.success('Indexer added successfully')
      setIndexerName(''); setIndexerBaseUrl(''); setIndexerApiKey('')
      setIndexerPriority(100); setIndexerEnabled(true); setIndexerTestResult(null)
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to add indexer'),
  })

  const deleteIndexerMutation = useMutation({
    mutationFn: (indexerId: string) => indexersApi.delete(indexerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['indexers'] })
      toast.success('Indexer deleted successfully')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to delete indexer'),
  })

  const updateIndexerMutation = useMutation({
    mutationFn: async () => {
      if (!editingIndexer) throw new Error('No indexer selected')
      const updates: any = {
        name: indexerName,
        base_url: indexerBaseUrl,
        priority: indexerPriority,
        is_enabled: indexerEnabled,
      }
      if (indexerApiKey) updates.api_key = indexerApiKey
      return indexersApi.update(editingIndexer.id, updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['indexers'] })
      setShowEditIndexerModal(false)
      toast.success('Indexer updated successfully')
      setEditingIndexer(null)
      setIndexerName(''); setIndexerBaseUrl(''); setIndexerApiKey('')
      setIndexerPriority(100); setIndexerEnabled(true); setIndexerTestResult(null)
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to update indexer'),
  })

  const testExistingIndexer = async (indexerId: string) => {
    setTesting(indexerId)
    try {
      const result = await indexersApi.test(indexerId)
      setTestResults({ ...testResults, [indexerId]: result })
    } catch {
      setTestResults({ ...testResults, [indexerId]: { success: false, message: 'Test failed' } })
    } finally {
      setTesting(null)
    }
  }

  const openEditIndexerModal = async (indexer: Indexer) => {
    setEditingIndexer(indexer)
    setIndexerName(indexer.name)
    setIndexerBaseUrl(indexer.base_url)
    setIndexerPriority(indexer.priority)
    setIndexerEnabled(indexer.is_enabled)
    setIndexerTestResult(null)
    setShowIndexerApiKey(false)
    setShowEditIndexerModal(true)

    setLoadingApiKey(true)
    try {
      const result = await indexersApi.getApiKey(indexer.id)
      setIndexerApiKey(result.api_key)
    } catch {
      console.error('Failed to fetch API key')
      toast.error('Failed to load API key')
      setIndexerApiKey('')
    } finally {
      setLoadingApiKey(false)
    }
  }

  return (
    <>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Indexers</h2>
          <button className="btn btn-primary" onClick={() => setShowAddIndexerModal(true)}>
            <FiPlus className="w-4 h-4 mr-2" />
            Add Indexer
          </button>
        </div>

        {indexersLoading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
          </div>
        ) : indexers && indexers.length > 0 ? (
          <div className="space-y-3">
            {indexers.map((indexer) => (
              <div key={indexer.id} className="card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center space-x-3">
                      <h3 className="font-semibold text-gray-900 dark:text-white">{indexer.name}</h3>
                      {indexer.is_enabled ? (
                        <span className="badge badge-success">Enabled</span>
                      ) : (
                        <span className="badge badge-warning">Disabled</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">{indexer.base_url}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">Priority: {indexer.priority}</p>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => testExistingIndexer(indexer.id)}
                      className="btn btn-sm btn-secondary"
                      disabled={testing === indexer.id}
                    >
                      {testing === indexer.id ? (
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600" />
                      ) : (
                        <FiRefreshCw className="w-4 h-4" />
                      )}
                    </button>
                    <button onClick={() => openEditIndexerModal(indexer)} className="btn btn-sm btn-secondary">
                      <FiEdit className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => deleteIndexerMutation.mutate(indexer.id)}
                      className="btn btn-sm btn-danger"
                      disabled={deleteIndexerMutation.isPending}
                    >
                      <FiTrash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
                {testResults[indexer.id] && (
                  <div className={`mt-3 p-2 rounded text-sm ${
                    testResults[indexer.id].success
                      ? 'bg-success-100 dark:bg-success-900/20 text-success-800 dark:text-success-200'
                      : 'bg-danger-100 dark:bg-danger-900/20 text-danger-800 dark:text-danger-200'
                  }`}>
                    {testResults[indexer.id].message}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="card p-12 text-center">
            <FiAlertCircle className="w-12 h-12 text-gray-400 mx-auto mb-3" />
            <p className="text-gray-500 dark:text-gray-400">No indexers configured. Add an indexer to start searching.</p>
          </div>
        )}
      </div>

      {/* Add Indexer Modal */}
      {showAddIndexerModal && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          onClick={() => setShowAddIndexerModal(false)}
        >
          <div
            className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Add Indexer</h2>
              <button onClick={() => setShowAddIndexerModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
                <FiX className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Name</label>
                <input type="text" className="input w-full" value={indexerName} onChange={(e) => setIndexerName(e.target.value)} placeholder="NZBGeek" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Base URL</label>
                <input type="text" className="input w-full" value={indexerBaseUrl} onChange={(e) => setIndexerBaseUrl(e.target.value)} placeholder="https://api.nzbgeek.info" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">API Key</label>
                <input type="password" className="input w-full" value={indexerApiKey} onChange={(e) => setIndexerApiKey(e.target.value)} placeholder="Enter API key" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Priority</label>
                <input type="number" className="input w-full" value={indexerPriority} onChange={(e) => setIndexerPriority(parseInt(e.target.value))} min="1" max="100" />
              </div>
              <div className="flex items-center">
                <input type="checkbox" id="indexer-enabled" className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4" checked={indexerEnabled} onChange={(e) => setIndexerEnabled(e.target.checked)} />
                <label htmlFor="indexer-enabled" className="ml-2 block text-sm text-gray-700 dark:text-gray-300">Enabled</label>
              </div>
            </div>

            {indexerTestResult && (
              <div className={`mx-6 mb-4 p-3 rounded-lg ${
                indexerTestResult.success
                  ? 'bg-success-100 dark:bg-success-900/20 text-success-800 dark:text-success-200'
                  : 'bg-danger-100 dark:bg-danger-900/20 text-danger-800 dark:text-danger-200'
              }`}>
                <div className="flex items-start">
                  {indexerTestResult.success ? <FiCheck className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" /> : <FiX className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" />}
                  <div className="text-sm">{indexerTestResult.message}</div>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between p-6 border-t border-gray-200 dark:border-[#30363D]">
              <button onClick={() => testIndexerMutation.mutate()} className="btn btn-secondary" disabled={testIndexerMutation.isPending || !indexerName || !indexerBaseUrl || !indexerApiKey}>
                {testIndexerMutation.isPending ? (
                  <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>Testing...</>
                ) : (
                  <><FiCheck className="w-4 h-4 mr-2" />Test Connection</>
                )}
              </button>
              <div className="flex items-center space-x-3">
                <button onClick={() => setShowAddIndexerModal(false)} className="btn btn-secondary">Cancel</button>
                <button onClick={() => addIndexerMutation.mutate()} className="btn btn-primary" disabled={addIndexerMutation.isPending || !indexerName || !indexerBaseUrl || !indexerApiKey}>
                  {addIndexerMutation.isPending ? (
                    <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>Adding...</>
                  ) : (
                    <><FiCheck className="w-4 h-4 mr-2" />Add Indexer</>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit Indexer Modal */}
      {showEditIndexerModal && editingIndexer && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          onClick={() => setShowEditIndexerModal(false)}
        >
          <div
            className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Edit Indexer</h2>
              <button onClick={() => setShowEditIndexerModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
                <FiX className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Name</label>
                <input type="text" className="input w-full" value={indexerName} onChange={(e) => setIndexerName(e.target.value)} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Base URL</label>
                <input type="text" className="input w-full" value={indexerBaseUrl} onChange={(e) => setIndexerBaseUrl(e.target.value)} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">API Key</label>
                <div className="relative">
                  <input
                    type={showIndexerApiKey ? "text" : "password"}
                    className="input w-full pr-10"
                    value={loadingApiKey ? "Loading..." : indexerApiKey}
                    onChange={(e) => setIndexerApiKey(e.target.value)}
                    placeholder="API key"
                    disabled={loadingApiKey}
                  />
                  <button
                    type="button"
                    onClick={() => setShowIndexerApiKey(!showIndexerApiKey)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                    disabled={loadingApiKey}
                  >
                    {showIndexerApiKey ? <FiEyeOff size={18} /> : <FiEye size={18} />}
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Priority</label>
                <input type="number" className="input w-full" value={indexerPriority} onChange={(e) => setIndexerPriority(parseInt(e.target.value))} min="1" max="100" />
              </div>
              <div className="flex items-center">
                <input type="checkbox" id="edit-indexer-enabled" className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4" checked={indexerEnabled} onChange={(e) => setIndexerEnabled(e.target.checked)} />
                <label htmlFor="edit-indexer-enabled" className="ml-2 block text-sm text-gray-700 dark:text-gray-300">Enabled</label>
              </div>
            </div>

            {indexerTestResult && (
              <div className={`mx-6 mb-4 p-3 rounded-lg ${
                indexerTestResult.success
                  ? 'bg-success-100 dark:bg-success-900/20 text-success-800 dark:text-success-200'
                  : 'bg-danger-100 dark:bg-danger-900/20 text-danger-800 dark:text-danger-200'
              }`}>
                <div className="flex items-start">
                  {indexerTestResult.success ? <FiCheck className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" /> : <FiX className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" />}
                  <div className="text-sm">{indexerTestResult.message}</div>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between p-6 border-t border-gray-200 dark:border-[#30363D]">
              <button
                onClick={() => {
                  if (editingIndexer && !indexerApiKey) {
                    testExistingIndexer(editingIndexer.id)
                  } else {
                    testIndexerMutation.mutate()
                  }
                }}
                className="btn btn-secondary"
                disabled={testing === editingIndexer?.id || testIndexerMutation.isPending || !indexerName || !indexerBaseUrl}
              >
                {(testing === editingIndexer?.id || testIndexerMutation.isPending) ? (
                  <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>Testing...</>
                ) : (
                  <><FiRefreshCw className="w-4 h-4 mr-2" />Test Connection</>
                )}
              </button>
              <div className="flex items-center space-x-3">
                <button onClick={() => setShowEditIndexerModal(false)} className="btn btn-secondary">Cancel</button>
                <button onClick={() => updateIndexerMutation.mutate()} className="btn btn-primary" disabled={updateIndexerMutation.isPending || !indexerName || !indexerBaseUrl}>
                  {updateIndexerMutation.isPending ? (
                    <><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>Updating...</>
                  ) : (
                    <><FiCheck className="w-4 h-4 mr-2" />Update Indexer</>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
