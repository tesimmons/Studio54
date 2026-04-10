import { useState, useEffect } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { fileOrganizationApi } from '../api/client'
import { FiX, FiChevronRight, FiChevronLeft, FiLink, FiSearch, FiMusic, FiDisc, FiCheck } from 'react-icons/fi'
import toast from 'react-hot-toast'

interface LinkFileModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  file: {
    id: string
    file_path: string
    artist?: string | null
    album?: string | null
    title?: string | null
  } | null
}

type Step = 'artist' | 'album' | 'track'

interface ArtistResult {
  id: string
  name: string
  musicbrainz_id: string
}

interface AlbumResult {
  id: string
  title: string
  artist_id: string
  release_date: string | null
  album_type: string | null
  track_count: number
  cover_art_url: string | null
}

interface TrackResult {
  id: string
  title: string
  track_number: number | null
  disc_number: number | null
  has_file: boolean
  album_id: string
  musicbrainz_id: string | null
  duration_ms: number | null
}

function LinkFileModal({ isOpen, onClose, onSuccess, file }: LinkFileModalProps) {
  const [step, setStep] = useState<Step>('artist')
  const [artistSearch, setArtistSearch] = useState('')
  const [albumSearch, setAlbumSearch] = useState('')
  const [trackSearch, setTrackSearch] = useState('')
  const [selectedArtist, setSelectedArtist] = useState<ArtistResult | null>(null)
  const [selectedAlbum, setSelectedAlbum] = useState<AlbumResult | null>(null)
  const [selectedTrack, setSelectedTrack] = useState<TrackResult | null>(null)

  // Reset state when modal opens/closes or file changes
  useEffect(() => {
    if (isOpen && file) {
      setStep('artist')
      setArtistSearch(file.artist || '')
      setAlbumSearch('')
      setTrackSearch('')
      setSelectedArtist(null)
      setSelectedAlbum(null)
      setSelectedTrack(null)
    }
  }, [isOpen, file?.id])

  // Search artists
  const { data: artistResults, isLoading: searchingArtists } = useQuery({
    queryKey: ['link-search-artists', artistSearch],
    queryFn: () => fileOrganizationApi.searchLinkTargets(file!.id, artistSearch, 'artist'),
    enabled: isOpen && step === 'artist' && artistSearch.length >= 1 && !!file,
  })

  // Fetch albums for selected artist
  const { data: albumResults, isLoading: loadingAlbums } = useQuery({
    queryKey: ['link-artist-albums', selectedArtist?.id],
    queryFn: () => fileOrganizationApi.getArtistAlbumsForLinking(selectedArtist!.id),
    enabled: isOpen && step === 'album' && !!selectedArtist,
  })

  // Fetch tracks for selected album
  const { data: trackResults, isLoading: loadingTracks } = useQuery({
    queryKey: ['link-album-tracks', selectedAlbum?.id],
    queryFn: () => fileOrganizationApi.getAlbumTracksForLinking(selectedAlbum!.id),
    enabled: isOpen && step === 'track' && !!selectedAlbum,
  })

  // Link mutation
  const linkMutation = useMutation({
    mutationFn: () => fileOrganizationApi.linkUnlinkedFile(file!.id, selectedTrack!.id),
    onSuccess: (data) => {
      toast.success(`Linked to "${data.track_title}" — file moved to organized location`)
      onSuccess()
      onClose()
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Failed to link file')
    },
  })

  if (!isOpen || !file) return null

  const fileName = file.file_path.split('/').pop() || file.file_path

  const formatDuration = (ms: number | null) => {
    if (!ms) return '-'
    const s = Math.floor(ms / 1000)
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-gray-800 rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col shadow-2xl border border-gray-700">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <div className="flex items-center gap-2">
            <FiLink className="text-blue-400" />
            <h2 className="text-lg font-semibold text-white">Link File to Track</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white p-1">
            <FiX size={20} />
          </button>
        </div>

        {/* File info bar */}
        <div className="px-4 py-2 bg-gray-900/50 border-b border-gray-700 text-sm">
          <div className="text-gray-400 truncate" title={file.file_path}>
            <span className="text-gray-500">File:</span> {fileName}
          </div>
          <div className="flex gap-4 text-gray-500 mt-1">
            {file.artist && <span>Artist: <span className="text-gray-300">{file.artist}</span></span>}
            {file.album && <span>Album: <span className="text-gray-300">{file.album}</span></span>}
            {file.title && <span>Title: <span className="text-gray-300">{file.title}</span></span>}
          </div>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-700">
          {(['artist', 'album', 'track'] as Step[]).map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              {i > 0 && <FiChevronRight className="text-gray-600" size={14} />}
              <span className={`text-sm px-2 py-0.5 rounded ${
                step === s ? 'bg-blue-500/20 text-blue-400 font-medium' :
                (s === 'album' && selectedArtist) || (s === 'track' && selectedAlbum) || (s === 'artist' && step !== 'artist')
                  ? 'text-green-400' : 'text-gray-500'
              }`}>
                {i + 1}. {s === 'artist' ? (selectedArtist ? selectedArtist.name : 'Select Artist') :
                          s === 'album' ? (selectedAlbum ? selectedAlbum.title : 'Select Album') :
                          'Select Track'}
              </span>
            </div>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 min-h-[300px]">
          {/* Step 1: Search Artist */}
          {step === 'artist' && (
            <div>
              <div className="relative mb-3">
                <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={artistSearch}
                  onChange={(e) => setArtistSearch(e.target.value)}
                  placeholder="Search for an artist..."
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg pl-10 pr-4 py-2 text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                  autoFocus
                />
              </div>
              {searchingArtists && <div className="text-gray-400 text-sm py-4 text-center">Searching...</div>}
              {artistResults?.results?.length === 0 && artistSearch.length >= 1 && !searchingArtists && (
                <div className="text-gray-500 text-sm py-4 text-center">No artists found</div>
              )}
              <div className="space-y-1">
                {artistResults?.results?.map((a: ArtistResult) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      setSelectedArtist(a)
                      setSelectedAlbum(null)
                      setSelectedTrack(null)
                      setAlbumSearch(file?.album || '')
                      setStep('album')
                    }}
                    className="w-full text-left px-3 py-2 rounded-lg hover:bg-gray-700 flex items-center gap-3 transition-colors"
                  >
                    <FiMusic className="text-gray-400 shrink-0" />
                    <span className="text-white">{a.name}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 2: Select Album */}
          {step === 'album' && (
            <div>
              <button
                onClick={() => setStep('artist')}
                className="text-sm text-gray-400 hover:text-white flex items-center gap-1 mb-3"
              >
                <FiChevronLeft size={14} /> Back to artist search
              </button>
              <div className="relative mb-3">
                <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={albumSearch}
                  onChange={(e) => setAlbumSearch(e.target.value)}
                  placeholder="Filter albums..."
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg pl-10 pr-4 py-2 text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                  autoFocus
                />
              </div>
              {loadingAlbums && <div className="text-gray-400 text-sm py-4 text-center">Loading albums...</div>}
              {albumResults?.results?.length === 0 && !loadingAlbums && (
                <div className="text-gray-500 text-sm py-4 text-center">No albums found for this artist</div>
              )}
              <div className="space-y-1">
                {albumResults?.results?.filter((a: AlbumResult) =>
                  !albumSearch || a.title.toLowerCase().includes(albumSearch.toLowerCase())
                ).map((a: AlbumResult) => (
                  <button
                    key={a.id}
                    onClick={() => {
                      setSelectedAlbum(a)
                      setSelectedTrack(null)
                      setTrackSearch(file?.title || '')
                      setStep('track')
                    }}
                    className="w-full text-left px-3 py-2 rounded-lg hover:bg-gray-700 flex items-center gap-3 transition-colors"
                  >
                    {a.cover_art_url ? (
                      <img src={a.cover_art_url} alt="" className="w-8 h-8 rounded object-cover shrink-0" />
                    ) : (
                      <FiDisc className="text-gray-400 shrink-0 w-8 h-8 p-1.5 bg-gray-600 rounded" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-white truncate">{a.title}</div>
                      <div className="text-xs text-gray-500">
                        {a.album_type || 'Album'}
                        {a.release_date && ` · ${a.release_date.substring(0, 4)}`}
                        {a.track_count > 0 && ` · ${a.track_count} tracks`}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 3: Select Track */}
          {step === 'track' && (
            <div>
              <button
                onClick={() => setStep('album')}
                className="text-sm text-gray-400 hover:text-white flex items-center gap-1 mb-3"
              >
                <FiChevronLeft size={14} /> Back to albums
              </button>
              <div className="relative mb-3">
                <FiSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={trackSearch}
                  onChange={(e) => setTrackSearch(e.target.value)}
                  placeholder="Filter tracks..."
                  className="w-full bg-gray-700 border border-gray-600 rounded-lg pl-10 pr-4 py-2 text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                  autoFocus
                />
              </div>
              {loadingTracks && <div className="text-gray-400 text-sm py-4 text-center">Loading tracks...</div>}
              {trackResults?.results?.length === 0 && !loadingTracks && (
                <div className="text-gray-500 text-sm py-4 text-center">No tracks found for this album</div>
              )}
              <div className="space-y-1">
                {trackResults?.results?.filter((t: TrackResult) =>
                  !trackSearch || t.title.toLowerCase().includes(trackSearch.toLowerCase())
                ).map((t: TrackResult) => (
                  <button
                    key={t.id}
                    onClick={() => setSelectedTrack(t)}
                    className={`w-full text-left px-3 py-2 rounded-lg flex items-center gap-3 transition-colors ${
                      selectedTrack?.id === t.id
                        ? 'bg-blue-500/20 border border-blue-500/40'
                        : 'hover:bg-gray-700'
                    }`}
                  >
                    <span className="text-gray-500 text-sm w-8 text-right shrink-0">
                      {t.disc_number && t.disc_number > 1 && `${t.disc_number}-`}{t.track_number || '-'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className="text-white truncate block">{t.title}</span>
                    </div>
                    <span className="text-gray-500 text-sm shrink-0">{formatDuration(t.duration_ms)}</span>
                    {t.has_file ? (
                      <span className="text-xs text-green-500 shrink-0 flex items-center gap-1">
                        <FiCheck size={12} /> Has file
                      </span>
                    ) : (
                      <span className="text-xs text-yellow-500 shrink-0">No file</span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-gray-700">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => linkMutation.mutate()}
            disabled={!selectedTrack || linkMutation.isPending}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg flex items-center gap-2 transition-colors"
          >
            {linkMutation.isPending ? (
              <>Linking...</>
            ) : (
              <>
                <FiLink size={16} />
                Link to Track
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

export default LinkFileModal
