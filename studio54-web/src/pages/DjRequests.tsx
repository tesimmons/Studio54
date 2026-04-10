import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { djRequestsApi, artistsApi } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { usePlayer } from '../contexts/PlayerContext'
import { searchPreview, searchArtistTopTracks, type ItunesResult } from '../api/itunes'
import {
  FiPlus, FiCheck, FiX, FiTrash2, FiMusic, FiDisc, FiUser,
  FiMessageSquare, FiFilter, FiSearch, FiPlay, FiArrowLeft,
  FiArrowRight, FiUsers, FiList, FiDownload, FiLoader, FiAlertTriangle,
} from 'react-icons/fi'
import type { DjRequest, DjRequestStatus, MusicBrainzArtist } from '../types'

const STATUS_COLORS: Record<DjRequestStatus, string> = {
  pending: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
  approved: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
  rejected: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  fulfilled: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
}

const TYPE_ICONS: Record<string, typeof FiMusic> = {
  artist: FiUser,
  album: FiDisc,
  track: FiMusic,
  problem: FiAlertTriangle,
}

// --- Preview Button Component ---
function PreviewButton({ artistName, trackName }: { artistName: string; trackName: string }) {
  const player = usePlayer()
  const [loading, setLoading] = useState(false)

  const handlePlay = async () => {
    setLoading(true)
    try {
      const result = await searchPreview(artistName, trackName)
      if (result) {
        player.play({
          id: `preview-${artistName}-${trackName}`,
          title: result.itunes_track_name,
          track_number: 0,
          duration_ms: 30000,
          has_file: false,
          preview_url: result.preview_url,
          artist_name: result.itunes_artist_name,
          artist_id: null,
          album_id: '',
          album_cover_art_url: result.artwork_url || null,
        })
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      onClick={handlePlay}
      disabled={loading}
      className="p-1.5 rounded-full text-amber-500 hover:bg-amber-500/20 transition-colors"
      title={`Preview: ${trackName}`}
    >
      {loading ? <FiLoader className="w-4 h-4 animate-spin" /> : <FiPlay className="w-4 h-4" />}
    </button>
  )
}

// --- iTunes Track Preview Row ---
function TrackPreviewRow({ result, artistName }: { result: ItunesResult; artistName: string }) {
  const player = usePlayer()

  return (
    <div className="flex items-center gap-3 py-1.5">
      {result.artwork_url && (
        <img src={result.artwork_url} alt="" className="w-8 h-8 rounded" />
      )}
      <span className="text-sm text-gray-700 dark:text-gray-300 flex-1 truncate">
        {result.itunes_track_name}
      </span>
      <button
        onClick={() => {
          player.play({
            id: `preview-${artistName}-${result.itunes_track_name}`,
            title: result.itunes_track_name,
            track_number: 0,
            duration_ms: 30000,
            has_file: false,
            preview_url: result.preview_url,
            artist_name: result.itunes_artist_name,
            artist_id: null,
            album_id: '',
            album_cover_art_url: result.artwork_url || null,
          })
        }}
        className="p-1.5 rounded-full text-amber-500 hover:bg-amber-500/20 transition-colors flex-shrink-0"
        title="Play 30-sec preview"
      >
        <FiPlay className="w-4 h-4" />
      </button>
    </div>
  )
}

// --- Multi-Step Request Form ---
function RequestForm({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()

  // Step 1: type + MB search
  const [step, setStep] = useState(1)
  const [requestType, setRequestType] = useState<string>('artist')
  const [searchQuery, setSearchQuery] = useState('')
  const [mbResults, setMbResults] = useState<MusicBrainzArtist[]>([])
  const [searching, setSearching] = useState(false)
  const [selectedArtist, setSelectedArtist] = useState<MusicBrainzArtist | null>(null)

  // Step 2: preview + details
  const [trackName, setTrackName] = useState('')
  const [albumName, setAlbumName] = useState('')
  const [topTracks, setTopTracks] = useState<ItunesResult[]>([])
  const [trackPreview, setTrackPreview] = useState<ItunesResult | null>(null)
  const [loadingPreviews, setLoadingPreviews] = useState(false)

  // Step 3: notes
  const [notes, setNotes] = useState('')

  const createMutation = useMutation({
    mutationFn: djRequestsApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dj-requests'] })
      onClose()
    },
  })

  // MusicBrainz search
  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    try {
      const result = await artistsApi.search(searchQuery.trim())
      setMbResults(result.results || [])
    } catch {
      setMbResults([])
    } finally {
      setSearching(false)
    }
  }

  // When artist is selected, go to step 2 and fetch previews
  const handleSelectArtist = async (artist: MusicBrainzArtist) => {
    setSelectedArtist(artist)
    setStep(2)

    if (requestType === 'artist') {
      setLoadingPreviews(true)
      try {
        const tracks = await searchArtistTopTracks(artist.name, 2)
        setTopTracks(tracks)
      } finally {
        setLoadingPreviews(false)
      }
    }
  }

  // Search for specific track preview
  const handleTrackSearch = useCallback(async (name: string) => {
    if (!name.trim() || !selectedArtist) return
    const result = await searchPreview(selectedArtist.name, name.trim())
    setTrackPreview(result)
  }, [selectedArtist])

  // Debounced track search
  useEffect(() => {
    if (requestType !== 'track' || !trackName.trim() || !selectedArtist) return
    const timer = setTimeout(() => handleTrackSearch(trackName), 500)
    return () => clearTimeout(timer)
  }, [trackName, requestType, selectedArtist, handleTrackSearch])

  const handleSubmit = () => {
    const title = requestType === 'artist'
      ? selectedArtist?.name || searchQuery
      : requestType === 'album'
        ? albumName || searchQuery
        : trackName || searchQuery

    createMutation.mutate({
      request_type: requestType,
      title,
      artist_name: requestType !== 'artist' ? (selectedArtist?.name || undefined) : undefined,
      notes: notes.trim() || undefined,
      musicbrainz_id: selectedArtist?.id,
      musicbrainz_name: selectedArtist?.name,
      track_name: requestType === 'track' ? trackName.trim() || undefined : undefined,
    })
  }

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
          {step === 1 ? 'Step 1: Find Artist' : step === 2 ? 'Step 2: Confirm Details' : 'Step 3: Submit'}
        </h2>
        <div className="flex items-center gap-1.5 text-xs text-gray-400">
          {[1, 2, 3].map(s => (
            <div
              key={s}
              className={`w-6 h-6 rounded-full flex items-center justify-center font-medium ${
                s === step ? 'bg-[#FF1493] text-white' : s < step ? 'bg-green-600 text-white' : 'bg-gray-200 dark:bg-[#0D1117]'
              }`}
            >
              {s < step ? <FiCheck className="w-3 h-3" /> : s}
            </div>
          ))}
        </div>
      </div>

      {/* Step 1: Type + MusicBrainz Search */}
      {step === 1 && (
        <div className="space-y-4">
          {/* Type selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Request Type</label>
            <div className="flex gap-2">
              {(['artist', 'album', 'track'] as const).map(type => {
                const Icon = TYPE_ICONS[type]
                return (
                  <button
                    key={type}
                    type="button"
                    onClick={() => setRequestType(type)}
                    className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                      requestType === type
                        ? 'bg-[#FF1493] text-white'
                        : 'bg-gray-100 dark:bg-[#0D1117] text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[#30363D]'
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                    {type.charAt(0).toUpperCase() + type.slice(1)}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Search */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Search MusicBrainz for Artist
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), handleSearch())}
                placeholder="Type artist name and press Enter..."
                className="flex-1 px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
                autoFocus
              />
              <button
                type="button"
                onClick={handleSearch}
                disabled={searching || !searchQuery.trim()}
                className="btn btn-primary flex items-center gap-1.5"
              >
                {searching ? <FiLoader className="w-4 h-4 animate-spin" /> : <FiSearch className="w-4 h-4" />}
                Search
              </button>
            </div>
          </div>

          {/* MB Results */}
          {mbResults.length > 0 && (
            <div className="space-y-2 max-h-64 overflow-y-auto">
              <p className="text-xs text-gray-500 dark:text-gray-400 font-medium">
                Select an artist ({mbResults.length} results):
              </p>
              {mbResults.map(artist => (
                <button
                  key={artist.id}
                  type="button"
                  onClick={() => handleSelectArtist(artist)}
                  className="w-full text-left p-3 rounded-lg border border-gray-200 dark:border-[#30363D] hover:border-[#FF1493] hover:bg-[#FF1493]/5 dark:hover:bg-[#FF1493]/10 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="font-medium text-gray-900 dark:text-white">{artist.name}</span>
                      {artist.type && (
                        <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">({artist.type})</span>
                      )}
                    </div>
                    {artist.country && (
                      <span className="text-xs text-gray-400">{artist.country}</span>
                    )}
                  </div>
                  {artist.tags?.length > 0 && (
                    <div className="flex gap-1 mt-1 flex-wrap">
                      {artist.tags.slice(0, 4).map(tag => (
                        <span key={tag} className="px-1.5 py-0.5 bg-gray-100 dark:bg-[#0D1117] text-gray-500 dark:text-gray-400 text-xs rounded">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="btn btn-secondary">Cancel</button>
          </div>
        </div>
      )}

      {/* Step 2: Confirm Details + Previews */}
      {step === 2 && selectedArtist && (
        <div className="space-y-4">
          {/* Selected artist card */}
          <div className="p-3 bg-[#FF1493]/5 dark:bg-[#FF1493]/10 rounded-lg border border-[#FF1493]/20 dark:border-[#FF1493]/20">
            <div className="flex items-center gap-2">
              <FiUser className="w-4 h-4 text-[#FF1493]" />
              <span className="font-medium text-gray-900 dark:text-white">{selectedArtist.name}</span>
              {selectedArtist.country && (
                <span className="text-xs text-gray-500">({selectedArtist.country})</span>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 font-mono">{selectedArtist.id}</p>
          </div>

          {/* Artist request: show top tracks previews */}
          {requestType === 'artist' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Preview Tracks
              </label>
              {loadingPreviews ? (
                <div className="flex items-center gap-2 text-sm text-gray-400 py-2">
                  <FiLoader className="w-4 h-4 animate-spin" /> Loading previews...
                </div>
              ) : topTracks.length > 0 ? (
                <div className="space-y-1 bg-gray-50 dark:bg-[#161B22]/50 rounded-lg p-3">
                  {topTracks.map((track, i) => (
                    <TrackPreviewRow key={i} result={track} artistName={selectedArtist.name} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-400 italic">No previews available</p>
              )}
            </div>
          )}

          {/* Track request: track name input + preview */}
          {requestType === 'track' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Track Name</label>
              <input
                type="text"
                value={trackName}
                onChange={e => setTrackName(e.target.value)}
                placeholder="e.g. Around the World"
                className="w-full px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
              />
              {trackPreview && (
                <div className="mt-2 bg-gray-50 dark:bg-[#161B22]/50 rounded-lg p-3">
                  <TrackPreviewRow result={trackPreview} artistName={selectedArtist.name} />
                </div>
              )}
            </div>
          )}

          {/* Album request: album name input */}
          {requestType === 'album' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Album Name</label>
              <input
                type="text"
                value={albumName}
                onChange={e => setAlbumName(e.target.value)}
                placeholder="e.g. Discovery"
                className="w-full px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
              />
            </div>
          )}

          <div className="flex justify-between">
            <button type="button" onClick={() => { setStep(1); setSelectedArtist(null); setMbResults([]) }} className="btn btn-secondary flex items-center gap-1.5">
              <FiArrowLeft className="w-4 h-4" /> Back
            </button>
            <button
              type="button"
              onClick={() => setStep(3)}
              disabled={requestType === 'track' && !trackName.trim() || requestType === 'album' && !albumName.trim()}
              className="btn btn-primary flex items-center gap-1.5"
            >
              Next <FiArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Notes + Submit */}
      {step === 3 && (
        <div className="space-y-4">
          {/* Summary */}
          <div className="p-3 bg-gray-50 dark:bg-[#161B22]/50 rounded-lg text-sm">
            <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300">
              <span className="font-medium">Type:</span>
              <span className="capitalize">{requestType}</span>
            </div>
            <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300 mt-1">
              <span className="font-medium">Artist:</span>
              <span>{selectedArtist?.name || searchQuery}</span>
            </div>
            {requestType === 'track' && trackName && (
              <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300 mt-1">
                <span className="font-medium">Track:</span>
                <span>{trackName}</span>
              </div>
            )}
            {requestType === 'album' && albumName && (
              <div className="flex items-center gap-2 text-gray-700 dark:text-gray-300 mt-1">
                <span className="font-medium">Album:</span>
                <span>{albumName}</span>
              </div>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Notes (optional)</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              rows={2}
              placeholder="Any additional details..."
              className="w-full px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
            />
          </div>

          <div className="flex justify-between">
            <button type="button" onClick={() => setStep(2)} className="btn btn-secondary flex items-center gap-1.5">
              <FiArrowLeft className="w-4 h-4" /> Back
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={createMutation.isPending}
              className="btn btn-primary"
            >
              {createMutation.isPending ? 'Submitting...' : 'Submit Request'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// --- Request Card (used in both views) ---
function RequestCard({
  req,
  isOwn,
  isDirector,
  onApprove,
  onReject,
  onFulfill,
  onDelete,
  onAddToLibrary,
  addingToLibrary,
}: {
  req: DjRequest
  isOwn: boolean
  isDirector: boolean
  onApprove: (req: DjRequest) => void
  onReject: (req: DjRequest) => void
  onFulfill: (id: string) => void
  onDelete: (id: string) => void
  onAddToLibrary?: (req: DjRequest) => void
  addingToLibrary?: boolean
}) {
  const Icon = TYPE_ICONS[req.request_type] || FiMusic

  return (
    <div className="card p-4 flex items-start gap-4">
      {/* Type icon */}
      <div className="w-10 h-10 rounded-lg bg-gray-100 dark:bg-[#0D1117] flex items-center justify-center flex-shrink-0">
        <Icon className="w-5 h-5 text-gray-500 dark:text-gray-400" />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="font-semibold text-gray-900 dark:text-white">{req.title}</h3>
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[req.status as DjRequestStatus]}`}>
            {req.status}
          </span>
          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-[#0D1117] dark:text-gray-400">
            {req.request_type}
          </span>
          {req.musicbrainz_name && (
            <span className="text-xs text-[#FF1493]" title={`MBID: ${req.musicbrainz_id}`}>
              MB verified
            </span>
          )}
        </div>

        {req.artist_name && (
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5">
            by {req.artist_name}
          </p>
        )}

        {req.track_name && (
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-0.5">
            Track: {req.track_name}
          </p>
        )}

        <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-400 dark:text-gray-500">
          <span>Requested by <span className="text-gray-600 dark:text-gray-300">{req.requester_name}</span></span>
          <span>{new Date(req.created_at).toLocaleDateString()}</span>
        </div>

        {req.notes && (
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-2 italic">"{req.notes}"</p>
        )}

        {req.response_note && (
          <div className="mt-2 text-sm bg-gray-50 dark:bg-[#161B22]/50 rounded-lg px-3 py-2 border-l-2 border-[#FF1493]">
            <span className="text-gray-500 dark:text-gray-400">Response: </span>
            <span className="text-gray-700 dark:text-gray-300">{req.response_note}</span>
            {req.fulfilled_by_name && (
              <span className="text-gray-400"> — {req.fulfilled_by_name}</span>
            )}
          </div>
        )}

        {/* Preview buttons for requests with MB data */}
        {req.musicbrainz_name && (
          <div className="flex items-center gap-2 mt-2">
            {req.track_name ? (
              <PreviewButton artistName={req.musicbrainz_name} trackName={req.track_name} />
            ) : req.request_type === 'artist' ? (
              <PreviewButton artistName={req.musicbrainz_name} trackName={req.title} />
            ) : null}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 flex-shrink-0">
        {isDirector && req.status === 'pending' && (
          <>
            <button
              onClick={() => onApprove(req)}
              className="p-2 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20 rounded-lg transition-colors"
              title="Approve"
            >
              <FiCheck className="w-4 h-4" />
            </button>
            <button
              onClick={() => onReject(req)}
              className="p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
              title="Reject"
            >
              <FiX className="w-4 h-4" />
            </button>
          </>
        )}
        {isDirector && req.status === 'approved' && (
          <button
            onClick={() => onFulfill(req.id)}
            className="px-2 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700 transition-colors"
          >
            Mark Fulfilled
          </button>
        )}
        {isDirector && req.musicbrainz_id && req.status !== 'fulfilled' && req.request_type === 'artist' && onAddToLibrary && (
          <button
            onClick={() => onAddToLibrary(req)}
            disabled={addingToLibrary}
            className="px-2 py-1 text-xs bg-[#FF1493] text-white rounded hover:bg-[#d10f7a] transition-colors flex items-center gap-1"
            title="Add artist to library and search for missing"
          >
            {addingToLibrary ? <FiLoader className="w-3 h-3 animate-spin" /> : <FiDownload className="w-3 h-3" />}
            Add to Library
          </button>
        )}
        {(isOwn || isDirector) && (
          <button
            onClick={() => {
              if (confirm('Delete this request?')) {
                onDelete(req.id)
              }
            }}
            className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
            title="Delete"
          >
            <FiTrash2 className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  )
}

// --- Main Component ---
export default function DjRequests() {
  const { user, isDirector, isDjOrAbove } = useAuth()
  const queryClient = useQueryClient()

  // View mode
  const [viewMode, setViewMode] = useState<'all' | 'by-user'>('all')
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [myOnly, setMyOnly] = useState(!isDjOrAbove)

  // New request form
  const [showForm, setShowForm] = useState(false)

  // Report a Problem modal
  const [showReportProblem, setShowReportProblem] = useState(false)
  const [reportTitle, setReportTitle] = useState('')
  const [reportDescription, setReportDescription] = useState('')

  // Response modal
  const [respondingTo, setRespondingTo] = useState<DjRequest | null>(null)
  const [responseNote, setResponseNote] = useState('')

  // Adding to library
  const [addingToLibrary, setAddingToLibrary] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['dj-requests', statusFilter, typeFilter, myOnly, selectedUserId],
    queryFn: () => djRequestsApi.list({
      status_filter: statusFilter || undefined,
      request_type: typeFilter || undefined,
      my_requests: myOnly || undefined,
      user_id: selectedUserId || undefined,
    }),
  })

  const { data: byUserData } = useQuery({
    queryKey: ['dj-requests-by-user'],
    queryFn: () => djRequestsApi.listByUser(),
    enabled: isDirector && viewMode === 'by-user',
  })

  const requests = data?.requests || []
  const userSummaries = byUserData?.users || []

  const updateMutation = useMutation({
    mutationFn: ({ id, status, response_note }: { id: string; status: string; response_note?: string }) =>
      djRequestsApi.updateStatus(id, { status, response_note }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dj-requests'] })
      queryClient.invalidateQueries({ queryKey: ['dj-requests-by-user'] })
      setRespondingTo(null)
      setResponseNote('')
    },
  })

  const reportProblemMutation = useMutation({
    mutationFn: () => djRequestsApi.create({
      request_type: 'problem',
      title: reportTitle.trim(),
      notes: reportDescription.trim() || undefined,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dj-requests'] })
      queryClient.invalidateQueries({ queryKey: ['dj-requests-by-user'] })
      setShowReportProblem(false)
      setReportTitle('')
      setReportDescription('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: djRequestsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dj-requests'] })
      queryClient.invalidateQueries({ queryKey: ['dj-requests-by-user'] })
    },
  })

  const handleApprove = (req: DjRequest) => {
    setRespondingTo({ ...req, status: 'approved' as DjRequestStatus })
    setResponseNote('')
  }

  const handleReject = (req: DjRequest) => {
    setRespondingTo({ ...req, status: 'rejected' as DjRequestStatus })
    setResponseNote('')
  }

  const handleRespondSubmit = () => {
    if (!respondingTo) return
    updateMutation.mutate({
      id: respondingTo.id,
      status: respondingTo.status,
      response_note: responseNote.trim() || undefined,
    })
  }

  const handleAddToLibrary = async (req: DjRequest) => {
    if (!req.musicbrainz_id) return
    setAddingToLibrary(true)
    try {
      await artistsApi.add({
        musicbrainz_id: req.musicbrainz_id,
        search_for_missing: true,
      })
      // Mark as fulfilled
      await djRequestsApi.updateStatus(req.id, { status: 'fulfilled', response_note: 'Added to library' })
      queryClient.invalidateQueries({ queryKey: ['dj-requests'] })
      queryClient.invalidateQueries({ queryKey: ['dj-requests-by-user'] })
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to add artist'
      alert(msg)
    } finally {
      setAddingToLibrary(false)
    }
  }

  const pendingCount = requests.filter(r => r.status === 'pending').length

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">DJ Requests</h1>
          <p className="mt-1 text-gray-500 dark:text-gray-400">
            Request artists, albums, or tracks to be added to the library
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowReportProblem(true)}
            className="btn btn-secondary flex items-center gap-2"
          >
            <FiAlertTriangle className="w-4 h-4" />
            Report a Problem
          </button>
          <button
            onClick={() => setShowForm(!showForm)}
            className="btn btn-primary flex items-center gap-2"
          >
            <FiPlus className="w-4 h-4" />
            New Request
          </button>
        </div>
      </div>

      {/* New Request Form */}
      {showForm && <RequestForm onClose={() => setShowForm(false)} />}

      {/* View Mode Tabs (directors only) */}
      {isDirector && (
        <div className="flex items-center gap-2 border-b border-gray-200 dark:border-[#30363D]">
          <button
            onClick={() => { setViewMode('all'); setSelectedUserId(null) }}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              viewMode === 'all'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <FiList className="w-4 h-4" />
            All Requests
          </button>
          <button
            onClick={() => setViewMode('by-user')}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              viewMode === 'by-user'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            <FiUsers className="w-4 h-4" />
            By User
          </button>
        </div>
      )}

      {/* By User View */}
      {isDirector && viewMode === 'by-user' && !selectedUserId && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {userSummaries.map(u => (
            <button
              key={u.user_id}
              onClick={() => setSelectedUserId(u.user_id)}
              className="card p-4 text-left hover:border-[#FF1493] transition-colors"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-full bg-[#FF1493]/10 dark:bg-[#FF1493]/15 flex items-center justify-center">
                    <FiUser className="w-4 h-4 text-[#FF1493]" />
                  </div>
                  <span className="font-medium text-gray-900 dark:text-white">{u.display_name}</span>
                </div>
                {u.pending_count > 0 && (
                  <span className="px-2 py-0.5 bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400 text-xs font-medium rounded-full">
                    {u.pending_count} pending
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                {u.total_count} total request{u.total_count !== 1 ? 's' : ''}
              </p>
            </button>
          ))}
          {userSummaries.length === 0 && (
            <div className="col-span-full card p-8 text-center text-gray-500 dark:text-gray-400">
              No requests from any users yet
            </div>
          )}
        </div>
      )}

      {/* Selected user header */}
      {isDirector && viewMode === 'by-user' && selectedUserId && (
        <div className="flex items-center gap-3">
          <button
            onClick={() => setSelectedUserId(null)}
            className="p-2 hover:bg-gray-100 dark:hover:bg-[#1C2128] rounded-lg transition-colors"
          >
            <FiArrowLeft className="w-4 h-4" />
          </button>
          <span className="text-sm text-gray-500 dark:text-gray-400">
            Showing requests for <span className="font-medium text-gray-900 dark:text-white">
              {userSummaries.find(u => u.user_id === selectedUserId)?.display_name || 'User'}
            </span>
          </span>
        </div>
      )}

      {/* Filters (shown in "all" view or when user is selected) */}
      {(viewMode === 'all' || selectedUserId) && (
        <div className="flex flex-wrap items-center gap-3">
          <FiFilter className="w-4 h-4 text-gray-400" />
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-3 py-1.5 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white"
          >
            <option value="">All Statuses</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="fulfilled">Fulfilled</option>
          </select>
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="px-3 py-1.5 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white"
          >
            <option value="">All Types</option>
            <option value="artist">Artist</option>
            <option value="album">Album</option>
            <option value="track">Track</option>
            <option value="problem">Problem</option>
          </select>
          {viewMode === 'all' && isDjOrAbove && (
            <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 cursor-pointer">
              <input
                type="checkbox"
                checked={myOnly}
                onChange={e => setMyOnly(e.target.checked)}
                className="rounded border-gray-300 text-[#FF1493] focus:ring-[#FF1493]"
              />
              My requests only
            </label>
          )}
          {pendingCount > 0 && (
            <span className="ml-auto text-sm text-yellow-600 dark:text-yellow-400 font-medium">
              {pendingCount} pending
            </span>
          )}
        </div>
      )}

      {/* Request List */}
      {(viewMode === 'all' || selectedUserId) && (
        <>
          {isLoading ? (
            <div className="flex justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]" />
            </div>
          ) : requests.length === 0 ? (
            <div className="card p-12 text-center">
              <FiMessageSquare className="w-16 h-16 text-gray-300 dark:text-gray-700 mx-auto mb-4" />
              <p className="text-lg text-gray-500 dark:text-gray-400">No requests yet</p>
              <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
                Click "New Request" to submit one
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {requests.map(req => (
                <RequestCard
                  key={req.id}
                  req={req}
                  isOwn={req.user_id === user?.id}
                  isDirector={isDirector}
                  onApprove={handleApprove}
                  onReject={handleReject}
                  onFulfill={(id) => updateMutation.mutate({ id, status: 'fulfilled' })}
                  onDelete={(id) => deleteMutation.mutate(id)}
                  onAddToLibrary={isDirector ? handleAddToLibrary : undefined}
                  addingToLibrary={addingToLibrary}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* Report a Problem Modal */}
      {showReportProblem && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl max-w-md w-full p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
              <FiAlertTriangle className="w-5 h-5 text-yellow-500" />
              Report a Problem
            </h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Title
                </label>
                <input
                  type="text"
                  value={reportTitle}
                  onChange={e => setReportTitle(e.target.value)}
                  placeholder="Brief summary of the issue..."
                  className="w-full px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={reportDescription}
                  onChange={e => setReportDescription(e.target.value)}
                  rows={4}
                  placeholder="Describe the problem in detail..."
                  className="w-full px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => { setShowReportProblem(false); setReportTitle(''); setReportDescription('') }}
                className="btn btn-secondary"
              >
                Cancel
              </button>
              <button
                onClick={() => reportProblemMutation.mutate()}
                disabled={reportProblemMutation.isPending || !reportTitle.trim()}
                className="btn btn-primary"
              >
                {reportProblemMutation.isPending ? 'Submitting...' : 'Submit Report'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Response Modal */}
      {respondingTo && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl max-w-md w-full p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-1">
              {respondingTo.status === 'rejected' ? 'Reject' : 'Approve'} Request
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
              "{respondingTo.title}" by {respondingTo.requester_name}
            </p>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Response Note (optional)
              </label>
              <textarea
                value={responseNote}
                onChange={e => setResponseNote(e.target.value)}
                rows={3}
                placeholder={respondingTo.status === 'rejected' ? 'Reason for rejection...' : 'Any notes...'}
                className="w-full px-3 py-2 bg-white dark:bg-[#0D1117] border border-gray-300 dark:border-[#30363D] rounded-lg text-sm text-gray-900 dark:text-white focus:ring-[#FF1493] focus:border-[#FF1493]"
                autoFocus
              />
            </div>

            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setRespondingTo(null)} className="btn btn-secondary">Cancel</button>
              <button
                onClick={handleRespondSubmit}
                disabled={updateMutation.isPending}
                className={`btn ${respondingTo.status === 'rejected' ? 'bg-red-600 hover:bg-red-700 text-white' : 'btn-primary'}`}
              >
                {updateMutation.isPending ? 'Saving...' : respondingTo.status === 'rejected' ? 'Reject' : 'Approve'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
