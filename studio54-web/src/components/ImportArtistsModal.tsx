import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { museApi, libraryApi, artistsApi, authFetch } from '../api/client'
import { FiX, FiChevronRight, FiChevronLeft, FiDownload } from 'react-icons/fi'
import toast from 'react-hot-toast'

interface ImportArtistsModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}

type ImportSource = 'muse' | 'studio54'
type WizardStep = 'select-source' | 'select-library' | 'select-artists' | 'importing' | 'results'

interface LibraryArtist {
  name: string
  musicbrainz_id: string | null
  file_count: number
  album_count: number
  has_mbid: boolean
}

interface ImportResults {
  imported_count: number
  skipped_count: number
  failed_count: number
  imported_artists: Array<{ name: string; musicbrainz_id: string | null }>
  skipped_artists: string[]
}

function ImportArtistsModal({ isOpen, onClose, onSuccess }: ImportArtistsModalProps) {
  const [step, setStep] = useState<WizardStep>('select-source')
  const [source, setSource] = useState<ImportSource>('muse')
  const [selectedLibraryId, setSelectedLibraryId] = useState<string>('')
  const [selectedArtists, setSelectedArtists] = useState<Set<string>>(new Set())
  const [autoMatchMbid, setAutoMatchMbid] = useState(true)
  const [monitorImported, setMonitorImported] = useState(false)
  const [libraryArtists, setLibraryArtists] = useState<LibraryArtist[]>([])
  const [libraryName, setLibraryName] = useState('')
  const [importResults, setImportResults] = useState<ImportResults | null>(null)

  // Fetch MUSE libraries
  const { data: museLibraries, isLoading: loadingMuseLibraries } = useQuery({
    queryKey: ['muse-libraries'],
    queryFn: () => museApi.getLibraries(),
    enabled: isOpen && source === 'muse',
  })

  // Fetch Studio54 library paths
  const { data: studio54Libraries, isLoading: loadingStudio54Libraries } = useQuery({
    queryKey: ['studio54-library-paths'],
    queryFn: () => libraryApi.listPaths(),
    enabled: isOpen && source === 'studio54',
  })

  // Fetch artists from selected library
  const fetchArtistsMutation = useMutation({
    mutationFn: async (libraryId: string) => {
      if (source === 'muse') {
        return museApi.getArtists(libraryId, { limit: 1000 })
      } else {
        // For Studio54, we'll fetch from library files endpoint
        // This requires a new endpoint on the backend
        const response = await authFetch(`/api/v1/library/paths/${libraryId}/artists`)
        if (!response.ok) throw new Error('Failed to fetch artists')
        return response.json()
      }
    },
    onSuccess: (data) => {
      setLibraryArtists(data.artists)
      setLibraryName(data.library_name || 'Library')
      setStep('select-artists')
    },
    onError: (error) => {
      toast.error(`Failed to fetch artists: ${error}`)
    },
  })

  // Import artists mutation
  const importMutation = useMutation({
    mutationFn: async () => {
      const selectedArtistNames = libraryArtists
        .filter(artist => selectedArtists.has(artist.name))
        .map(artist => artist.name)

      if (source === 'muse') {
        return artistsApi.importFromMuse({
          library_id: selectedLibraryId,
          artist_names: selectedArtistNames,
          auto_match_mbid: autoMatchMbid,
          is_monitored: monitorImported,
        })
      } else {
        return artistsApi.importFromStudio54({
          library_id: selectedLibraryId,
          artist_names: selectedArtistNames,
          auto_match_mbid: autoMatchMbid,
          is_monitored: monitorImported,
        })
      }
    },
    onSuccess: (data) => {
      setImportResults(data)
      setStep('results')
      onSuccess()
    },
    onError: (error: any) => {
      console.error('Import error:', error)
      const errorMessage = error?.response?.data?.detail || error?.message || String(error)
      toast.error(`Import failed: ${errorMessage}`)
      setStep('select-artists') // Go back to artist selection on error
    },
  })

  const handleClose = () => {
    setStep('select-source')
    setSource('muse')
    setSelectedLibraryId('')
    setSelectedArtists(new Set())
    setLibraryArtists([])
    setAutoMatchMbid(true)
    setMonitorImported(false)
    onClose()
  }

  const handleSourceNext = () => {
    setStep('select-library')
  }

  const handleLibraryNext = () => {
    if (!selectedLibraryId) {
      toast.error('Please select a library')
      return
    }
    fetchArtistsMutation.mutate(selectedLibraryId)
  }

  const handleSelectAll = () => {
    if (selectedArtists.size === libraryArtists.length) {
      setSelectedArtists(new Set())
    } else {
      setSelectedArtists(new Set(libraryArtists.map(a => a.name)))
    }
  }

  const toggleArtist = (artistName: string) => {
    const newSelected = new Set(selectedArtists)
    if (newSelected.has(artistName)) {
      newSelected.delete(artistName)
    } else {
      newSelected.add(artistName)
    }
    setSelectedArtists(newSelected)
  }

  const handleImport = () => {
    if (selectedArtists.size === 0) {
      toast.error('Please select at least one artist')
      return
    }
    setStep('importing')
    importMutation.mutate()
  }

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
      onClick={(e) => {
        // Prevent closing modal while importing or viewing results, and only close if clicking the background
        if (e.target === e.currentTarget && step !== 'importing' && step !== 'results') {
          handleClose()
        }
      }}
    >
      <div
        className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
          <div>
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Import Artists</h2>
            {step !== 'results' && (
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                Step {step === 'select-source' ? 1 : step === 'select-library' ? 2 : step === 'select-artists' ? 3 : 4} of 4
              </p>
            )}
          </div>
          <button
            onClick={handleClose}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={step === 'importing' || step === 'results'}
          >
            <FiX className="w-6 h-6" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Step 1: Select Source */}
          {step === 'select-source' && (
            <div className="space-y-6">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Select Import Source</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <button
                    className={`p-6 border-2 rounded-lg transition-colors ${
                      source === 'muse'
                        ? 'border-[#FF1493] bg-[#FF1493]/5 dark:bg-[#FF1493]/10'
                        : 'border-gray-300 dark:border-[#30363D] hover:border-[#FF1493]'
                    }`}
                    onClick={() => setSource('muse')}
                  >
                    <h4 className="text-xl font-semibold text-gray-900 dark:text-white">MUSE Library</h4>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
                      Import artists from your MUSE music library
                    </p>
                  </button>
                  <button
                    className={`p-6 border-2 rounded-lg transition-colors ${
                      source === 'studio54'
                        ? 'border-[#FF1493] bg-[#FF1493]/5 dark:bg-[#FF1493]/10'
                        : 'border-gray-300 dark:border-[#30363D] hover:border-[#FF1493]'
                    }`}
                    onClick={() => setSource('studio54')}
                  >
                    <h4 className="text-xl font-semibold text-gray-900 dark:text-white">Studio54 Library</h4>
                    <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
                      Import artists from your local filesystem library
                    </p>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Step 2: Select Library */}
          {step === 'select-library' && (
            <div className="space-y-6">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
                  Select {source === 'muse' ? 'MUSE' : 'Studio54'} Library
                </h3>
                {source === 'muse' ? (
                  loadingMuseLibraries ? (
                    <div className="flex justify-center py-8">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]"></div>
                    </div>
                  ) : museLibraries && museLibraries.length > 0 ? (
                    <div className="space-y-2">
                      {museLibraries.map((library) => (
                        <button
                          key={library.id}
                          className={`w-full p-4 border-2 rounded-lg text-left transition-colors ${
                            selectedLibraryId === library.id
                              ? 'border-[#FF1493] bg-[#FF1493]/5 dark:bg-[#FF1493]/10'
                              : 'border-gray-300 dark:border-[#30363D] hover:border-[#FF1493]'
                          }`}
                          onClick={() => setSelectedLibraryId(library.id)}
                        >
                          <div className="font-semibold text-gray-900 dark:text-white">{library.name}</div>
                          <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">{library.path}</div>
                          <div className="text-xs text-gray-500 dark:text-gray-500 mt-1">
                            {library.total_files?.toLocaleString()} files
                          </div>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="text-gray-500 dark:text-gray-400">No MUSE libraries found</p>
                  )
                ) : loadingStudio54Libraries ? (
                  <div className="flex justify-center py-8">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#FF1493]"></div>
                  </div>
                ) : studio54Libraries && studio54Libraries.length > 0 ? (
                  <div className="space-y-2">
                    {studio54Libraries.map((library) => (
                      <button
                        key={library.id}
                        className={`w-full p-4 border-2 rounded-lg text-left transition-colors ${
                          selectedLibraryId === library.id
                            ? 'border-[#FF1493] bg-[#FF1493]/5 dark:bg-[#FF1493]/10'
                            : 'border-gray-300 dark:border-[#30363D] hover:border-[#FF1493]'
                        }`}
                        onClick={() => setSelectedLibraryId(library.id)}
                      >
                        <div className="font-semibold text-gray-900 dark:text-white">{library.name}</div>
                        <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">{library.path}</div>
                        <div className="text-xs text-gray-500 dark:text-gray-500 mt-1">
                          {library.total_files?.toLocaleString()} files
                        </div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-gray-500 dark:text-gray-400">No Studio54 libraries found</p>
                )}
              </div>
            </div>
          )}

          {/* Step 3: Select Artists */}
          {step === 'select-artists' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                  Select Artists from {libraryName}
                </h3>
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={handleSelectAll}
                >
                  {selectedArtists.size === libraryArtists.length ? 'Deselect All' : 'Select All'}
                </button>
              </div>

              {/* Options */}
              <div className="bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-4 space-y-3">
                <label className="flex items-center space-x-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoMatchMbid}
                    onChange={(e) => setAutoMatchMbid(e.target.checked)}
                    className="w-4 h-4 text-[#FF1493] border-gray-300 rounded focus:ring-[#FF1493]"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Auto-match MusicBrainz IDs (95% confidence threshold)
                  </span>
                </label>
                <label className="flex items-center space-x-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={monitorImported}
                    onChange={(e) => setMonitorImported(e.target.checked)}
                    className="w-4 h-4 text-[#FF1493] border-gray-300 rounded focus:ring-[#FF1493]"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">
                    Monitor imported artists (default: unmonitored)
                  </span>
                </label>
              </div>

              {/* Artists List */}
              <div className="border border-gray-300 dark:border-[#30363D] rounded-lg max-h-96 overflow-y-auto">
                {libraryArtists.length > 0 ? (
                  <div className="divide-y divide-gray-200 dark:divide-[#30363D]">
                    {libraryArtists.map((artist) => (
                      <label
                        key={artist.name}
                        className="flex items-center p-3 hover:bg-gray-50 dark:hover:bg-[#1C2128] cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={selectedArtists.has(artist.name)}
                          onChange={() => toggleArtist(artist.name)}
                          className="w-4 h-4 text-[#FF1493] border-gray-300 rounded focus:ring-[#FF1493]"
                        />
                        <div className="ml-3 flex-1">
                          <div className="flex items-center space-x-2">
                            <span className="font-medium text-gray-900 dark:text-white">{artist.name}</span>
                            {artist.has_mbid && (
                              <span className="badge badge-success text-xs">MBID</span>
                            )}
                          </div>
                          <div className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                            {artist.file_count} files • {artist.album_count} albums
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="p-8 text-center text-gray-500 dark:text-gray-400">
                    No artists found in this library
                  </div>
                )}
              </div>

              <div className="text-sm text-gray-600 dark:text-gray-400">
                {selectedArtists.size} of {libraryArtists.length} artists selected
              </div>
            </div>
          )}

          {/* Step 4: Importing */}
          {step === 'importing' && (
            <div className="flex flex-col items-center justify-center py-12 space-y-4">
              <div className="animate-spin rounded-full h-16 w-16 border-b-4 border-[#FF1493]"></div>
              <h3 className="text-xl font-semibold text-gray-900 dark:text-white">
                Importing Artists...
              </h3>
              <p className="text-gray-600 dark:text-gray-400">
                Importing {selectedArtists.size} artists from {libraryName}
              </p>
              <div className="mt-4 p-4 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg max-w-md">
                <p className="text-sm text-yellow-800 dark:text-yellow-200">
                  <strong>Please wait:</strong> Large imports may take several minutes.
                  {selectedArtists.size > 100 && (
                    <span> For {selectedArtists.size} artists, this could take {Math.ceil(selectedArtists.size / 10)} minutes or more.</span>
                  )}
                  {' '}The import will continue even if this dialog times out.
                </p>
              </div>
            </div>
          )}

          {/* Step 5: Results */}
          {step === 'results' && importResults && (
            <div className="py-6 space-y-6">
              <div className="text-center">
                <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                  Import Complete
                </h3>
                <p className="text-gray-600 dark:text-gray-400">
                  Here's what happened with your import
                </p>
              </div>

              {/* Summary Cards */}
              <div className="grid grid-cols-3 gap-4">
                <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4 text-center">
                  <div className="text-3xl font-bold text-green-600 dark:text-green-400">
                    {importResults.imported_count}
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">Imported</div>
                </div>
                <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 text-center">
                  <div className="text-3xl font-bold text-yellow-600 dark:text-yellow-400">
                    {importResults.skipped_count}
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">Skipped</div>
                </div>
                <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-center">
                  <div className="text-3xl font-bold text-red-600 dark:text-red-400">
                    {importResults.failed_count}
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">Failed</div>
                </div>
              </div>

              {/* Why Artists Were Skipped */}
              {importResults.skipped_count > 0 && (
                <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
                  <h4 className="font-semibold text-blue-900 dark:text-blue-100 mb-2">
                    Why were artists skipped?
                  </h4>
                  <p className="text-sm text-blue-800 dark:text-blue-200">
                    Artists are skipped when they don't have a MusicBrainz ID in your library files
                    and the automatic matching service can't find a confident match (≥95% confidence).
                    This is normal for artists with common names or special characters.
                  </p>
                </div>
              )}

              {/* Imported Artists List */}
              {importResults.imported_count > 0 && (
                <div>
                  <h4 className="font-semibold text-gray-900 dark:text-white mb-3">
                    Successfully Imported ({importResults.imported_count})
                  </h4>
                  <div className="max-h-48 overflow-y-auto bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3 space-y-1">
                    {importResults.imported_artists.map((artist, idx) => (
                      <div key={idx} className="text-sm text-gray-700 dark:text-gray-300">
                        • {artist.name}
                        {artist.musicbrainz_id && (
                          <span className="ml-2 text-xs text-green-600 dark:text-green-400">✓ MBID</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Skipped Artists Sample */}
              {importResults.skipped_count > 0 && (
                <div>
                  <h4 className="font-semibold text-gray-900 dark:text-white mb-3">
                    Skipped Artists (showing first 20 of {importResults.skipped_count})
                  </h4>
                  <div className="max-h-48 overflow-y-auto bg-gray-50 dark:bg-[#0D1117]/50 rounded-lg p-3 space-y-1">
                    {importResults.skipped_artists.slice(0, 20).map((name, idx) => (
                      <div key={idx} className="text-sm text-gray-600 dark:text-gray-400">
                        • {name}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-between p-6 border-t border-gray-200 dark:border-[#30363D]">
          <button
            className="btn btn-secondary"
            onClick={() => {
              if (step === 'select-library') setStep('select-source')
              else if (step === 'select-artists') setStep('select-library')
            }}
            disabled={step === 'select-source' || step === 'importing' || step === 'results'}
          >
            <FiChevronLeft className="w-4 h-4 mr-2" />
            Back
          </button>

          <div className="flex space-x-3">
            {step !== 'results' && (
              <button className="btn btn-secondary" onClick={handleClose} disabled={step === 'importing'}>
                Cancel
              </button>
            )}
            {step === 'select-source' && (
              <button className="btn btn-primary" onClick={handleSourceNext}>
                Next
                <FiChevronRight className="w-4 h-4 ml-2" />
              </button>
            )}
            {step === 'select-library' && (
              <button
                className="btn btn-primary"
                onClick={handleLibraryNext}
                disabled={!selectedLibraryId || fetchArtistsMutation.isPending}
              >
                {fetchArtistsMutation.isPending ? (
                  <>
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    Loading Artists...
                  </>
                ) : (
                  <>
                    Next
                    <FiChevronRight className="w-4 h-4 ml-2" />
                  </>
                )}
              </button>
            )}
            {step === 'select-artists' && (
              <button
                className="btn btn-primary"
                onClick={handleImport}
                disabled={selectedArtists.size === 0}
              >
                <FiDownload className="w-4 h-4 mr-2" />
                Import {selectedArtists.size} Artist{selectedArtists.size !== 1 ? 's' : ''}
              </button>
            )}
            {step === 'results' && (
              <button className="btn btn-primary" onClick={handleClose}>
                Done
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default ImportArtistsModal
