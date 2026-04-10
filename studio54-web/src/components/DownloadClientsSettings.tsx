import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { downloadClientsApi } from '../api/client'
import { FiPlus, FiTrash2, FiCheck, FiX, FiAlertCircle, FiEdit, FiRefreshCw, FiEye, FiEyeOff } from 'react-icons/fi'
import type { DownloadClient } from '../types'

export default function DownloadClientsSettings() {
  const queryClient = useQueryClient()

  const [showAddDownloadClientModal, setShowAddDownloadClientModal] = useState(false)
  const [showEditDownloadClientModal, setShowEditDownloadClientModal] = useState(false)
  const [editingClient, setEditingClient] = useState<DownloadClient | null>(null)

  const [clientName, setClientName] = useState('')
  const [clientType, setClientType] = useState('sabnzbd')
  const [clientHost, setClientHost] = useState('')
  const [clientPort, setClientPort] = useState(8080)
  const [clientUseSsl, setClientUseSsl] = useState(false)
  const [clientApiKey, setClientApiKey] = useState('')
  const [clientCategory, setClientCategory] = useState('music')
  const [clientIsDefault, setClientIsDefault] = useState(false)
  const [clientTestResult, setClientTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const [testResults, setTestResults] = useState<Record<string, { success: boolean; message: string }>>({})
  const [testing, setTesting] = useState<string | null>(null)
  const [showClientApiKey, setShowClientApiKey] = useState(false)
  const [loadingApiKey, setLoadingApiKey] = useState(false)

  const { data: downloadClients, isLoading: downloadClientsLoading } = useQuery<DownloadClient[]>({
    queryKey: ['downloadClients'],
    queryFn: () => downloadClientsApi.list(false),
  })

  const testDownloadClientMutation = useMutation({
    mutationFn: async () => {
      return downloadClientsApi.testConfig({
        name: clientName,
        client_type: clientType,
        host: clientHost,
        port: clientPort,
        use_ssl: clientUseSsl,
        api_key: clientApiKey,
        category: clientCategory,
        priority: 100,
        is_enabled: true,
        is_default: clientIsDefault,
      })
    },
    onSuccess: (result) => setClientTestResult(result),
    onError: () => setClientTestResult({ success: false, message: 'Test failed: Unable to connect to server' }),
  })

  const addDownloadClientMutation = useMutation({
    mutationFn: async () => {
      return downloadClientsApi.add({
        name: clientName,
        client_type: clientType,
        host: clientHost,
        port: clientPort,
        use_ssl: clientUseSsl,
        api_key: clientApiKey,
        category: clientCategory,
        priority: 100,
        is_enabled: true,
        is_default: clientIsDefault,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downloadClients'] })
      setShowAddDownloadClientModal(false)
      toast.success('Download client added successfully')
      setClientName(''); setClientType('sabnzbd'); setClientHost('')
      setClientPort(8080); setClientUseSsl(false); setClientApiKey('')
      setClientCategory('music'); setClientIsDefault(false); setClientTestResult(null)
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to add download client'),
  })

  const deleteDownloadClientMutation = useMutation({
    mutationFn: (clientId: string) => downloadClientsApi.delete(clientId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downloadClients'] })
      toast.success('Download client deleted successfully')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to delete download client'),
  })

  const updateDownloadClientMutation = useMutation({
    mutationFn: async () => {
      if (!editingClient) throw new Error('No client selected')
      const updates: any = {
        name: clientName,
        host: clientHost,
        port: clientPort,
        use_ssl: clientUseSsl,
        category: clientCategory,
        is_enabled: true,
        is_default: clientIsDefault,
      }
      if (clientApiKey) updates.api_key = clientApiKey
      return downloadClientsApi.update(editingClient.id, updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['downloadClients'] })
      setShowEditDownloadClientModal(false)
      toast.success('Download client updated successfully')
      setEditingClient(null)
      setClientName(''); setClientHost(''); setClientPort(8080)
      setClientUseSsl(false); setClientApiKey(''); setClientCategory('music')
      setClientIsDefault(false); setClientTestResult(null)
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to update download client'),
  })

  const testExistingClient = async (clientId: string) => {
    setTesting(clientId)
    try {
      const result = await downloadClientsApi.test(clientId)
      setTestResults({ ...testResults, [clientId]: result })
    } catch {
      setTestResults({ ...testResults, [clientId]: { success: false, message: 'Test failed' } })
    } finally {
      setTesting(null)
    }
  }

  const openEditClientModal = async (client: DownloadClient) => {
    setEditingClient(client)
    setClientName(client.name)
    setClientHost(client.host)
    setClientPort(client.port)
    setClientUseSsl(client.use_ssl)
    setClientCategory(client.category)
    setClientIsDefault(client.is_default)
    setClientTestResult(null)
    setShowClientApiKey(false)
    setShowEditDownloadClientModal(true)

    setLoadingApiKey(true)
    try {
      const result = await downloadClientsApi.getApiKey(client.id)
      setClientApiKey(result.api_key)
    } catch {
      console.error('Failed to fetch API key')
      toast.error('Failed to load API key')
      setClientApiKey('')
    } finally {
      setLoadingApiKey(false)
    }
  }

  return (
    <>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Download Clients</h2>
          <button className="btn btn-primary" onClick={() => setShowAddDownloadClientModal(true)}>
            <FiPlus className="w-4 h-4 mr-2" />
            Add Download Client
          </button>
        </div>

        {downloadClientsLoading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
          </div>
        ) : downloadClients && downloadClients.length > 0 ? (
          <div className="space-y-3">
            {downloadClients.map((client) => (
              <div key={client.id} className="card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center space-x-3">
                      <h3 className="font-semibold text-gray-900 dark:text-white">{client.name}</h3>
                      {client.is_enabled ? (
                        <span className="badge badge-success">Enabled</span>
                      ) : (
                        <span className="badge badge-warning">Disabled</span>
                      )}
                      {client.is_default && <span className="badge badge-primary">Default</span>}
                    </div>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                      {client.client_type.toUpperCase()} - {client.host}:{client.port}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">Category: {client.category}</p>
                  </div>
                  <div className="flex items-center space-x-2">
                    <button onClick={() => testExistingClient(client.id)} className="btn btn-sm btn-secondary" disabled={testing === client.id}>
                      {testing === client.id ? (
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600" />
                      ) : (
                        <FiRefreshCw className="w-4 h-4" />
                      )}
                    </button>
                    <button onClick={() => openEditClientModal(client)} className="btn btn-sm btn-secondary">
                      <FiEdit className="w-4 h-4" />
                    </button>
                    <button onClick={() => deleteDownloadClientMutation.mutate(client.id)} className="btn btn-sm btn-danger" disabled={deleteDownloadClientMutation.isPending}>
                      <FiTrash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
                {testResults[client.id] && (
                  <div className={`mt-3 p-2 rounded text-sm ${
                    testResults[client.id].success
                      ? 'bg-success-100 dark:bg-success-900/20 text-success-800 dark:text-success-200'
                      : 'bg-danger-100 dark:bg-danger-900/20 text-danger-800 dark:text-danger-200'
                  }`}>
                    {testResults[client.id].message}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="card p-12 text-center">
            <FiAlertCircle className="w-12 h-12 text-gray-400 mx-auto mb-3" />
            <p className="text-gray-500 dark:text-gray-400">No download clients configured. Add a client to enable downloads.</p>
          </div>
        )}
      </div>

      {/* Add Download Client Modal */}
      {showAddDownloadClientModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowAddDownloadClientModal(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Add Download Client</h2>
              <button onClick={() => setShowAddDownloadClientModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><FiX className="w-6 h-6" /></button>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Name</label>
                <input type="text" className="input w-full" value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="SABnzbd" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Client Type</label>
                <select className="input w-full" value={clientType} onChange={(e) => setClientType(e.target.value)}>
                  <option value="sabnzbd">SABnzbd</option>
                  <option value="nzbget">NZBGet</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Host</label>
                <input type="text" className="input w-full" value={clientHost} onChange={(e) => setClientHost(e.target.value)} placeholder="192.168.150.99" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Port</label>
                <input type="number" className="input w-full" value={clientPort} onChange={(e) => setClientPort(parseInt(e.target.value))} min="1" max="65535" />
              </div>
              <div className="flex items-center">
                <input type="checkbox" id="client-use-ssl" className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4" checked={clientUseSsl} onChange={(e) => setClientUseSsl(e.target.checked)} />
                <label htmlFor="client-use-ssl" className="ml-2 block text-sm text-gray-700 dark:text-gray-300">Use SSL</label>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">API Key</label>
                <input type="password" className="input w-full" value={clientApiKey} onChange={(e) => setClientApiKey(e.target.value)} placeholder="Enter API key" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Category</label>
                <input type="text" className="input w-full" value={clientCategory} onChange={(e) => setClientCategory(e.target.value)} placeholder="music" />
              </div>
              <div className="flex items-center">
                <input type="checkbox" id="client-is-default" className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4" checked={clientIsDefault} onChange={(e) => setClientIsDefault(e.target.checked)} />
                <label htmlFor="client-is-default" className="ml-2 block text-sm text-gray-700 dark:text-gray-300">Set as default</label>
              </div>
            </div>
            {clientTestResult && (
              <div className={`mx-6 mb-4 p-3 rounded-lg ${
                clientTestResult.success ? 'bg-success-100 dark:bg-success-900/20 text-success-800 dark:text-success-200' : 'bg-danger-100 dark:bg-danger-900/20 text-danger-800 dark:text-danger-200'
              }`}>
                <div className="flex items-start">
                  {clientTestResult.success ? <FiCheck className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" /> : <FiX className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" />}
                  <div className="text-sm">{clientTestResult.message}</div>
                </div>
              </div>
            )}
            <div className="flex items-center justify-between p-6 border-t border-gray-200 dark:border-[#30363D]">
              <button onClick={() => testDownloadClientMutation.mutate()} className="btn btn-secondary" disabled={testDownloadClientMutation.isPending || !clientName || !clientHost || !clientApiKey}>
                {testDownloadClientMutation.isPending ? (<><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>Testing...</>) : (<><FiCheck className="w-4 h-4 mr-2" />Test Connection</>)}
              </button>
              <div className="flex items-center space-x-3">
                <button onClick={() => setShowAddDownloadClientModal(false)} className="btn btn-secondary">Cancel</button>
                <button onClick={() => addDownloadClientMutation.mutate()} className="btn btn-primary" disabled={addDownloadClientMutation.isPending || !clientName || !clientHost || !clientApiKey}>
                  {addDownloadClientMutation.isPending ? (<><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>Adding...</>) : (<><FiCheck className="w-4 h-4 mr-2" />Add Client</>)}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit Download Client Modal */}
      {showEditDownloadClientModal && editingClient && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowEditDownloadClientModal(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Edit Download Client</h2>
              <button onClick={() => setShowEditDownloadClientModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><FiX className="w-6 h-6" /></button>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Name</label>
                <input type="text" className="input w-full" value={clientName} onChange={(e) => setClientName(e.target.value)} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Host</label>
                <input type="text" className="input w-full" value={clientHost} onChange={(e) => setClientHost(e.target.value)} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Port</label>
                <input type="number" className="input w-full" value={clientPort} onChange={(e) => setClientPort(parseInt(e.target.value))} />
              </div>
              <div className="flex items-center">
                <input type="checkbox" id="edit-client-use-ssl" className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4" checked={clientUseSsl} onChange={(e) => setClientUseSsl(e.target.checked)} />
                <label htmlFor="edit-client-use-ssl" className="ml-2 block text-sm text-gray-700 dark:text-gray-300">Use SSL</label>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">API Key</label>
                <div className="relative">
                  <input type={showClientApiKey ? "text" : "password"} className="input w-full pr-10" value={loadingApiKey ? "Loading..." : clientApiKey} onChange={(e) => setClientApiKey(e.target.value)} placeholder="API key" disabled={loadingApiKey} />
                  <button type="button" onClick={() => setShowClientApiKey(!showClientApiKey)} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200" disabled={loadingApiKey}>
                    {showClientApiKey ? <FiEyeOff size={18} /> : <FiEye size={18} />}
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Category</label>
                <input type="text" className="input w-full" value={clientCategory} onChange={(e) => setClientCategory(e.target.value)} />
              </div>
              <div className="flex items-center">
                <input type="checkbox" id="edit-client-is-default" className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4" checked={clientIsDefault} onChange={(e) => setClientIsDefault(e.target.checked)} />
                <label htmlFor="edit-client-is-default" className="ml-2 block text-sm text-gray-700 dark:text-gray-300">Set as default</label>
              </div>
            </div>
            {clientTestResult && (
              <div className={`mx-6 mb-4 p-3 rounded-lg ${
                clientTestResult.success ? 'bg-success-100 dark:bg-success-900/20 text-success-800 dark:text-success-200' : 'bg-danger-100 dark:bg-danger-900/20 text-danger-800 dark:text-danger-200'
              }`}>
                <div className="flex items-start">
                  {clientTestResult.success ? <FiCheck className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" /> : <FiX className="w-5 h-5 mr-2 flex-shrink-0 mt-0.5" />}
                  <div className="text-sm">{clientTestResult.message}</div>
                </div>
              </div>
            )}
            <div className="flex items-center justify-between p-6 border-t border-gray-200 dark:border-[#30363D]">
              <button
                onClick={() => {
                  if (editingClient && !clientApiKey) { testExistingClient(editingClient.id) } else { testDownloadClientMutation.mutate() }
                }}
                className="btn btn-secondary"
                disabled={testing === editingClient?.id || testDownloadClientMutation.isPending || !clientName || !clientHost}
              >
                {(testing === editingClient?.id || testDownloadClientMutation.isPending) ? (<><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-gray-600 mr-2"></div>Testing...</>) : (<><FiRefreshCw className="w-4 h-4 mr-2" />Test Connection</>)}
              </button>
              <div className="flex items-center space-x-3">
                <button onClick={() => setShowEditDownloadClientModal(false)} className="btn btn-secondary">Cancel</button>
                <button onClick={() => updateDownloadClientMutation.mutate()} className="btn btn-primary" disabled={updateDownloadClientMutation.isPending || !clientName || !clientHost}>
                  {updateDownloadClientMutation.isPending ? (<><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>Updating...</>) : (<><FiCheck className="w-4 h-4 mr-2" />Update Client</>)}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
