import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { apiKeysApi } from '../api/client'
import type { ApiKeyStatus } from '../api/client'
import { FiEye, FiEyeOff, FiCheck, FiX, FiExternalLink, FiLoader, FiRefreshCw, FiEdit2, FiCalendar, FiAlertTriangle, FiAlertCircle } from 'react-icons/fi'

// ---------------------------------------------------------------------------
// Countdown / expiry helpers
// ---------------------------------------------------------------------------
function ExpiryBadge({ daysUntil, expiresAt }: { daysUntil: number; expiresAt: string }) {
  const expired = daysUntil < 0
  const critical = daysUntil >= 0 && daysUntil <= 30
  const warning = daysUntil > 30 && daysUntil <= 90

  const abs = Math.abs(daysUntil)
  const years = Math.floor(abs / 365)
  const months = Math.floor((abs % 365) / 30)
  const days = abs % 30

  const parts: string[] = []
  if (years > 0) parts.push(`${years}y`)
  if (months > 0) parts.push(`${months}mo`)
  if (days > 0 || parts.length === 0) parts.push(`${days}d`)
  const countdown = parts.join(' ')

  if (expired) {
    return (
      <div className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-red-500/15 text-red-500">
        <FiAlertCircle className="w-3.5 h-3.5 shrink-0" />
        Expired {countdown} ago — renew now
      </div>
    )
  }
  if (critical) {
    return (
      <div className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-red-500/15 text-red-500">
        <FiAlertCircle className="w-3.5 h-3.5 shrink-0" />
        Expires in {countdown} ({expiresAt})
      </div>
    )
  }
  if (warning) {
    return (
      <div className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-500/15 text-amber-500">
        <FiAlertTriangle className="w-3.5 h-3.5 shrink-0" />
        Expires in {countdown} ({expiresAt})
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-green-500/10 text-green-500">
      <FiCalendar className="w-3 h-3 shrink-0" />
      Expires in {countdown} ({expiresAt})
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline date editor
// ---------------------------------------------------------------------------
function InstalledAtRow({ keyDef, onSaved }: { keyDef: ApiKeyStatus; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(keyDef.installed_at ?? '')

  const mutation = useMutation({
    mutationFn: (d: string) => apiKeysApi.updateInstalledAt(keyDef.id, d),
    onSuccess: () => {
      toast.success('Installation date updated')
      setEditing(false)
      onSaved()
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to update date')
    },
  })

  if (!keyDef.configured) return null

  const label = keyDef.installed_at
    ? new Date(keyDef.installed_at + 'T00:00:00').toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
      })
    : 'Unknown'

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-1">
        <FiCalendar className="w-3 h-3" />
        Key installed:
      </span>

      {editing ? (
        <>
          <input
            type="date"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="input text-xs py-1 px-2 h-7"
            autoFocus
          />
          <button
            onClick={() => mutation.mutate(draft)}
            disabled={!draft || mutation.isPending}
            className="p-1.5 rounded text-green-600 hover:bg-green-500/10 disabled:opacity-50 transition-colors"
            title="Save date"
          >
            {mutation.isPending ? <FiLoader className="w-3.5 h-3.5 animate-spin" /> : <FiCheck className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={() => { setEditing(false); setDraft(keyDef.installed_at ?? '') }}
            className="p-1.5 rounded text-gray-400 hover:bg-gray-500/10 transition-colors"
            title="Cancel"
          >
            <FiX className="w-3.5 h-3.5" />
          </button>
        </>
      ) : (
        <>
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{label}</span>
          <button
            onClick={() => { setDraft(keyDef.installed_at ?? ''); setEditing(true) }}
            className="p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
            title="Edit installation date"
          >
            <FiEdit2 className="w-3 h-3" />
          </button>
        </>
      )}

      {/* Expiry countdown — only for keys with expiry tracking */}
      {keyDef.expiry_days && keyDef.expires_at && keyDef.days_until_expiry !== null && keyDef.days_until_expiry !== undefined && (
        <ExpiryBadge daysUntil={keyDef.days_until_expiry} expiresAt={keyDef.expires_at} />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Per-key row
// ---------------------------------------------------------------------------
function ApiKeyRow({ keyDef }: { keyDef: ApiKeyStatus }) {
  const qc = useQueryClient()

  const [inputValue, setInputValue] = useState('')
  const [showInput, setShowInput] = useState(false)
  const [showPreview, setShowPreview] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [testing, setTesting] = useState(false)

  const saveMutation = useMutation({
    mutationFn: (value: string) => apiKeysApi.save(keyDef.id, value),
    onSuccess: () => {
      toast.success(`${keyDef.label} API key saved — workers restarting`)
      setInputValue('')
      setShowInput(false)
      setTestResult(null)
      qc.invalidateQueries({ queryKey: ['api-keys'] })
    },
    onError: () => toast.error(`Failed to save ${keyDef.label} key`),
  })

  const removeMutation = useMutation({
    mutationFn: () => apiKeysApi.remove(keyDef.id),
    onSuccess: () => {
      toast.success(`${keyDef.label} API key removed`)
      setTestResult(null)
      qc.invalidateQueries({ queryKey: ['api-keys'] })
    },
    onError: () => toast.error(`Failed to remove ${keyDef.label} key`),
  })

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await apiKeysApi.test(keyDef.id)
      setTestResult(result)
    } catch {
      setTestResult({ success: false, message: 'Test request failed' })
    } finally {
      setTesting(false)
    }
  }

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    const v = inputValue.trim()
    if (v) saveMutation.mutate(v)
  }

  return (
    <div className="border border-gray-200 dark:border-[#30363D] rounded-xl p-5 space-y-3 bg-white dark:bg-[#0D1117]">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-semibold text-gray-900 dark:text-white">{keyDef.label}</h4>
            {keyDef.configured ? (
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-green-500/15 text-green-500">Configured</span>
            ) : (
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-gray-200 dark:bg-[#1C2128] text-gray-500">Not set</span>
            )}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{keyDef.description}</p>
        </div>
        <a
          href={keyDef.docs_url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 flex items-center gap-1 text-xs text-[#FF1493] hover:underline"
        >
          Get key <FiExternalLink className="w-3 h-3" />
        </a>
      </div>

      {/* Installation date + expiry countdown */}
      <InstalledAtRow
        keyDef={keyDef}
        onSaved={() => qc.invalidateQueries({ queryKey: ['api-keys'] })}
      />

      {/* Current key + actions */}
      {keyDef.configured && !showInput && (
        <div className="flex items-center gap-2 flex-wrap">
          {/* Masked preview */}
          <span className="font-mono text-sm bg-gray-100 dark:bg-[#161B22] px-3 py-1.5 rounded-lg text-gray-700 dark:text-gray-300 select-none">
            {showPreview ? keyDef.key_preview : '••••••••••••'}
          </span>
          <button
            onClick={() => setShowPreview(!showPreview)}
            className="p-1.5 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
            title={showPreview ? 'Hide preview' : 'Show last 4 chars'}
          >
            {showPreview ? <FiEyeOff className="w-3.5 h-3.5" /> : <FiEye className="w-3.5 h-3.5" />}
          </button>

          {/* Test button */}
          <button
            onClick={handleTest}
            disabled={testing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-gray-300 dark:border-[#30363D] text-gray-700 dark:text-gray-300 hover:border-[#FF1493]/50 hover:text-[#FF1493] transition-colors disabled:opacity-50"
          >
            {testing ? <FiLoader className="w-3 h-3 animate-spin" /> : <FiRefreshCw className="w-3 h-3" />}
            Test
          </button>

          {/* Update */}
          <button
            onClick={() => setShowInput(true)}
            className="px-3 py-1.5 text-xs rounded-lg border border-gray-300 dark:border-[#30363D] text-gray-700 dark:text-gray-300 hover:border-[#FF1493]/50 transition-colors"
          >
            Update
          </button>

          {/* Remove */}
          <button
            onClick={() => removeMutation.mutate()}
            disabled={removeMutation.isPending}
            className="px-3 py-1.5 text-xs rounded-lg border border-red-500/30 text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-50"
          >
            Remove
          </button>
        </div>
      )}

      {/* Input form — shown when not configured or updating */}
      {(!keyDef.configured || showInput) && (
        <form onSubmit={handleSave} className="flex items-center gap-2">
          <input
            type="password"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder={`Paste your ${keyDef.label} API key`}
            className="input flex-1 min-w-0 font-mono text-sm"
            autoFocus={showInput}
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || saveMutation.isPending}
            className="btn btn-primary text-sm"
          >
            {saveMutation.isPending ? 'Saving…' : 'Save'}
          </button>
          {showInput && (
            <button
              type="button"
              onClick={() => { setShowInput(false); setInputValue('') }}
              className="btn btn-secondary text-sm"
            >
              Cancel
            </button>
          )}
        </form>
      )}

      {/* Test result */}
      {testResult && (
        <div className={`flex items-start gap-2 text-xs px-3 py-2 rounded-lg ${
          testResult.success
            ? 'bg-green-500/10 text-green-600 dark:text-green-400'
            : 'bg-red-500/10 text-red-600 dark:text-red-400'
        }`}>
          {testResult.success
            ? <FiCheck className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            : <FiX className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          }
          {testResult.message}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function ApiKeysSettings() {
  const { data: keys, isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: () => apiKeysApi.list(),
    refetchOnWindowFocus: false,
  })

  if (isLoading) {
    return <div className="text-gray-500 dark:text-gray-400 text-sm">Loading…</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white">API Keys</h2>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Third-party API keys are stored in <span className="font-mono text-xs">studio54-keys.env</span> and
          are never committed to version control. Saving a key restarts the worker service automatically.
        </p>
      </div>

      <div className="space-y-3">
        {(keys ?? []).map((k) => (
          <ApiKeyRow key={k.id} keyDef={k} />
        ))}
      </div>
    </div>
  )
}
