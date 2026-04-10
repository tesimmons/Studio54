import { useRef, useState } from 'react'
import { FiCamera, FiLoader, FiLink, FiX, FiCheck } from 'react-icons/fi'
import toast from 'react-hot-toast'

// Maps entity type to its cover art API endpoint pattern.
// These must match the actual FastAPI routes in the backend.
const COVER_ART_API_URL: Record<string, (id: string) => string> = {
  series: (id) => `/api/v1/series/${id}/cover-art`,
  book:   (id) => `/api/v1/books/${id}/cover-art`,
  author: (id) => `/api/v1/authors/${id}/cover-art`,
  artist: (id) => `/api/v1/${id}/cover-art`,
  album:  (id) => `/api/v1/${id}/cover-art`,
}

interface CoverArtUploaderProps {
  entityType: 'artist' | 'album' | 'author' | 'series' | 'book'
  entityId: string
  currentUrl: string | null | undefined
  onSuccess: () => void
  /** Upload function from the relevant API client */
  uploadFn: (entityId: string, file: File) => Promise<unknown>
  /** Upload-from-URL function from the relevant API client */
  uploadFromUrlFn: (entityId: string, url: string) => Promise<unknown>
  /** Fallback content when no cover art exists */
  fallback: React.ReactNode
  /** Alt text for the image */
  alt: string
  /** Additional className for the wrapper */
  className?: string
}

export default function CoverArtUploader({
  entityType,
  entityId,
  currentUrl,
  onSuccess,
  uploadFn,
  uploadFromUrlFn,
  fallback,
  alt,
  className = '',
}: CoverArtUploaderProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  // Incremented after each upload to bust the browser image cache
  const [cacheBust, setCacheBust] = useState(0)

  // 'idle' = normal hover overlay, 'menu' = show file/url choice, 'url' = url input mode
  const [mode, setMode] = useState<'idle' | 'menu' | 'url'>('idle')
  const [urlInput, setUrlInput] = useState('')

  // Build the URL to display the image.
  // - If currentUrl is an external http(s) URL, use it directly.
  // - If it's a local filesystem path or internal API path, route through
  //   the backend's serve endpoint (which handles redirects and file serving).
  // - After an upload (cacheBust > 0), always use the serve endpoint so the
  //   freshly saved image is fetched.
  const getImageSrc = () => {
    if (!currentUrl && cacheBust === 0) return null

    // After an upload, always go through the serve endpoint to pick up the new image
    if (cacheBust > 0) {
      const buildUrl = COVER_ART_API_URL[entityType]
      const base = buildUrl ? buildUrl(entityId) : currentUrl!
      return `${base}?t=${cacheBust}`
    }

    // External URL (fanart.tv, coverartarchive.org, etc.) — use directly
    if (currentUrl && (currentUrl.startsWith('http://') || currentUrl.startsWith('https://'))) {
      return currentUrl
    }

    // Local path or internal API path — serve through backend endpoint
    const buildUrl = COVER_ART_API_URL[entityType]
    if (!buildUrl) return currentUrl
    return buildUrl(entityId)
  }

  const handleOverlayClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (uploading) return
    setMode(m => m === 'menu' ? 'idle' : 'menu')
  }

  const handleFileChoice = (e: React.MouseEvent) => {
    e.stopPropagation()
    setMode('idle')
    fileInputRef.current?.click()
  }

  const handleUrlChoice = (e: React.MouseEvent) => {
    e.stopPropagation()
    setUrlInput('')
    setMode('url')
  }

  const handleDismiss = (e: React.MouseEvent) => {
    e.stopPropagation()
    setMode('idle')
    setUrlInput('')
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/tiff', 'image/bmp', 'image/x-bmp']
    if (!allowed.includes(file.type)) {
      toast.error('Accepted formats: JPEG, PNG, GIF, WebP, TIFF, BMP')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      toast.error('Image must be under 10 MB')
      return
    }

    setUploading(true)
    try {
      await uploadFn(entityId, file)
      toast.success('Cover art updated')
      setCacheBust((n) => n + 1)
      onSuccess()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to upload cover art'
      toast.error(msg)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleUrlSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const url = urlInput.trim()
    if (!url) return

    setUploading(true)
    try {
      await uploadFromUrlFn(entityId, url)
      toast.success('Cover art updated')
      setCacheBust((n) => n + 1)
      setMode('idle')
      setUrlInput('')
      onSuccess()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to fetch image from URL'
      toast.error(msg)
    } finally {
      setUploading(false)
    }
  }

  const imageSrc = getImageSrc()

  return (
    <div
      className={`relative group cursor-pointer ${className}`}
      onClick={handleOverlayClick}
    >
      {/* Image or fallback */}
      {imageSrc ? (
        <img
          src={imageSrc}
          alt={alt}
          className="w-full h-full object-cover"
        />
      ) : (
        fallback
      )}

      {/* URL input overlay — shown when mode === 'url' */}
      {mode === 'url' && (
        <div
          className="absolute inset-0 bg-black/75 flex flex-col items-center justify-center p-3 z-10"
          onClick={(e) => e.stopPropagation()}
        >
          {uploading ? (
            <FiLoader className="w-8 h-8 text-white animate-spin" />
          ) : (
            <form onSubmit={handleUrlSubmit} className="w-full flex flex-col gap-2">
              <p className="text-white text-xs text-center font-medium mb-1">Paste image URL</p>
              <input
                autoFocus
                type="url"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="https://example.com/image.jpg"
                className="w-full text-xs rounded px-2 py-1.5 bg-white/10 text-white placeholder-white/50 border border-white/30 focus:outline-none focus:border-white"
              />
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={!urlInput.trim()}
                  className="flex-1 flex items-center justify-center gap-1 text-xs bg-[#FF1493] hover:bg-[#d10f7a] disabled:opacity-40 text-white rounded py-1.5 transition-colors"
                >
                  <FiCheck className="w-3 h-3" /> Fetch
                </button>
                <button
                  type="button"
                  onClick={handleDismiss}
                  className="flex-1 flex items-center justify-center gap-1 text-xs bg-white/10 hover:bg-white/20 text-white rounded py-1.5 transition-colors"
                >
                  <FiX className="w-3 h-3" /> Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Default hover overlay with file / URL choice */}
      {mode !== 'url' && (
        <div
          className={`absolute inset-0 bg-black/50 transition-opacity flex flex-col items-center justify-center gap-3
            ${mode === 'menu' ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
        >
          {uploading ? (
            <FiLoader className="w-8 h-8 text-white animate-spin" />
          ) : (
            <>
              <button
                type="button"
                onClick={handleFileChoice}
                className="flex flex-col items-center gap-1 text-white hover:text-[#FF1493] transition-colors"
                title="Browse local file"
              >
                <FiCamera className="w-6 h-6" />
                <span className="text-xs font-medium">Browse</span>
              </button>
              <button
                type="button"
                onClick={handleUrlChoice}
                className="flex flex-col items-center gap-1 text-white hover:text-[#FF1493] transition-colors"
                title="Enter image URL"
              >
                <FiLink className="w-6 h-6" />
                <span className="text-xs font-medium">URL</span>
              </button>
            </>
          )}
        </div>
      )}

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp,image/tiff,image/bmp,.jpg,.jpeg,.png,.gif,.webp,.tif,.tiff,.bmp"
        className="hidden"
        onChange={handleFileChange}
      />
    </div>
  )
}
