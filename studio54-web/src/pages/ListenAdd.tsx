import { useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { FiMic, FiX, FiCheck, FiAlertCircle, FiSearch, FiPlus, FiRefreshCw } from 'react-icons/fi'
import toast from 'react-hot-toast'
import { listenApi, artistsApi, albumsApi } from '../api/client'
import { S54 } from '../assets/graphics'
import { encodeWAV } from '../utils/audioEncoder'
import type { IdentifyResult } from '../types'

type ListenState = 'idle' | 'listening' | 'analyzing' | 'found' | 'not-found' | 'error'

const RECORD_DURATION_MS = 20000

function ListenAdd() {
  const navigate = useNavigate()
  const [state, setState] = useState<ListenState>('idle')
  const [result, setResult] = useState<IdentifyResult | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [addingArtist, setAddingArtist] = useState(false)
  const [searchingDownload, setSearchingDownload] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [audioLevel, setAudioLevel] = useState(0) // 0-1 linear scale for dB meter

  const mediaStreamRef = useRef<MediaStream | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const meterFrameRef = useRef<number | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cancelledRef = useRef(false)

  const cleanup = useCallback(() => {
    if (meterFrameRef.current) {
      cancelAnimationFrame(meterFrameRef.current)
      meterFrameRef.current = null
    }
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {})
      audioContextRef.current = null
    }
    analyserRef.current = null
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => t.stop())
      mediaStreamRef.current = null
    }
    setAudioLevel(0)
  }, [])

  const startListening = useCallback(async () => {
    cancelledRef.current = false
    setElapsed(0)
    setResult(null)
    setErrorMessage('')

    // Check browser support
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setState('error')
      setErrorMessage(
        'Microphone access is not available. This feature requires HTTPS (or localhost). ' +
        'Please ensure you are accessing Studio54 over a secure connection.'
      )
      return
    }

    // Request microphone permission — let browser use its native sample rate
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: true,
        },
      })
    } catch (err: any) {
      setState('error')
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setErrorMessage(
          'Microphone permission denied. To use Listen & Add:\n\n' +
          '- Chrome: Click the lock icon in the address bar > Site settings > Microphone > Allow\n' +
          '- Firefox: Click the lock icon > Connection secure > More Information > Permissions\n' +
          '- Safari: Settings > Privacy > Microphone > Allow for this site'
        )
      } else if (err.name === 'NotFoundError') {
        setErrorMessage('No microphone found. Please connect a microphone and try again.')
      } else {
        setErrorMessage(`Could not access microphone: ${err.message || err.name}`)
      }
      return
    }

    mediaStreamRef.current = stream
    setState('listening')

    // Start elapsed timer
    const startTime = Date.now()
    timerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000))
    }, 500)

    // Capture raw PCM directly via Web Audio API — bypasses MediaRecorder encode/decode
    // which was producing near-silent audio (fingerprint only 66 chars for 14s).
    // ScriptProcessorNode is deprecated but functional in all browsers; AudioWorklet
    // requires a separate file and has CSP issues with blob URLs.
    try {
      const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)()
      audioContextRef.current = audioCtx
      const sourceNode = audioCtx.createMediaStreamSource(stream)
      const BUFFER_SIZE = 4096
      const processor = audioCtx.createScriptProcessor(BUFFER_SIZE, 1, 1)
      const pcmChunks: Float32Array[] = []

      processor.onaudioprocess = (e: AudioProcessingEvent) => {
        // Copy the input buffer (must copy — buffer is reused)
        const input = e.inputBuffer.getChannelData(0)
        pcmChunks.push(new Float32Array(input))
      }

      sourceNode.connect(processor)
      processor.connect(audioCtx.destination)

      // Set up AnalyserNode for real-time dB meter
      const analyser = audioCtx.createAnalyser()
      analyser.fftSize = 2048
      analyser.smoothingTimeConstant = 0.8
      sourceNode.connect(analyser)
      analyserRef.current = analyser
      const analyserData = new Float32Array(analyser.fftSize)

      const updateMeter = () => {
        if (!analyserRef.current) return
        analyserRef.current.getFloatTimeDomainData(analyserData)
        let peak = 0
        for (let i = 0; i < analyserData.length; i++) {
          const abs = Math.abs(analyserData[i])
          if (abs > peak) peak = abs
        }
        // Scale: raw mic peak is usually 0-0.1, normalize for display
        // Use a mild log scale so quiet sounds still show movement
        const displayLevel = Math.min(1, Math.max(0, (20 * Math.log10(Math.max(peak, 0.00001)) + 60) / 60))
        setAudioLevel(displayLevel)
        meterFrameRef.current = requestAnimationFrame(updateMeter)
      }
      meterFrameRef.current = requestAnimationFrame(updateMeter)

      // Wait for recording duration, checking for cancel
      await new Promise<void>((resolve) => {
        const timeout = setTimeout(() => resolve(), RECORD_DURATION_MS)
        const checkCancel = setInterval(() => {
          if (cancelledRef.current) {
            clearTimeout(timeout)
            clearInterval(checkCancel)
            resolve()
          }
        }, 200)
      })

      // Disconnect and stop
      processor.disconnect()
      sourceNode.disconnect()
      stream.getTracks().forEach(t => t.stop())
      mediaStreamRef.current = null

      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }

      if (cancelledRef.current) {
        audioCtx.close()
        audioContextRef.current = null
        setState('idle')
        return
      }

      setState('analyzing')

      // Concatenate PCM chunks into a single Float32Array
      const totalSamples = pcmChunks.reduce((sum, c) => sum + c.length, 0)
      const pcmData = new Float32Array(totalSamples)
      let offset = 0
      for (const chunk of pcmChunks) {
        pcmData.set(chunk, offset)
        offset += chunk.length
      }

      // Compute RMS and peak level, then normalize audio for robust fingerprinting.
      // Mic capture is often very quiet (RMS ~0.003) which produces weak spectral
      // data for chromaprint. Normalizing to peak=0.9 gives fpcalc clear tonal peaks.
      let sumSq = 0
      let peak = 0
      for (let i = 0; i < pcmData.length; i++) {
        sumSq += pcmData[i] * pcmData[i]
        const abs = Math.abs(pcmData[i])
        if (abs > peak) peak = abs
      }
      const rms = Math.sqrt(sumSq / pcmData.length)
      const nativeSampleRate = audioCtx.sampleRate
      const durationSec = totalSamples / nativeSampleRate
      console.log(`Listen: captured ${totalSamples} samples at ${nativeSampleRate}Hz, ${durationSec.toFixed(1)}s, RMS=${rms.toFixed(4)}, peak=${peak.toFixed(4)}`)

      // Normalize: scale so peak reaches 0.9 (headroom to avoid clipping)
      if (peak > 0.0001) {
        const gain = 0.9 / peak
        for (let i = 0; i < pcmData.length; i++) {
          pcmData[i] *= gain
        }
        console.log(`Listen: normalized audio — gain=${gain.toFixed(1)}x, new peak=0.9, new RMS=${(rms * gain).toFixed(4)}`)
      }

      // Create an AudioBuffer from the normalized PCM at native sample rate.
      // Skip resampling — fpcalc handles any sample rate internally (resamples to 11025Hz).
      // Avoiding 48000→44100→11025 double resampling prevents phase artifacts.
      const rawBuffer = audioCtx.createBuffer(1, totalSamples, nativeSampleRate)
      rawBuffer.getChannelData(0).set(pcmData)

      await audioCtx.close()
      audioContextRef.current = null

      // Encode as WAV at native sample rate
      const wavBlob = encodeWAV(rawBuffer)
      console.log(`Listen: WAV encoded — ${(wavBlob.size / 1024).toFixed(0)}KB, ${durationSec.toFixed(1)}s, ${nativeSampleRate}Hz mono, RMS=${rms.toFixed(4)}`)

      if (rms < 0.001) {
        setState('not-found')
        setErrorMessage('Audio level too low — microphone may not be picking up the music. Try moving closer to the speaker or increasing the volume.')
        return
      }

      const identifyResult = await listenApi.identify(wavBlob)
      setResult(identifyResult)

      if (identifyResult.identified) {
        setState('found')
      } else {
        setState('not-found')
        setErrorMessage(identifyResult.message || 'Could not identify the song.')
      }
    } catch (err: any) {
      cleanup()
      setState('error')
      setErrorMessage(`Recognition failed: ${err.message || 'Unknown error'}`)
    }
  }, [cleanup])

  const cancelListening = useCallback(() => {
    cancelledRef.current = true
    cleanup()
    setState('idle')
  }, [cleanup])

  const resetToIdle = useCallback(() => {
    cleanup()
    setState('idle')
    setResult(null)
    setErrorMessage('')
    setElapsed(0)
  }, [cleanup])

  const handleAddArtist = useCallback(async () => {
    if (!result?.artist?.mbid) {
      toast.error('No MusicBrainz ID available for this artist')
      return
    }
    setAddingArtist(true)
    try {
      await artistsApi.add({ musicbrainz_id: result.artist.mbid, monitored: true })
      toast.success(`Added ${result.artist.name} to library`)
      // Update result to reflect the artist is now in library
      setResult(prev => prev ? {
        ...prev,
        artist: { ...prev.artist!, exists_in_library: true },
      } : null)
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to add artist'
      toast.error(msg)
    } finally {
      setAddingArtist(false)
    }
  }, [result])

  const handleSearchDownload = useCallback(async () => {
    if (!result?.album?.library_id) {
      toast.error('Album must be in the library first to search for downloads')
      return
    }
    setSearchingDownload(true)
    try {
      await albumsApi.search(result.album.library_id)
      toast.success('Download search started')
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || 'Failed to start search'
      toast.error(msg)
    } finally {
      setSearchingDownload(false)
    }
  }, [result])

  const confidencePercent = result?.confidence ? Math.round(result.confidence * 100) : 0
  const confidenceColor = confidencePercent >= 80 ? 'text-green-400' : confidencePercent >= 50 ? 'text-yellow-400' : 'text-red-400'

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="text-center">
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Listen & Add</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          Identify a song playing nearby and add it to your library
        </p>
      </div>

      {/* Main Card */}
      <div className="card p-6 md:p-8">
        {/* IDLE STATE */}
        {state === 'idle' && (
          <div className="flex flex-col items-center space-y-6 py-8">
            <button
              onClick={startListening}
              className="group relative w-40 h-40 rounded-full bg-gradient-to-br from-[#FF1493]/20 to-[#FF8C00]/20 hover:from-[#FF1493]/30 hover:to-[#FF8C00]/30 border-2 border-[#FF1493]/30 hover:border-[#FF1493]/60 transition-all duration-300 flex items-center justify-center"
            >
              <img
                src={S54.listen}
                alt="Listen"
                className="w-24 h-24 object-contain group-hover:scale-110 transition-transform duration-300"
              />
            </button>
            <div className="text-center">
              <p className="text-lg font-semibold text-gray-900 dark:text-white">Tap to Listen</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Hold your device near the speaker and we'll identify the song
              </p>
            </div>
          </div>
        )}

        {/* LISTENING STATE */}
        {state === 'listening' && (
          <div className="flex flex-col items-center space-y-6 py-8">
            <div className="relative w-40 h-40 flex items-center justify-center">
              {/* Animated rings */}
              <div className="absolute inset-0 rounded-full border-2 border-[#FF1493]/40 animate-ping" />
              <div className="absolute inset-4 rounded-full border-2 border-[#FF1493]/30 animate-ping" style={{ animationDelay: '0.3s' }} />
              <div className="absolute inset-8 rounded-full border-2 border-[#FF1493]/20 animate-ping" style={{ animationDelay: '0.6s' }} />
              <FiMic className="w-16 h-16 text-[#FF1493] animate-pulse" />
            </div>
            <div className="text-center">
              <p className="text-lg font-semibold text-gray-900 dark:text-white">Listening...</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                {elapsed}s / {RECORD_DURATION_MS / 1000}s — Keep your device near the speaker
              </p>
              {/* Progress bar */}
              <div className="w-64 mx-auto mt-3 h-1.5 bg-gray-200 dark:bg-[#30363D] rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-[#FF1493] to-[#FF8C00] rounded-full transition-all duration-500"
                  style={{ width: `${Math.min((elapsed / (RECORD_DURATION_MS / 1000)) * 100, 100)}%` }}
                />
              </div>
              {/* Audio level meter */}
              <div className="w-64 mx-auto mt-3">
                <div className="flex items-center space-x-2">
                  <FiMic className="w-3 h-3 text-gray-400 flex-shrink-0" />
                  <div className="flex-1 h-2 bg-gray-200 dark:bg-[#30363D] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-75"
                      style={{
                        width: `${Math.min(audioLevel * 100, 100)}%`,
                        backgroundColor: audioLevel > 0.8 ? '#ef4444' : audioLevel > 0.5 ? '#FF8C00' : '#22c55e',
                      }}
                    />
                  </div>
                  <span className="text-[10px] text-gray-400 w-10 text-right font-mono flex-shrink-0">
                    {audioLevel > 0.01 ? `${Math.round((20 * Math.log10(Math.max(audioLevel, 0.001))))}dB` : '-∞dB'}
                  </span>
                </div>
                <p className="text-[10px] text-gray-400 mt-0.5">
                  {audioLevel < 0.15 ? 'Low — move closer to speaker' : audioLevel < 0.5 ? 'Good level' : 'Strong signal'}
                </p>
              </div>
            </div>
            <button
              onClick={cancelListening}
              className="flex items-center space-x-2 px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-red-500 dark:hover:text-red-400 transition-colors"
            >
              <FiX className="w-4 h-4" />
              <span>Cancel</span>
            </button>
          </div>
        )}

        {/* ANALYZING STATE */}
        {state === 'analyzing' && (
          <div className="flex flex-col items-center space-y-6 py-8">
            <div className="w-16 h-16 border-4 border-[#FF1493]/30 border-t-[#FF1493] rounded-full animate-spin" />
            <div className="text-center">
              <p className="text-lg font-semibold text-gray-900 dark:text-white">Identifying song...</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Analyzing audio fingerprint
              </p>
            </div>
          </div>
        )}

        {/* FOUND STATE */}
        {state === 'found' && result && (
          <div className="space-y-6">
            {/* Song Info */}
            <div className="text-center space-y-2">
              <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-xs font-medium">
                <FiCheck className="w-3.5 h-3.5" />
                <span>Song Identified</span>
              </div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">{result.title}</h2>
              <p className="text-lg text-gray-600 dark:text-gray-300">{result.artist?.name}</p>
              {result.album?.name && (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Album: {result.album.name}
                </p>
              )}
              <p className={`text-xs font-medium ${confidenceColor}`}>
                {confidencePercent}% confidence
              </p>
            </div>

            {/* Library Status */}
            <div className="space-y-3">
              {/* Artist Status */}
              <div className="flex items-center justify-between px-4 py-3 rounded-lg bg-gray-50 dark:bg-[#0D1117] border border-gray-200 dark:border-[#30363D]">
                <div>
                  <p className="text-sm font-medium text-gray-900 dark:text-white">Artist: {result.artist?.name}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {result.artist?.exists_in_library ? 'In your library' : 'Not in library'}
                  </p>
                </div>
                {result.artist?.exists_in_library ? (
                  <span className="flex items-center space-x-1 text-xs text-green-500">
                    <FiCheck className="w-4 h-4" />
                    <span>In Library</span>
                  </span>
                ) : result.artist?.mbid ? (
                  <button
                    onClick={handleAddArtist}
                    disabled={addingArtist}
                    className="flex items-center space-x-1 px-3 py-1.5 text-xs font-medium text-white bg-[#FF1493] hover:bg-[#d10f7a] rounded-lg transition-colors disabled:opacity-50"
                  >
                    {addingArtist ? (
                      <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    ) : (
                      <FiPlus className="w-3.5 h-3.5" />
                    )}
                    <span>Add Artist</span>
                  </button>
                ) : (
                  <span className="text-xs text-gray-400">No MBID</span>
                )}
              </div>

              {/* Album Status */}
              {result.album?.name && (
                <div className="flex items-center justify-between px-4 py-3 rounded-lg bg-gray-50 dark:bg-[#0D1117] border border-gray-200 dark:border-[#30363D]">
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white">Album: {result.album.name}</p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {result.album.exists_in_library ? 'In your library' : 'Not in library'}
                    </p>
                  </div>
                  {result.album.exists_in_library ? (
                    <button
                      onClick={() => navigate(`/disco-lounge/albums/${result.album!.library_id}`)}
                      className="flex items-center space-x-1 text-xs text-[#FF1493] hover:text-[#d10f7a] transition-colors"
                    >
                      <span>View Album</span>
                    </button>
                  ) : (
                    <span className="text-xs text-gray-400">
                      {result.artist?.exists_in_library ? 'Sync artist to add albums' : 'Add artist first'}
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              {result.album?.exists_in_library && result.album?.library_id && (
                <button
                  onClick={handleSearchDownload}
                  disabled={searchingDownload}
                  className="flex items-center space-x-2 px-4 py-2 text-sm font-medium text-white bg-[#FF8C00] hover:bg-[#e67e00] rounded-lg transition-colors disabled:opacity-50"
                >
                  {searchingDownload ? (
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  ) : (
                    <FiSearch className="w-4 h-4" />
                  )}
                  <span>Search for Download</span>
                </button>
              )}
              <button
                onClick={resetToIdle}
                className="flex items-center space-x-2 px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-[#161B22] hover:bg-gray-200 dark:hover:bg-[#1C2128] rounded-lg transition-colors"
              >
                <FiRefreshCw className="w-4 h-4" />
                <span>Listen Again</span>
              </button>
            </div>
          </div>
        )}

        {/* NOT FOUND STATE */}
        {state === 'not-found' && (
          <div className="flex flex-col items-center space-y-6 py-8">
            <div className="w-16 h-16 rounded-full bg-yellow-100 dark:bg-yellow-900/20 flex items-center justify-center">
              <FiAlertCircle className="w-8 h-8 text-yellow-500" />
            </div>
            <div className="text-center">
              <p className="text-lg font-semibold text-gray-900 dark:text-white">Song Not Identified</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 max-w-sm">
                {errorMessage || 'Could not identify the song. Try recording for longer or moving closer to the speaker.'}
              </p>
            </div>
            <button
              onClick={resetToIdle}
              className="flex items-center space-x-2 px-4 py-2 text-sm font-medium text-white bg-[#FF1493] hover:bg-[#d10f7a] rounded-lg transition-colors"
            >
              <FiRefreshCw className="w-4 h-4" />
              <span>Try Again</span>
            </button>
          </div>
        )}

        {/* ERROR STATE */}
        {state === 'error' && (
          <div className="flex flex-col items-center space-y-6 py-8">
            <div className="w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/20 flex items-center justify-center">
              <FiAlertCircle className="w-8 h-8 text-red-500" />
            </div>
            <div className="text-center">
              <p className="text-lg font-semibold text-gray-900 dark:text-white">Something Went Wrong</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 max-w-md whitespace-pre-line">
                {errorMessage}
              </p>
            </div>
            <button
              onClick={resetToIdle}
              className="flex items-center space-x-2 px-4 py-2 text-sm font-medium text-white bg-[#FF1493] hover:bg-[#d10f7a] rounded-lg transition-colors"
            >
              <FiRefreshCw className="w-4 h-4" />
              <span>Try Again</span>
            </button>
          </div>
        )}
      </div>

      {/* Info Card */}
      {state === 'idle' && (
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-2">How it works</h3>
          <ol className="text-sm text-gray-500 dark:text-gray-400 space-y-1.5 list-decimal list-inside">
            <li>Tap the listen button and hold your device near the speaker</li>
            <li>We'll record about {RECORD_DURATION_MS / 1000} seconds of audio</li>
            <li>The audio fingerprint is matched against the AcoustID database</li>
            <li>If identified, you can add the artist/album to your library</li>
          </ol>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-3">
            Requires microphone permission and HTTPS connection.
          </p>
        </div>
      )}
    </div>
  )
}

export default ListenAdd
