# Download Management UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete download management UI: active queue dashboard with pause/resume/remove actions, a Radarr-style manual search modal on album pages, enhanced history, blacklist management, and pending releases — all backed by existing APIs.

**Architecture:** All backend APIs already exist; this is a pure frontend build plus one small backend enrichment. New components are extracted into focused files rather than stuffed into the already-large Activity.tsx (61KB). The Activity page gets two new tabs (Queue, Blacklist) wired to new child components. AlbumDetail gets a Manual Search button that opens a new modal component.

**Tech Stack:** React 18 + TypeScript, React Query 5 (TanStack), axios, Tailwind CSS, react-hot-toast, react-router-dom 6, Material-UI icons (via react-icons/fi)

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `app/models/download_decision.py` | Add age_days, size_mb, format, bitrate to DownloadDecision.to_dict() |
| Modify | `studio54-web/src/types/index.ts` | Add TrackedDownloadItem, ManualSearchDecision, BlacklistEntry, PendingRelease interfaces |
| Modify | `studio54-web/src/api/client.ts` | Add queueApi and extend searchApi |
| Create | `studio54-web/src/components/ManualSearchModal.tsx` | Full search-results table + grab action |
| Modify | `studio54-web/src/pages/AlbumDetail.tsx` | Wire in Manual Search button + modal |
| Create | `studio54-web/src/components/activity/DownloadQueueTab.tsx` | Active queue table with actions |
| Create | `studio54-web/src/components/activity/PendingSection.tsx` | Pending releases list |
| Create | `studio54-web/src/components/activity/BlacklistSection.tsx` | Blacklist table with remove |
| Modify | `studio54-web/src/pages/Activity.tsx` | Add Queue + Blacklist tabs, import new components |

---

## Task 1: Enrich DownloadDecision.to_dict() with full release fields

The existing `to_dict()` is missing `age_days`, `size_mb`, `format`, `bitrate`, and `publish_date` — all needed for the manual search results table. They're already on the `release_info` object; we just need to expose them.

**Files:**
- Modify: `studio54-service/app/models/download_decision.py:229-240`

- [ ] **Step 1: Update to_dict()**

Open `studio54-service/app/models/download_decision.py` and replace the `to_dict` method on `DownloadDecision` (currently lines 229–240):

```python
    def to_dict(self) -> Dict[str, Any]:
        ri = self.remote_album.release_info
        return {
            "title": ri.title,
            "guid": ri.guid,
            "quality": ri.quality,
            "size": ri.size,
            "size_mb": round(ri.size / (1024 * 1024), 1) if ri.size else 0,
            "age_days": ri.age_days,
            "publish_date": ri.publish_date.isoformat() if ri.publish_date else None,
            "format": ri.codec,
            "bitrate": ri.bitrate,
            "indexer": ri.indexer_name,
            "indexer_id": ri.indexer_id,
            "protocol": ri.protocol,
            "approved": self.approved,
            "temporarily_rejected": self.temporarily_rejected,
            "permanently_rejected": self.permanently_rejected,
            "rejections": [r.to_dict() for r in self.rejections],
        }
```

- [ ] **Step 2: Restart the service to apply**

```bash
docker restart studio54-service studio54-worker
```

- [ ] **Step 3: Verify the enriched response**

```bash
# Get an album ID that exists and is WANTED
ALBUM_ID=$(docker exec studio54-db psql -U studio54 -d studio54_db -tAc \
  "SELECT id FROM albums WHERE status='WANTED' LIMIT 1;")

TOKEN=$(curl -s -X POST http://localhost:8010/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

curl -s -X POST "http://localhost:8010/api/v1/search/albums/${ALBUM_ID}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
decisions = d.get('decisions', [])
if decisions:
    print(json.dumps(decisions[0], indent=2))
else:
    print('No decisions returned — indexer may not be configured or no results found')
"
```

Expected: First decision includes `age_days`, `size_mb`, `format`, `bitrate` fields.

- [ ] **Step 4: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-service/app/models/download_decision.py
git commit -m "feat: enrich DownloadDecision.to_dict with age_days, size_mb, format, bitrate"
```

---

## Task 2: Add TypeScript interfaces

**Files:**
- Modify: `studio54-web/src/types/index.ts`

- [ ] **Step 1: Add new interfaces at the end of the types file**

Append the following to `studio54-web/src/types/index.ts`:

```typescript
// ============================================================
// Download Queue & Manual Search Types
// ============================================================

export type TrackedDownloadState =
  | 'queued'
  | 'downloading'
  | 'paused'
  | 'import_pending'
  | 'import_blocked'
  | 'importing'
  | 'imported'
  | 'ignored'
  | 'failed'

export interface TrackedDownloadItem {
  id: string
  title: string
  state: TrackedDownloadState
  progress: number
  size_bytes: number
  downloaded_bytes: number
  eta_seconds: number | null
  album_id: string | null
  album_title: string | null
  artist_id: string | null
  artist_name: string | null
  quality: string
  indexer: string
  grabbed_at: string
  completed_at: string | null
  error_message: string | null
  status_messages: string[]
  output_path: string
}

export interface TrackedDownloadQueue {
  count: number
  items: TrackedDownloadItem[]
}

export interface ManualSearchDecision {
  title: string
  guid: string
  quality: string
  size: number
  size_mb: number
  age_days: number
  publish_date: string | null
  format: string | null
  bitrate: number | null
  indexer: string
  indexer_id: string
  protocol: string
  approved: boolean
  temporarily_rejected: boolean
  permanently_rejected: boolean
  rejections: Array<{ reason: string; type: string }>
}

export interface ManualSearchResult {
  album_id: string
  artist: { id: string; name: string }
  album: { id: string; title: string; status: string }
  total_results: number
  approved_count: number
  rejected_count: number
  decisions: ManualSearchDecision[]
}

export interface BlacklistEntry {
  id: string
  album_id: string | null
  artist_id: string | null
  release_guid: string
  release_title: string
  reason: string
  source_title: string | null
  added_at: string
  album_title?: string | null
  artist_name?: string | null
}

export interface BlacklistResponse {
  count: number
  items: BlacklistEntry[]
}

export interface PendingRelease {
  id: string
  album_id: string
  artist_id: string | null
  release_guid: string
  release_title: string
  rejection_reasons: string[]
  retry_count: number
  retry_after: string | null
  added_at: string
  album_title?: string | null
  artist_name?: string | null
}

export interface PendingResponse {
  count: number
  items: PendingRelease[]
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -30
```

Expected: No errors (or only pre-existing errors unrelated to new types).

- [ ] **Step 3: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/types/index.ts
git commit -m "feat: add TypeScript interfaces for download queue, manual search, blacklist, pending"
```

---

## Task 3: Add API client methods

**Files:**
- Modify: `studio54-web/src/api/client.ts`

- [ ] **Step 1: Extend searchApi and add queueApi**

In `studio54-web/src/api/client.ts`, find the `searchApi` export (around line 1862) and replace it entirely, then add `queueApi` after it:

```typescript
// ==================== SEARCH ====================

export const searchApi = {
  searchMissing: async (artistId?: string, limit = 50): Promise<{
    task_id: string
    status: string
    message: string
  }> => {
    const { data } = await api.post('/search/missing', null, {
      params: { artist_id: artistId, limit },
    })
    return data
  },

  searchAlbum: async (albumId: string): Promise<import('../types').ManualSearchResult> => {
    const { data } = await api.post(`/search/albums/${albumId}`, {})
    return data
  },

  grabRelease: async (albumId: string, releaseGuid: string): Promise<{
    success: boolean
    album_id: string
    release_guid: string
    tracked_download_id: string
    message: string
  }> => {
    const { data } = await api.post(`/search/albums/${albumId}/grab`, {
      release_guid: releaseGuid,
    })
    return data
  },

  getPending: async (): Promise<import('../types').PendingResponse> => {
    const { data } = await api.get('/search/pending')
    return data
  },

  removePending: async (pendingId: string): Promise<void> => {
    await api.delete(`/search/pending/${pendingId}`)
  },

  retryPending: async (pendingId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/search/pending/${pendingId}/retry`)
    return data
  },
}

// ==================== QUEUE ====================

export const queueApi = {
  getQueue: async (params?: {
    state?: string
    album_id?: string
    artist_id?: string
    include_completed?: boolean
    limit?: number
  }): Promise<import('../types').TrackedDownloadQueue> => {
    const { data } = await api.get('/queue', { params })
    return data
  },

  pause: async (downloadId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/queue/${downloadId}/pause`)
    return data
  },

  resume: async (downloadId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/queue/${downloadId}/resume`)
    return data
  },

  remove: async (downloadId: string, blacklist = false): Promise<void> => {
    await api.delete(`/queue/${downloadId}`, { params: { blacklist } })
  },

  retryImport: async (downloadId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/queue/${downloadId}/retry-import`)
    return data
  },

  getBlacklist: async (params?: {
    limit?: number
    offset?: number
  }): Promise<import('../types').BlacklistResponse> => {
    const { data } = await api.get('/queue/blacklist', { params })
    return data
  },

  removeFromBlacklist: async (blacklistId: string): Promise<void> => {
    await api.delete(`/queue/blacklist/${blacklistId}`)
  },
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -30
```

Expected: No new errors.

- [ ] **Step 3: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/api/client.ts
git commit -m "feat: add queueApi and extend searchApi with manual search and grab methods"
```

---

## Task 4: ManualSearchModal component

This is the Radarr-style modal: shows indexer results table with quality, size, age, approval decision, and a Grab button on each row.

**Files:**
- Create: `studio54-web/src/components/ManualSearchModal.tsx`

- [ ] **Step 1: Create the component**

Create `studio54-web/src/components/ManualSearchModal.tsx`:

```typescript
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FiX, FiDownload, FiSearch, FiCheck, FiAlertCircle, FiClock } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { searchApi } from '../api/client'
import type { ManualSearchDecision } from '../types'

interface Props {
  albumId: string
  albumTitle: string
  onClose: () => void
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '—'
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(0)} MB`
}

function QualityBadge({ quality, format, bitrate }: { quality: string; format: string | null; bitrate: number | null }) {
  const isLossless = quality?.includes('FLAC') || quality?.includes('ALAC') || quality?.includes('WAV')
  const bg = isLossless
    ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300'
    : 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300'

  const label = bitrate ? `${format || quality} ${bitrate}kbps` : (format || quality || '?')
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${bg}`}>{label}</span>
}

function DecisionBadge({ decision }: { decision: ManualSearchDecision }) {
  if (decision.approved) {
    return (
      <span className="flex items-center gap-1 text-green-600 dark:text-green-400 text-xs font-medium">
        <FiCheck size={12} /> Approved
      </span>
    )
  }
  if (decision.temporarily_rejected) {
    return (
      <span
        className="flex items-center gap-1 text-yellow-600 dark:text-yellow-400 text-xs font-medium cursor-help"
        title={decision.rejections.map(r => r.reason).join('\n')}
      >
        <FiClock size={12} /> Pending
      </span>
    )
  }
  return (
    <span
      className="flex items-center gap-1 text-red-600 dark:text-red-400 text-xs font-medium cursor-help"
      title={decision.rejections.map(r => r.reason).join('\n')}
    >
      <FiAlertCircle size={12} /> Rejected
    </span>
  )
}

export default function ManualSearchModal({ albumId, albumTitle, onClose }: Props) {
  const queryClient = useQueryClient()
  const [grabbingGuid, setGrabbingGuid] = useState<string | null>(null)
  const [showRejected, setShowRejected] = useState(false)

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['manual-search', albumId],
    queryFn: () => searchApi.searchAlbum(albumId),
    staleTime: 0,
    gcTime: 0,
  })

  const grabMutation = useMutation({
    mutationFn: (guid: string) => searchApi.grabRelease(albumId, guid),
    onMutate: (guid) => setGrabbingGuid(guid),
    onSuccess: () => {
      toast.success('Grabbed — download queued in SABnzbd')
      queryClient.invalidateQueries({ queryKey: ['album', albumId] })
      queryClient.invalidateQueries({ queryKey: ['download-queue'] })
      onClose()
    },
    onError: (err: Error) => {
      toast.error(err.message || 'Failed to grab release')
    },
    onSettled: () => setGrabbingGuid(null),
  })

  const decisions = data?.decisions ?? []
  const visible = showRejected ? decisions : decisions.filter(d => d.approved || d.temporarily_rejected)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#161B22] border border-gray-200 dark:border-[#30363D] rounded-lg shadow-xl w-full max-w-5xl max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-[#30363D]">
          <div>
            <h2 className="text-lg font-semibold text-gray-900 dark:text-[#E6EDF3] flex items-center gap-2">
              <FiSearch size={18} className="text-[#FF1493]" />
              Manual Search
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{albumTitle}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400"
          >
            <FiX size={18} />
          </button>
        </div>

        {/* Summary bar */}
        {data && (
          <div className="flex items-center gap-4 px-5 py-2.5 bg-gray-50 dark:bg-[#0D1117] border-b border-gray-200 dark:border-[#30363D] text-sm">
            <span className="text-gray-600 dark:text-gray-400">
              <strong className="text-gray-900 dark:text-[#E6EDF3]">{data.total_results}</strong> results
            </span>
            <span className="text-green-600 dark:text-green-400">
              <strong>{data.approved_count}</strong> approved
            </span>
            <span className="text-red-500 dark:text-red-400">
              <strong>{data.rejected_count}</strong> rejected
            </span>
            <label className="ml-auto flex items-center gap-2 cursor-pointer text-gray-500 dark:text-gray-400">
              <input
                type="checkbox"
                checked={showRejected}
                onChange={e => setShowRejected(e.target.checked)}
                className="rounded"
              />
              Show rejected
            </label>
            <button
              onClick={() => refetch()}
              className="flex items-center gap-1.5 text-[#FF1493] hover:text-[#FF1493]/80"
            >
              <FiSearch size={13} /> Re-search
            </button>
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <div className="flex flex-col items-center justify-center py-16 gap-3">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]" />
              <p className="text-sm text-gray-500 dark:text-gray-400">Searching indexers…</p>
            </div>
          )}

          {isError && (
            <div className="text-center py-16 text-red-500 dark:text-red-400">
              Search failed. Check that at least one indexer is configured and enabled.
            </div>
          )}

          {!isLoading && !isError && visible.length === 0 && (
            <div className="text-center py-16 text-gray-500 dark:text-gray-400">
              {data?.total_results === 0
                ? 'No results found on any configured indexer.'
                : 'No approved results. Enable "Show rejected" to see why results were filtered.'}
            </div>
          )}

          {!isLoading && !isError && visible.length > 0 && (
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-50 dark:bg-[#161B22] border-b border-gray-200 dark:border-[#30363D]">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 w-8"></th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Release</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">Quality</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">Size</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">Age</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Indexer</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Decision</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-[#21262D]">
                {visible.map(decision => (
                  <tr
                    key={decision.guid}
                    className={`hover:bg-gray-50 dark:hover:bg-[#1C2128] ${
                      decision.permanently_rejected ? 'opacity-50' : ''
                    }`}
                  >
                    <td className="px-4 py-3 text-gray-400">
                      {decision.protocol === 'usenet' ? '📡' : '🌊'}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className="text-gray-800 dark:text-[#E6EDF3] font-mono text-xs leading-tight break-all"
                        title={decision.title}
                      >
                        {decision.title.length > 80 ? decision.title.slice(0, 80) + '…' : decision.title}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <QualityBadge quality={decision.quality} format={decision.format} bitrate={decision.bitrate} />
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                      {formatBytes(decision.size)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                      {decision.age_days != null ? `${decision.age_days}d` : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-600 dark:text-gray-400 whitespace-nowrap">
                      {decision.indexer}
                    </td>
                    <td className="px-4 py-3">
                      <DecisionBadge decision={decision} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => grabMutation.mutate(decision.guid)}
                        disabled={grabbingGuid === decision.guid}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium
                          bg-[#FF1493]/10 text-[#FF1493] hover:bg-[#FF1493]/20
                          disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {grabbingGuid === decision.guid
                          ? <div className="animate-spin rounded-full h-3 w-3 border-b border-[#FF1493]" />
                          : <FiDownload size={12} />
                        }
                        Grab
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -30
```

Expected: No errors from the new file.

- [ ] **Step 3: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/components/ManualSearchModal.tsx
git commit -m "feat: add ManualSearchModal component with indexer results table and grab action"
```

---

## Task 5: Wire ManualSearchModal into AlbumDetail

**Files:**
- Modify: `studio54-web/src/pages/AlbumDetail.tsx`

- [ ] **Step 1: Add import and state to AlbumDetail**

Near the top of `AlbumDetail.tsx`, find the existing imports (around line 1-30) and add:

```typescript
import ManualSearchModal from '../components/ManualSearchModal'
```

Then find the component's state declarations (look for `useState` calls near the top of the function body) and add:

```typescript
const [showManualSearch, setShowManualSearch] = useState(false)
```

- [ ] **Step 2: Add the Manual Search button to the album toolbar**

In `AlbumDetail.tsx`, find the existing search/action buttons in the album header (look for the `manualSearchMutation` button or the area with `FiSearch`). The existing button triggers an auto-search. Add a new "Manual Search" button next to it:

Search for the line containing `manualSearchMutation.mutate()` or the auto-search button. Immediately after that button, add:

```typescript
<button
  onClick={() => setShowManualSearch(true)}
  className="flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium
    border border-gray-200 dark:border-[#30363D]
    text-gray-700 dark:text-[#8B949E]
    hover:bg-gray-100 dark:hover:bg-[#1C2128]
    hover:text-gray-900 dark:hover:text-[#E6EDF3]
    transition-colors"
  title="Manual Search — pick a release from indexer results"
>
  <FiSearch size={15} />
  Manual Search
</button>
```

- [ ] **Step 3: Render the modal at the bottom of the component's JSX**

Near the end of the `return (...)` in AlbumDetail, just before the closing `</div>` of the root element, add:

```typescript
{showManualSearch && album && (
  <ManualSearchModal
    albumId={album.id}
    albumTitle={album.title}
    onClose={() => setShowManualSearch(false)}
  />
)}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -30
```

Expected: No errors.

- [ ] **Step 5: Start dev server and test manually**

```bash
cd /home/tesimmons/Studio54/studio54-web
npm run dev &
```

Navigate to any album detail page. Confirm:
1. "Manual Search" button is visible in the toolbar
2. Clicking it opens the modal
3. The modal shows a loading spinner, then results (or "no results" if no indexer configured)
4. Clicking X or the backdrop closes the modal
5. Grab button is visible on approved rows

- [ ] **Step 6: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/pages/AlbumDetail.tsx
git commit -m "feat: add Manual Search button and modal to AlbumDetail page"
```

---

## Task 6: DownloadQueueTab component

This is the active download queue — progress bars, state badges, per-row actions.

**Files:**
- Create: `studio54-web/src/components/activity/DownloadQueueTab.tsx`

- [ ] **Step 1: Create the directory and component**

```bash
mkdir -p /home/tesimmons/Studio54/studio54-web/src/components/activity
```

Create `studio54-web/src/components/activity/DownloadQueueTab.tsx`:

```typescript
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FiPause, FiPlay, FiTrash2, FiRefreshCw, FiAlertCircle } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { queueApi } from '../../api/client'
import type { TrackedDownloadItem, TrackedDownloadState } from '../../types'

// ── helpers ──────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (!bytes) return '—'
  const gb = bytes / 1073741824
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  return `${(bytes / 1048576).toFixed(0)} MB`
}

function formatEta(seconds: number | null): string {
  if (!seconds) return '—'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

const STATE_CONFIG: Record<TrackedDownloadState, { label: string; className: string }> = {
  queued:          { label: 'Queued',          className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  downloading:     { label: 'Downloading',     className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' },
  paused:          { label: 'Paused',          className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300' },
  import_pending:  { label: 'Import Pending',  className: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300' },
  import_blocked:  { label: 'Import Blocked',  className: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300' },
  importing:       { label: 'Importing',       className: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300' },
  imported:        { label: 'Imported',        className: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' },
  ignored:         { label: 'Ignored',         className: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500' },
  failed:          { label: 'Failed',          className: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400' },
}

function StateBadge({ state }: { state: TrackedDownloadState }) {
  const cfg = STATE_CONFIG[state] ?? { label: state, className: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' }
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${cfg.className}`}>{cfg.label}</span>
}

function ProgressBar({ progress, state }: { progress: number; state: TrackedDownloadState }) {
  const color =
    state === 'failed' ? 'bg-red-500' :
    state === 'paused' ? 'bg-yellow-400' :
    state === 'imported' ? 'bg-green-500' :
    'bg-[#FF1493]'

  return (
    <div className="w-full bg-gray-200 dark:bg-[#30363D] rounded-full h-1.5">
      <div
        className={`${color} h-1.5 rounded-full transition-all duration-500`}
        style={{ width: `${Math.min(progress, 100)}%` }}
      />
    </div>
  )
}

// ── row actions ───────────────────────────────────────────────────────────────

function RowActions({ item }: { item: TrackedDownloadItem }) {
  const queryClient = useQueryClient()

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['download-queue'] })

  const pauseMutation = useMutation({
    mutationFn: () => queueApi.pause(item.id),
    onSuccess: () => { toast.success('Paused'); invalidate() },
    onError: () => toast.error('Failed to pause'),
  })

  const resumeMutation = useMutation({
    mutationFn: () => queueApi.resume(item.id),
    onSuccess: () => { toast.success('Resumed'); invalidate() },
    onError: () => toast.error('Failed to resume'),
  })

  const removeMutation = useMutation({
    mutationFn: (blacklist: boolean) => queueApi.remove(item.id, blacklist),
    onSuccess: () => { toast.success('Removed from queue'); invalidate() },
    onError: () => toast.error('Failed to remove'),
  })

  const retryImportMutation = useMutation({
    mutationFn: () => queueApi.retryImport(item.id),
    onSuccess: () => { toast.success('Retrying import'); invalidate() },
    onError: () => toast.error('Failed to retry import'),
  })

  const canPause = item.state === 'downloading' || item.state === 'queued'
  const canResume = item.state === 'paused'
  const canRetryImport = item.state === 'import_blocked'
  const isActive = ['queued', 'downloading', 'paused', 'import_pending', 'import_blocked', 'importing'].includes(item.state)

  return (
    <div className="flex items-center gap-1">
      {canPause && (
        <button
          onClick={() => pauseMutation.mutate()}
          disabled={pauseMutation.isPending}
          title="Pause"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-[#FF1493] transition-colors"
        >
          <FiPause size={14} />
        </button>
      )}
      {canResume && (
        <button
          onClick={() => resumeMutation.mutate()}
          disabled={resumeMutation.isPending}
          title="Resume"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-green-500 transition-colors"
        >
          <FiPlay size={14} />
        </button>
      )}
      {canRetryImport && (
        <button
          onClick={() => retryImportMutation.mutate()}
          disabled={retryImportMutation.isPending}
          title="Retry Import"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-blue-500 transition-colors"
        >
          <FiRefreshCw size={14} />
        </button>
      )}
      {isActive && (
        <button
          onClick={() => {
            if (confirm(`Remove "${item.title}" from queue?`)) {
              removeMutation.mutate(false)
            }
          }}
          disabled={removeMutation.isPending}
          title="Remove from queue"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-red-500 transition-colors"
        >
          <FiTrash2 size={14} />
        </button>
      )}
      {item.state === 'failed' && (
        <button
          onClick={() => {
            if (confirm(`Blacklist this release?\n"${item.title}"`)) {
              removeMutation.mutate(true)
            }
          }}
          disabled={removeMutation.isPending}
          title="Blacklist this release"
          className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-red-500 transition-colors"
        >
          <FiTrash2 size={14} />
        </button>
      )}
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export default function DownloadQueueTab() {
  const [includeCompleted, setIncludeCompleted] = useState(false)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['download-queue', includeCompleted],
    queryFn: () => queueApi.getQueue({ include_completed: includeCompleted, limit: 200 }),
    refetchInterval: 5000,
  })

  const items = data?.items ?? []
  const activeCount = items.filter(i =>
    ['queued', 'downloading', 'paused', 'import_pending', 'import_blocked', 'importing'].includes(i.state)
  ).length

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
          {isLoading
            ? <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-[#FF1493]" />
            : <span><strong className="text-gray-900 dark:text-[#E6EDF3]">{activeCount}</strong> active</span>
          }
          {data && data.count !== activeCount && (
            <span>· {data.count} total</span>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={includeCompleted}
            onChange={e => setIncludeCompleted(e.target.checked)}
            className="rounded"
          />
          Show completed
        </label>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        {isError && (
          <div className="text-center py-12 text-red-500 dark:text-red-400">
            Failed to load download queue
          </div>
        )}

        {!isLoading && !isError && items.length === 0 && (
          <div className="text-center py-12 text-gray-500 dark:text-gray-400">
            {includeCompleted ? 'No downloads found' : 'No active downloads'}
          </div>
        )}

        {!isError && items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#161B22]/50">
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Release</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Album / Artist</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Status</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400 w-40">Progress</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Size</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">ETA</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Indexer</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
                {items.map(item => (
                  <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                    <td className="px-4 py-3">
                      <div className="max-w-xs">
                        <span
                          className="text-gray-800 dark:text-[#E6EDF3] text-xs font-mono leading-tight block truncate"
                          title={item.title}
                        >
                          {item.title}
                        </span>
                        {item.quality && (
                          <span className="text-xs text-gray-500 dark:text-gray-500 mt-0.5 block">
                            {item.quality}
                          </span>
                        )}
                        {item.error_message && (
                          <span className="flex items-center gap-1 text-xs text-red-500 dark:text-red-400 mt-0.5" title={item.error_message}>
                            <FiAlertCircle size={10} />
                            {item.error_message.slice(0, 60)}{item.error_message.length > 60 ? '…' : ''}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-xs space-y-0.5">
                        {item.album_id && item.album_title && (
                          <Link
                            to={`/disco-lounge/albums/${item.album_id}`}
                            className="text-[#FF1493] hover:underline block font-medium"
                          >
                            {item.album_title}
                          </Link>
                        )}
                        {item.artist_id && item.artist_name && (
                          <Link
                            to={`/disco-lounge/artists/${item.artist_id}`}
                            className="text-gray-600 dark:text-gray-400 hover:underline block"
                          >
                            {item.artist_name}
                          </Link>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <StateBadge state={item.state} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="space-y-1 min-w-[120px]">
                        <ProgressBar progress={item.progress} state={item.state} />
                        <div className="flex justify-between text-xs text-gray-500 dark:text-gray-500">
                          <span>{item.progress.toFixed(0)}%</span>
                          <span>{formatBytes(item.downloaded_bytes)} / {formatBytes(item.size_bytes)}</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400 text-xs">
                      {formatBytes(item.size_bytes)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400 text-xs">
                      {formatEta(item.eta_seconds)}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400 text-xs">
                      {item.indexer || '—'}
                    </td>
                    <td className="px-4 py-3">
                      <RowActions item={item} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -30
```

Expected: No errors.

- [ ] **Step 3: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/components/activity/
git commit -m "feat: add DownloadQueueTab component with progress bars and pause/resume/remove actions"
```

---

## Task 7: PendingSection and BlacklistSection components

**Files:**
- Create: `studio54-web/src/components/activity/PendingSection.tsx`
- Create: `studio54-web/src/components/activity/BlacklistSection.tsx`

- [ ] **Step 1: Create PendingSection**

Create `studio54-web/src/components/activity/PendingSection.tsx`:

```typescript
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FiRefreshCw, FiTrash2, FiClock } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { searchApi } from '../../api/client'

export default function PendingSection() {
  const queryClient = useQueryClient()
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['pending-releases'] })

  const { data, isLoading, isError } = useQuery({
    queryKey: ['pending-releases'],
    queryFn: () => searchApi.getPending(),
    refetchInterval: 30000,
  })

  const retryMutation = useMutation({
    mutationFn: (id: string) => searchApi.retryPending(id),
    onSuccess: () => { toast.success('Queued for retry'); invalidate() },
    onError: () => toast.error('Failed to retry'),
  })

  const removeMutation = useMutation({
    mutationFn: (id: string) => searchApi.removePending(id),
    onSuccess: () => { toast.success('Removed'); invalidate() },
    onError: () => toast.error('Failed to remove'),
  })

  const items = data?.items ?? []

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <FiClock size={16} className="text-yellow-500" />
        <h3 className="text-sm font-semibold text-gray-700 dark:text-[#E6EDF3]">
          Pending Releases
        </h3>
        {data && (
          <span className="text-xs text-gray-500 dark:text-gray-400">({data.count})</span>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-6">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-[#FF1493]" />
        </div>
      )}

      {isError && (
        <p className="text-sm text-red-500 dark:text-red-400 py-3">Failed to load pending releases</p>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400 py-3">No pending releases</p>
      )}

      {items.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#161B22]/50">
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Release</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Album</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Reason</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Retries</th>
                <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Retry After</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
              {items.map(item => (
                <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                  <td className="px-4 py-3">
                    <span className="text-xs font-mono text-gray-800 dark:text-[#E6EDF3] truncate block max-w-xs" title={item.release_title}>
                      {item.release_title.length > 60 ? item.release_title.slice(0, 60) + '…' : item.release_title}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {item.album_id && item.album_title ? (
                      <Link to={`/disco-lounge/albums/${item.album_id}`} className="text-[#FF1493] hover:underline">
                        {item.album_title}
                      </Link>
                    ) : (
                      <span className="text-gray-500 dark:text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="space-y-0.5">
                      {item.rejection_reasons.slice(0, 2).map((r, i) => (
                        <span key={i} className="block text-xs text-yellow-600 dark:text-yellow-400">{r}</span>
                      ))}
                      {item.rejection_reasons.length > 2 && (
                        <span className="text-xs text-gray-500">+{item.rejection_reasons.length - 2} more</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                    {item.retry_count}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                    {item.retry_after
                      ? new Date(item.retry_after).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => retryMutation.mutate(item.id)}
                        disabled={retryMutation.isPending}
                        title="Retry now"
                        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-blue-500 transition-colors"
                      >
                        <FiRefreshCw size={13} />
                      </button>
                      <button
                        onClick={() => removeMutation.mutate(item.id)}
                        disabled={removeMutation.isPending}
                        title="Remove"
                        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-red-500 transition-colors"
                      >
                        <FiTrash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create BlacklistSection**

Create `studio54-web/src/components/activity/BlacklistSection.tsx`:

```typescript
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FiTrash2, FiSlash } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { queueApi } from '../../api/client'

const PAGE_SIZE = 50

export default function BlacklistSection() {
  const queryClient = useQueryClient()
  const [page, setPage] = useState(0)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['blacklist', page],
    queryFn: () => queueApi.getBlacklist({ limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
  })

  const removeMutation = useMutation({
    mutationFn: (id: string) => queueApi.removeFromBlacklist(id),
    onSuccess: () => {
      toast.success('Removed from blacklist')
      queryClient.invalidateQueries({ queryKey: ['blacklist'] })
    },
    onError: () => toast.error('Failed to remove from blacklist'),
  })

  const items = data?.items ?? []
  const totalPages = data ? Math.ceil(data.count / PAGE_SIZE) : 0

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <FiSlash size={16} className="text-red-500" />
        <h3 className="text-sm font-semibold text-gray-700 dark:text-[#E6EDF3]">
          Blacklisted Releases
        </h3>
        {data && (
          <span className="text-xs text-gray-500 dark:text-gray-400">({data.count})</span>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-6">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-[#FF1493]" />
        </div>
      )}

      {isError && (
        <p className="text-sm text-red-500 dark:text-red-400 py-3">Failed to load blacklist</p>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <p className="text-sm text-gray-500 dark:text-gray-400 py-3">Blacklist is empty</p>
      )}

      {items.length > 0 && (
        <>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-[#30363D] bg-gray-50 dark:bg-[#161B22]/50">
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Release</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Album / Artist</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400">Reason</th>
                  <th className="text-left px-4 py-2.5 font-medium text-gray-600 dark:text-gray-400 whitespace-nowrap">Date Added</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-[#30363D]">
                {items.map(item => (
                  <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                    <td className="px-4 py-3">
                      <span
                        className="text-xs font-mono text-gray-800 dark:text-[#E6EDF3] block truncate max-w-xs"
                        title={item.release_title}
                      >
                        {item.release_title}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs space-y-0.5">
                      {item.album_id && item.album_title && (
                        <Link to={`/disco-lounge/albums/${item.album_id}`} className="text-[#FF1493] hover:underline block">
                          {item.album_title}
                        </Link>
                      )}
                      {item.artist_name && (
                        <span className="text-gray-500 dark:text-gray-400 block">{item.artist_name}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 max-w-xs">
                      {item.reason || '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                      {item.added_at
                        ? new Date(item.added_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => {
                          if (confirm(`Remove "${item.release_title}" from blacklist?`)) {
                            removeMutation.mutate(item.id)
                          }
                        }}
                        disabled={removeMutation.isPending}
                        title="Remove from blacklist"
                        className="p-1.5 rounded hover:bg-gray-100 dark:hover:bg-[#21262D] text-gray-500 dark:text-gray-400 hover:text-red-500 transition-colors"
                      >
                        <FiTrash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
              <span>Page {page + 1} of {totalPages}</span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage(p => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="px-3 py-1 rounded border border-gray-200 dark:border-[#30363D] disabled:opacity-40 hover:bg-gray-100 dark:hover:bg-[#21262D]"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="px-3 py-1 rounded border border-gray-200 dark:border-[#30363D] disabled:opacity-40 hover:bg-gray-100 dark:hover:bg-[#21262D]"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -30
```

Expected: No errors from new files.

- [ ] **Step 4: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/components/activity/
git commit -m "feat: add PendingSection and BlacklistSection activity components"
```

---

## Task 8: Wire new tabs into Activity page

**Files:**
- Modify: `studio54-web/src/pages/Activity.tsx`

- [ ] **Step 1: Add imports at the top of Activity.tsx**

Near the existing imports in `Activity.tsx`, add:

```typescript
import DownloadQueueTab from '../components/activity/DownloadQueueTab'
import PendingSection from '../components/activity/PendingSection'
import BlacklistSection from '../components/activity/BlacklistSection'
```

- [ ] **Step 2: Extend the tab state type**

Find the `useState` for `activeTab` in `Activity.tsx`. It currently looks like:

```typescript
const [activeTab, setActiveTab] = useState<'jobs' | 'downloads' | 'queue-status'>('jobs')
```

Change it to:

```typescript
const [activeTab, setActiveTab] = useState<'jobs' | 'downloads' | 'queue-status' | 'queue' | 'blacklist'>('jobs')
```

- [ ] **Step 3: Add the two new tab buttons**

Find the tab button bar in Activity.tsx (look for the buttons rendering 'jobs', 'downloads', 'queue-status'). After the existing tab buttons, add:

```typescript
<button
  onClick={() => setActiveTab('queue')}
  className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
    activeTab === 'queue'
      ? 'bg-[#FF1493]/10 text-[#FF1493]'
      : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-[#E6EDF3]'
  }`}
>
  Download Queue
</button>
<button
  onClick={() => setActiveTab('blacklist')}
  className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
    activeTab === 'blacklist'
      ? 'bg-[#FF1493]/10 text-[#FF1493]'
      : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-[#E6EDF3]'
  }`}
>
  Blacklist
</button>
```

- [ ] **Step 4: Add the new tab content panels**

Find the section in Activity.tsx that renders the existing tab content (the `{activeTab === 'jobs' && ...}` blocks). After the last existing tab content block, add:

```typescript
{activeTab === 'queue' && (
  <div className="space-y-6">
    <DownloadQueueTab />
    <PendingSection />
  </div>
)}

{activeTab === 'blacklist' && (
  <BlacklistSection />
)}
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd /home/tesimmons/Studio54/studio54-web
npx tsc --noEmit 2>&1 | head -30
```

Expected: No errors.

- [ ] **Step 6: Build to verify no runtime issues**

```bash
cd /home/tesimmons/Studio54/studio54-web
npm run build 2>&1 | tail -20
```

Expected: Build succeeds (may show warnings but no errors).

- [ ] **Step 7: Smoke test in browser**

Start the dev server if not running:

```bash
cd /home/tesimmons/Studio54/studio54-web
npm run dev
```

Verify:
1. `/activity` page loads without error
2. "Download Queue" tab appears in the tab bar
3. "Blacklist" tab appears in the tab bar
4. Clicking "Download Queue" shows the queue table (empty if no active downloads) and Pending section
5. Clicking "Blacklist" shows the blacklist table (empty if nothing blacklisted)
6. On an album page, "Manual Search" button is visible
7. Clicking "Manual Search" opens the modal (may take a few seconds to search)
8. The existing Jobs, Downloads, Queue Status tabs still work correctly

- [ ] **Step 8: Commit**

```bash
cd /home/tesimmons/Studio54
git add studio54-web/src/pages/Activity.tsx
git commit -m "feat: add Download Queue and Blacklist tabs to Activity page"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Activities page with download/search status → Queue tab added to Activity
- ✅ Manual search showing indexer results with file, size, age → ManualSearchModal with full table
- ✅ Determine which to download → Grab button per row
- ✅ Download process status (SABnzbd, failed, etc.) → DownloadQueueTab with state machine badges
- ✅ Track failed downloads → TrackedDownload state=failed shown with error message
- ✅ Look for alternative downloads → existing backend handles this; queue shows retry-import action
- ✅ Track tried NZBs → attempted_nzb_guids already in backend; queue shows blacklist action for failures
- ✅ Blacklist management → BlacklistSection with remove action
- ✅ Pending releases → PendingSection with retry/remove actions

**Gaps / notes:**
- The "show attempted GUIDs per download in history" mentioned in the feature description is backend-complex (requires joining download_history rows by album) and is deferred — the blacklist and pending sections cover the user-visible surface of that feature.
- The `album_title` and `artist_name` fields on BlacklistEntry and PendingRelease depend on the backend `/queue/blacklist` and `/search/pending` responses including those joins. If missing, those cells will show "—" gracefully — no crash.
