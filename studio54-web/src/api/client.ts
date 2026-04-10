/**
 * Studio54 API Client
 * Handles all HTTP requests to the Studio54 backend
 */

import axios, { AxiosInstance, AxiosError } from 'axios'
import type { AuthUser, LoginResponse } from '../types'
import type {
  Artist,
  Album,
  Track,
  Author,
  Series,
  Book,
  Chapter,
  Indexer,
  DownloadClient,
  DownloadQueueEntry,
  SystemStats,
  MuseLibrary,
  MusicBrainzArtist,
  PaginatedResponse,
  Playlist,
  PlaylistDetail,
  LibraryPath,
  LibraryFile,
  ScanJob,
  LibraryStats,
  RootFolder,
  QualityProfile,
  NotificationProfile,
  DjRequest,
  DjRequestUserSummary,
  StorageMount,
  IdentifyResult,
} from '../types'

// Create axios instance with base configuration
const api: AxiosInstance = axios.create({
  baseURL: (import.meta as any).env?.VITE_API_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor - inject Bearer token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('studio54_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Rewrite coverartarchive.org URLs to use our backend proxy (archive.org blocks direct browser requests)
const COVER_ART_RE = /https?:\/\/coverartarchive\.org\/release\/([^/]+)\/(.+)/
function proxyCoverArtUrls(data: any): any {
  if (typeof data === 'string') {
    return data.replace(COVER_ART_RE, '/api/v1/cover-art-proxy/$1/$2')
  }
  if (Array.isArray(data)) {
    return data.map(proxyCoverArtUrls)
  }
  if (data && typeof data === 'object') {
    const result: any = {}
    for (const key of Object.keys(data)) {
      result[key] = proxyCoverArtUrls(data[key])
    }
    return result
  }
  return data
}

// Response interceptor for error handling + 401 redirect
api.interceptors.response.use(
  (response) => {
    if (response.data) {
      response.data = proxyCoverArtUrls(response.data)
    }
    return response
  },
  (error: AxiosError) => {
    if (error.response) {
      if (error.response.status === 401) {
        // Token expired or invalid - clear auth and redirect to login
        localStorage.removeItem('studio54_token')
        localStorage.removeItem('studio54_user')
        // Only redirect if not already on login page
        if (!window.location.pathname.includes('/login')) {
          window.location.href = '/login'
        }
      }
      console.error('API Error:', error.response.status, error.response.data)
    } else if (error.request) {
      console.error('Network Error:', error.message)
    } else {
      console.error('Request Error:', error.message)
    }
    return Promise.reject(error)
  }
)

// Authenticated fetch wrapper for code that uses native fetch() instead of axios
export function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const token = localStorage.getItem('studio54_token')
  const headers = new Headers(init?.headers)
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  if (!headers.has('Content-Type') && init?.body && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }
  return fetch(url, { ...init, headers })
}

// ==================== ARTISTS ====================

export const artistsApi = {
  // Search MusicBrainz for artists
  search: async (query: string, limit = 25): Promise<{ results: MusicBrainzArtist[] }> => {
    const { data } = await api.post('/artists/search', null, {
      params: { query, limit },
    })
    return data
  },

  // Add artist to monitoring
  add: async (params: {
    musicbrainz_id: string
    monitored?: boolean
    root_folder_path?: string
    quality_profile_id?: string
    monitor_type?: string
    search_for_missing?: boolean
  }): Promise<Artist> => {
    const { data } = await api.post('/artists', {
      musicbrainz_id: params.musicbrainz_id,
      is_monitored: params.monitored ?? true,
      root_folder_path: params.root_folder_path,
      quality_profile_id: params.quality_profile_id,
      monitor_type: params.monitor_type ?? 'all_albums',
      search_for_missing: params.search_for_missing ?? false,
    })
    return data
  },

  // List monitored artists
  list: async (monitoredOnly = false): Promise<Artist[]> => {
    const { data } = await api.get('/artists', {
      params: { monitored_only: monitoredOnly },
    })
    return data.artists
  },

  // Get artist details (includes albums array)
  get: async (artistId: string): Promise<Artist & { albums: Album[] }> => {
    const { data } = await api.get(`/artists/${artistId}`)
    return data
  },

  // Update artist
  update: async (
    artistId: string,
    updates: Partial<Pick<Artist, 'is_monitored' | 'quality_profile_id' | 'root_folder_path'>>
  ): Promise<Artist> => {
    const { data } = await api.patch(`/artists/${artistId}`, updates)
    return data
  },

  // Sync artist albums from MusicBrainz
  sync: async (artistId: string): Promise<{ success: boolean; task_id: string }> => {
    const { data } = await api.post(`/artists/${artistId}/sync`)
    return data
  },

  // Delete artist
  delete: async (artistId: string, deleteFiles = false): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/artists/${artistId}`, {
      params: { delete_files: deleteFiles },
    })
    return data
  },

  // Import artists from MUSE library
  importFromMuse: async (params: {
    library_id: string
    artist_names?: string[]
    auto_match_mbid?: boolean
    is_monitored?: boolean
  }): Promise<{
    imported_count: number
    skipped_count: number
    failed_count: number
    imported_artists: Array<{ name: string; musicbrainz_id: string | null }>
    skipped_artists: string[]
  }> => {
    // Use longer timeout for large imports (10 minutes)
    const { data } = await api.post('/artists/import/muse', params, { timeout: 600000 })
    return data
  },

  // Import artists from Studio54 local library
  importFromStudio54: async (params: {
    library_id: string
    artist_names?: string[]
    auto_match_mbid?: boolean
    is_monitored?: boolean
  }): Promise<{
    imported_count: number
    skipped_count: number
    failed_count: number
    imported_artists: Array<{ name: string; musicbrainz_id: string | null }>
    skipped_artists: string[]
  }> => {
    // Use longer timeout for large imports (10 minutes)
    const { data } = await api.post('/artists/import/studio54', params, { timeout: 600000 })
    return data
  },

  // Bulk update artists (monitor/unmonitor)
  bulkUpdate: async (
    artistIds: string[],
    updates: {
      is_monitored?: boolean
      quality_profile_id?: string
    }
  ): Promise<{ updated_count: number }> => {
    const { data } = await api.patch('/artists/bulk-update', {
      artist_ids: artistIds,
      ...updates,
    })
    return data
  },

  // Refresh metadata for individual artist
  refreshMetadata: async (artistId: string): Promise<{
    success: boolean
    artist_id: string
    artist_name: string
    message: string
    task_id: string
  }> => {
    const { data } = await api.post(`/artists/${artistId}/refresh-metadata?force=true`)
    return data
  },

  // Get external (Last.fm) top tracks for artist
  getTopTracksExternal: async (artistId: string, limit = 10): Promise<ExternalTopTracksResponse> => {
    const { data } = await api.get(`/artists/${artistId}/top-tracks-external`, {
      params: { limit },
    })
    return data
  },

  // Refresh metadata for all artists
  refreshAllMetadata: async (): Promise<{
    success: boolean
    message: string
    total_artists: number
    task_id: string
  }> => {
    const { data } = await api.post('/artists/refresh-all-metadata')
    return data
  },

  // Sync all albums and tracks for every artist in the library
  syncAllAlbums: async (): Promise<{
    success: boolean
    message: string
    total_artists: number
    task_id: string
  }> => {
    const { data } = await api.post('/artists/sync-all-albums')
    return data
  },

  // Import unlinked artists (files with MBIDs but no matching track in DB)
  // Returns a task_id — work is done asynchronously by Celery
  importUnlinked: async (params?: {
    library_path_id?: string
    is_monitored?: boolean
    auto_sync?: boolean
  }): Promise<{
    success: boolean
    task_id: string
    message: string
  }> => {
    const { data } = await api.post('/artists/import-unlinked', params || {})
    return data
  },

  // Get orphaned artists (unmonitored with no linked files)
  getOrphaned: async (): Promise<{
    success: boolean
    count: number
    orphaned_artists: Array<{
      id: string
      name: string
      musicbrainz_id: string
      added_at: string | null
      album_count: number
      track_count: number
    }>
  }> => {
    const { data } = await api.get('/artists/orphaned')
    return data
  },

  // Resolve MBID for a single artist via local MBDB
  resolveMbid: async (artistId: string): Promise<{
    artist_id: string
    artist_name: string
    current_mbid: string | null
    matches: Array<{
      id: string
      name: string
      disambiguation: string
      type: string | null
      score: number
    }>
    total: number
  }> => {
    const { data } = await api.post(`/artists/${artistId}/resolve-mbid`)
    return data
  },

  // Set/update an artist's MusicBrainz ID
  setMusicbrainzId: async (artistId: string, musicbrainzId: string, triggerSync = true): Promise<{
    success: boolean
    artist_id: string
    artist_name: string
    musicbrainz_id: string
    old_musicbrainz_id: string | null
    sync_task_id: string | null
  }> => {
    const { data } = await api.patch(`/artists/${artistId}/musicbrainz-id`, {
      musicbrainz_id: musicbrainzId,
      trigger_sync: triggerSync,
    })
    return data
  },

  // Bulk resolve MBIDs via local MBDB
  bulkResolveMbid: async (): Promise<{
    resolved: Array<{ id: string; name: string; mbid: string; score: number; matched_name: string }>
    unresolved: Array<{ id: string; name: string; top_match: { name: string; mbid: string; score: number } | null }>
    stats: { total: number; resolved: number; unresolved: number }
  }> => {
    const { data } = await api.post('/artists/bulk-resolve-mbid', null, { timeout: 300000 })
    return data
  },

  // Bulk resolve MBIDs via remote MusicBrainz API
  bulkResolveMbidRemote: async (artistIds: string[]): Promise<{
    success: boolean
    task_id: string
    artist_count: number
    message: string
  }> => {
    const { data } = await api.post('/artists/bulk-resolve-mbid/remote', { artist_ids: artistIds })
    return data
  },

  // Cleanup orphaned artists
  cleanupOrphaned: async (): Promise<{
    success: boolean
    deleted_count: number
    message: string
    deleted_artists: Array<{ id: string; name: string; musicbrainz_id: string }>
  }> => {
    const { data } = await api.delete('/artists/cleanup-orphaned')
    return data
  },

  setRating: async (artistId: string, rating: number | null): Promise<{ id: string; name: string; rating_override: number | null }> => {
    const { data } = await api.patch(`/artists/${artistId}/rating`, { rating })
    return data
  },

  uploadCoverArt: async (artistId: string, file: File): Promise<{ success: boolean; image_url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await api.post(`/artists/${artistId}/cover-art`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  uploadCoverArtFromUrl: async (artistId: string, url: string): Promise<{ success: boolean; image_url: string }> => {
    const { data } = await api.post(`/artists/${artistId}/cover-art-from-url`, { url })
    return data
  },
}

// ==================== ALBUMS ====================

export const albumsApi = {
  // List albums
  list: async (params?: {
    search_query?: string
    status?: string
    artist_id?: string
    monitored_only?: boolean
    limit?: number
    offset?: number
  }): Promise<PaginatedResponse<Album>> => {
    const { data } = await api.get('/albums', { params })
    return {
      total_count: data.total_count,
      limit: data.limit,
      offset: data.offset,
      items: data.albums,
    }
  },

  // Get wanted albums
  getWanted: async (limit = 100, offset = 0): Promise<Album[]> => {
    const { data } = await api.get('/albums/wanted', {
      params: { limit, offset },
    })
    return data.wanted_albums
  },

  // Get calendar (upcoming releases)
  getCalendar: async (startDate?: string, endDate?: string): Promise<Album[]> => {
    const { data } = await api.get('/albums/calendar', {
      params: { start_date: startDate, end_date: endDate },
    })
    return data.releases
  },

  // Get album details
  get: async (albumId: string): Promise<Album & { tracks: Track[]; downloads: DownloadQueueEntry[] }> => {
    const { data } = await api.get(`/albums/${albumId}`)
    return data
  },

  // Update album
  update: async (
    albumId: string,
    updates: Partial<Pick<Album, 'monitored' | 'status' | 'custom_folder_path'>>
  ): Promise<Album> => {
    const { data } = await api.patch(`/albums/${albumId}`, updates)
    return data
  },

  // Search for album
  search: async (
    albumId: string,
    skipMuseCheck = false
  ): Promise<{ success: boolean; task_id?: string; already_exists?: boolean }> => {
    const { data } = await api.post(`/albums/${albumId}/search`, null, {
      params: { skip_muse_check: skipMuseCheck },
    })
    return data
  },

  // Bulk update album monitoring
  bulkUpdate: async (albumIds: string[], monitored: boolean): Promise<{
    success: boolean
    updated_count: number
  }> => {
    const { data } = await api.patch('/albums/bulk-update', {
      album_ids: albumIds,
      monitored,
    })
    return data
  },

  // Monitor/unmonitor albums by type for an artist
  monitorByType: async (artistId: string, albumType: string | null, monitored: boolean): Promise<{
    success: boolean
    updated_count: number
  }> => {
    const { data } = await api.post('/albums/monitor-by-type', {
      artist_id: artistId,
      album_type: albumType,
      monitored,
    })
    return data
  },

  // Verify album in MUSE
  verifyMuse: async (albumId: string, updateStatus = true): Promise<{
    exists_in_muse: boolean
    file_count: number
    message: string
  }> => {
    const { data } = await api.post(`/albums/${albumId}/verify-muse`, null, {
      params: { update_status: updateStatus },
    })
    return data
  },

  // Prefetch lyrics for all tracks in an album
  prefetchLyrics: async (albumId: string): Promise<{
    total: number
    fetched: number
    already_cached: number
    failed: number
  }> => {
    const { data } = await api.post(`/albums/${albumId}/prefetch-lyrics`)
    return data
  },

  // Clear download history for album
  clearDownloads: async (albumId: string, statusFilter?: string): Promise<{
    cleared: number
    album_id: string
    album_status: string
  }> => {
    const { data } = await api.delete(`/albums/${albumId}/downloads`, {
      params: statusFilter ? { status_filter: statusFilter } : undefined,
    })
    return data
  },

  uploadCoverArt: async (albumId: string, file: File): Promise<{ success: boolean; cover_art_url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await api.post(`/albums/${albumId}/cover-art`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  uploadCoverArtFromUrl: async (albumId: string, url: string): Promise<{ success: boolean; cover_art_url: string }> => {
    const { data } = await api.post(`/albums/${albumId}/cover-art-from-url`, { url })
    return data
  },
}

// ==================== TRACKS ====================

export interface TrackListItem {
  id: string
  title: string
  track_number: number
  disc_number: number
  duration_ms: number | null
  has_file: boolean
  file_path: string | null
  file_format: string | null
  musicbrainz_id: string | null
  album_id: string
  album_title: string
  album_cover_art_url: string | null
  artist_id: string | null
  artist_name: string
  monitored: boolean
  rating: number | null
  average_rating: number | null
}

export interface LyricsResponse {
  synced_lyrics: string | null
  plain_lyrics: string | null
  source: string | null
  has_synced: boolean
}

export interface TopTracksResponse {
  source: 'play_count' | 'newest'
  tracks: (TrackListItem & { play_count: number })[]
}

export interface ExternalTopTrack {
  track_name: string
  listeners: number
  playcount: number
  local_track_id: string | null
  has_file: boolean
  file_path: string | null
  album_title: string | null
  album_cover_art_url: string | null
  album_id: string | null
  duration_ms: number | null
  artist_name: string
  artist_id: string
}

export interface ExternalTopTracksResponse {
  error: string | null
  tracks: ExternalTopTrack[]
}

export const tracksApi = {
  list: async (params?: {
    search_query?: string
    has_file?: boolean
    artist_id?: string
    album_id?: string
    limit?: number
    offset?: number
  }): Promise<{ total_count: number; tracks: TrackListItem[] }> => {
    const { data } = await api.get('/tracks', { params })
    return { total_count: data.total_count, tracks: data.tracks }
  },

  getLyrics: async (trackId: string): Promise<LyricsResponse> => {
    const { data } = await api.get(`/tracks/${trackId}/lyrics`)
    return data
  },

  recordPlay: async (trackId: string): Promise<{ play_count: number }> => {
    const { data } = await api.post(`/tracks/${trackId}/record-play`)
    return data
  },

  getTopTracks: async (artistId: string, limit = 10): Promise<TopTracksResponse> => {
    const { data } = await api.get('/tracks/top', {
      params: { artist_id: artistId, limit },
    })
    return data
  },

  search: async (trackId: string): Promise<{ success: boolean; message: string; task_id?: string }> => {
    const { data } = await api.post(`/tracks/${trackId}/search`)
    return data
  },

  deleteFile: async (trackId: string): Promise<{ success: boolean; message: string; deleted_path: string }> => {
    const { data } = await api.delete(`/tracks/${trackId}/file`)
    return data
  },

  getRating: async (trackId: string): Promise<{ track_id: string; average_rating: number | null; user_rating: number | null; rating_count: number }> => {
    const { data } = await api.get(`/tracks/${trackId}/rating`)
    return data
  },

  setRating: async (trackId: string, rating: number | null): Promise<{ id: string; title: string; average_rating: number | null; user_rating: number | null; rating_count: number }> => {
    const { data } = await api.patch(`/tracks/${trackId}/rating`, { rating })
    return data
  },

  download: async (trackId: string): Promise<Blob> => {
    const { data } = await api.get(`/tracks/${trackId}/download`, {
      responseType: 'blob',
    })
    return data
  },
}

// ==================== INDEXERS ====================

export const indexersApi = {
  // List indexers
  list: async (enabledOnly = false): Promise<Indexer[]> => {
    const { data } = await api.get('/indexers', {
      params: { enabled_only: enabledOnly },
    })
    return data.indexers
  },

  // Add indexer
  add: async (indexer: {
    name: string
    base_url: string
    api_key: string
    indexer_type: string
    priority: number
    is_enabled: boolean
    categories: number[]
    rate_limit_per_second: number
  }): Promise<Indexer> => {
    const { data } = await api.post('/indexers', indexer)
    return data
  },

  // Get indexer
  get: async (indexerId: string): Promise<Indexer> => {
    const { data } = await api.get(`/indexers/${indexerId}`)
    return data
  },

  // Update indexer
  update: async (indexerId: string, updates: Partial<Indexer>): Promise<Indexer> => {
    const { data } = await api.patch(`/indexers/${indexerId}`, updates)
    return data
  },

  // Delete indexer
  delete: async (indexerId: string): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/indexers/${indexerId}`)
    return data
  },

  // Test indexer
  test: async (indexerId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/indexers/${indexerId}/test`)
    return data
  },

  // Test indexer configuration before saving
  testConfig: async (indexer: {
    name: string
    base_url: string
    api_key: string
    indexer_type: string
    priority: number
    is_enabled: boolean
    categories: number[]
    rate_limit_per_second: number
  }): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post('/indexers/test-config', indexer)
    return data
  },

  // Get API key for existing indexer
  getApiKey: async (indexerId: string): Promise<{ api_key: string }> => {
    const { data } = await api.get(`/indexers/${indexerId}/api-key`)
    return data
  },
}

// ==================== DOWNLOAD CLIENTS ====================

export const downloadClientsApi = {
  // List download clients
  list: async (enabledOnly = false): Promise<DownloadClient[]> => {
    const { data } = await api.get('/download-clients', {
      params: { enabled_only: enabledOnly },
    })
    return data.clients
  },

  // Add download client
  add: async (client: {
    name: string
    client_type: string
    host: string
    port: number
    use_ssl: boolean
    api_key: string
    category: string
    priority: number
    is_enabled: boolean
    is_default: boolean
  }): Promise<DownloadClient> => {
    const { data } = await api.post('/download-clients', client)
    return data
  },

  // Get download client
  get: async (clientId: string): Promise<DownloadClient> => {
    const { data } = await api.get(`/download-clients/${clientId}`)
    return data
  },

  // Update download client
  update: async (clientId: string, updates: Partial<DownloadClient>): Promise<DownloadClient> => {
    const { data } = await api.patch(`/download-clients/${clientId}`, updates)
    return data
  },

  // Delete download client
  delete: async (clientId: string): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/download-clients/${clientId}`)
    return data
  },

  // Test download client
  test: async (clientId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/download-clients/${clientId}/test`)
    return data
  },

  // Test download client configuration before saving
  testConfig: async (client: {
    name: string
    client_type: string
    host: string
    port: number
    use_ssl: boolean
    api_key: string
    category: string
    priority: number
    is_enabled: boolean
    is_default: boolean
  }): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post('/download-clients/test-config', client)
    return data
  },

  // Get API key for existing download client
  getApiKey: async (clientId: string): Promise<{ api_key: string }> => {
    const { data} = await api.get(`/download-clients/${clientId}/api-key`)
    return data
  },
}

// ==================== MUSE INTEGRATION ====================

export const museApi = {
  // Get MUSE libraries
  getLibraries: async (): Promise<MuseLibrary[]> => {
    const { data } = await api.get('/muse/libraries')
    return data.libraries
  },

  // Get library stats
  getLibraryStats: async (libraryId: string): Promise<MuseLibrary> => {
    const { data } = await api.get(`/muse/libraries/${libraryId}/stats`)
    return data.library
  },

  // Get artists from MUSE library
  getArtists: async (
    libraryId: string,
    options?: {
      limit?: number
      offset?: number
      missing_mbid_only?: boolean
    }
  ): Promise<{
    library_id: string
    library_name: string
    total_artists: number
    artists: Array<{
      name: string
      musicbrainz_id: string | null
      file_count: number
      album_count: number
      has_mbid: boolean
    }>
  }> => {
    const { data } = await api.get(`/muse/libraries/${libraryId}/artists`, {
      params: options
    })
    return data
  },

  // Verify album exists in MUSE
  verifyAlbum: async (
    musicbrainzId: string,
    minTrackCount = 1
  ): Promise<{ exists: boolean; file_count: number; recommendation: string }> => {
    const { data } = await api.post('/muse/verify-album', {
      musicbrainz_id: musicbrainzId,
      min_track_count: minTrackCount,
    })
    return data
  },

  // Trigger MUSE scan
  triggerScan: async (libraryId: string, pathHint?: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post('/muse/trigger-scan', {
      library_id: libraryId,
      path_hint: pathHint,
    })
    return data
  },

  // Find missing albums
  findMissing: async (artistId?: string, museLibraryId?: string): Promise<{
    total_artists_checked: number
    total_albums_checked: number
    missing_albums_found: number
    missing_albums: Array<{
      artist_name: string
      album_title: string
      musicbrainz_id: string
      release_date: string
      album_id: string
    }>
  }> => {
    const { data } = await api.post('/muse/find-missing', {
      artist_id: artistId,
      muse_library_id: museLibraryId,
    })
    return data
  },

  // Test MUSE connection
  testConnection: async (): Promise<{ muse_available: boolean; message: string }> => {
    const { data } = await api.get('/muse/connection-test')
    return data
  },

  // Check album quality
  checkQuality: async (
    musicbrainzId: string,
    minQualityScore = 70
  ): Promise<{
    meets_quality: boolean
    average_quality_score: number | null
    recommendation: string
    message: string
  }> => {
    const { data } = await api.get(`/muse/quality-check/${musicbrainzId}`, {
      params: { min_quality_score: minQualityScore },
    })
    return data
  },
}

// ==================== PLAYLISTS ====================

export const playlistsApi = {
  // List playlists
  list: async (limit = 100, offset = 0): Promise<PaginatedResponse<Playlist>> => {
    const { data } = await api.get('/playlists', {
      params: { limit, offset },
    })
    return {
      total_count: data.total_count,
      limit: data.limit,
      offset: data.offset,
      items: data.playlists,
    }
  },

  // Get playlist details with tracks
  get: async (playlistId: string): Promise<PlaylistDetail> => {
    const { data } = await api.get(`/playlists/${playlistId}`)
    return data
  },

  // Create playlist
  create: async (playlist: {
    name: string
    description?: string
  }): Promise<Playlist> => {
    const { data } = await api.post('/playlists', playlist)
    return data
  },

  // Update playlist
  update: async (
    playlistId: string,
    updates: { name?: string; description?: string }
  ): Promise<Playlist> => {
    const { data } = await api.put(`/playlists/${playlistId}`, updates)
    return data
  },

  // Delete playlist
  delete: async (playlistId: string): Promise<void> => {
    await api.delete(`/playlists/${playlistId}`)
  },

  // Add track to playlist
  addTrack: async (playlistId: string, trackId: string): Promise<{ message: string; track_count: number }> => {
    const { data } = await api.post(`/playlists/${playlistId}/tracks`, { track_id: trackId })
    return data
  },

  // Add multiple tracks to playlist in bulk
  addTracksBulk: async (playlistId: string, trackIds: string[]): Promise<{ message: string; added_count: number; skipped_count: number; track_count: number }> => {
    const { data } = await api.post(`/playlists/${playlistId}/tracks/bulk`, { track_ids: trackIds })
    return data
  },

  // Add chapter to playlist
  addChapter: async (playlistId: string, chapterId: string): Promise<{ message: string; track_count: number }> => {
    const { data } = await api.post(`/playlists/${playlistId}/chapters`, { chapter_id: chapterId })
    return data
  },

  // Add multiple chapters to playlist in bulk
  addChaptersBulk: async (playlistId: string, chapterIds: string[]): Promise<{ message: string; added_count: number; skipped_count: number; track_count: number }> => {
    const { data } = await api.post(`/playlists/${playlistId}/chapters/bulk`, { chapter_ids: chapterIds })
    return data
  },

  // Remove track from playlist
  removeTrack: async (playlistId: string, trackId: string): Promise<void> => {
    await api.delete(`/playlists/${playlistId}/tracks/${trackId}`)
  },

  // Reorder tracks in playlist
  reorder: async (
    playlistId: string,
    trackPositions: Array<{ track_id: string; position: number }>
  ): Promise<{ message: string }> => {
    const { data } = await api.put(`/playlists/${playlistId}/reorder`, { track_positions: trackPositions })
    return data
  },

  // List published playlists (Sound Booth)
  listPublished: async (limit = 100, offset = 0): Promise<PaginatedResponse<Playlist>> => {
    const { data } = await api.get('/playlists/published', {
      params: { limit, offset },
    })
    return {
      total_count: data.total_count,
      limit: data.limit,
      offset: data.offset,
      items: data.playlists,
    }
  },

  // Publish playlist to Sound Booth
  publish: async (playlistId: string): Promise<Playlist> => {
    const { data } = await api.post(`/playlists/${playlistId}/publish`)
    return data
  },

  // Unpublish playlist from Sound Booth
  unpublish: async (playlistId: string): Promise<Playlist> => {
    const { data } = await api.post(`/playlists/${playlistId}/unpublish`)
    return data
  },

  // Upload cover art
  uploadCoverArt: async (playlistId: string, file: File): Promise<{ message: string; cover_art_url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await api.post(`/playlists/${playlistId}/cover-art`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },
}

// ==================== LIBRARY SCANNER ====================

export const libraryApi = {
  // List library paths
  listPaths: async (libraryType?: string): Promise<LibraryPath[]> => {
    const { data } = await api.get('/library/paths', {
      params: libraryType ? { library_type: libraryType } : undefined,
    })
    return data.library_paths
  },

  // Add library path
  addPath: async (path: {
    path: string
    name: string
    is_enabled?: boolean
    library_type?: string
  }): Promise<LibraryPath> => {
    const { data } = await api.post('/library/paths', path)
    return data
  },

  // Update library path
  updatePath: async (
    pathId: string,
    updates: { name?: string; is_enabled?: boolean }
  ): Promise<{ message: string }> => {
    const { data } = await api.patch(`/library/paths/${pathId}`, updates)
    return data
  },

  // Delete library path
  deletePath: async (pathId: string): Promise<void> => {
    await api.delete(`/library/paths/${pathId}`)
  },

  // Start scan
  startScan: async (
    pathId: string,
    options?: { incremental?: boolean; fetch_images?: boolean }
  ): Promise<{
    scan_job_id: string
    celery_task_id: string
    status: string
    message: string
  }> => {
    const { data } = await api.post(`/library/paths/${pathId}/scan`, {
      incremental: options?.incremental ?? true,
      fetch_images: options?.fetch_images ?? true,
    })
    return data
  },

  // List scans
  listScans: async (libraryPathId?: string, limit = 50, libraryType?: string): Promise<ScanJob[]> => {
    const { data } = await api.get('/library/scans', {
      params: { library_path_id: libraryPathId, limit, library_type: libraryType },
    })
    return data.scans
  },

  // Get scan status
  getScanStatus: async (scanId: string): Promise<ScanJob> => {
    const { data } = await api.get(`/library/scans/${scanId}`)
    return data
  },

  // Search files
  searchFiles: async (params?: {
    library_path_id?: string
    library_type?: string
    artist?: string
    album?: string
    title?: string
    format?: string
    limit?: number
    offset?: number
  }): Promise<PaginatedResponse<LibraryFile>> => {
    const { data } = await api.get('/library/files', { params })
    return {
      total_count: data.total_count,
      limit: data.limit,
      offset: data.offset,
      items: data.files,
    }
  },

  // Get library stats
  getStats: async (libraryType?: string): Promise<LibraryStats> => {
    const { data } = await api.get('/library/stats', {
      params: libraryType ? { library_type: libraryType } : undefined,
    })
    return data
  },

  // Browse filesystem
  browseFolders: async (path: string = '/'): Promise<{
    current_path: string
    parent_path: string | null
    directories: Array<{ name: string; path: string; is_readable: boolean }>
  }> => {
    const { data } = await api.get('/library/filesystem/browse', {
      params: { path }
    })
    return data
  },

  // Cancel scan
  cancelScan: async (scanId: string): Promise<{ message: string; scan_id: string; status: string }> => {
    const { data } = await api.post(`/library/scans/${scanId}/cancel`)
    return data
  },

  // Rescan single file
  rescanFile: async (fileId: string): Promise<{ message: string; file_id: string; file_path: string }> => {
    const { data } = await api.post(`/library/files/${fileId}/rescan`)
    return data
  },

  // Rescan by album
  rescanByAlbum: async (album: string, artist?: string): Promise<{ message: string; file_count: number; task_id: string }> => {
    const { data } = await api.post('/library/rescan-by-album', null, {
      params: { album, artist }
    })
    return data
  },

  // Rescan by artist
  rescanByArtist: async (artist: string): Promise<{ message: string; file_count: number; task_id: string }> => {
    const { data } = await api.post('/library/rescan-by-artist', null, {
      params: { artist }
    })
    return data
  },
}

// ==================== JOBS ====================

export interface Job {
  id: string
  job_type: string
  entity_type?: string
  entity_id?: string
  status: string
  current_step?: string
  progress_percent: number
  items_processed: number
  items_total?: number
  speed_metric?: number
  eta_seconds?: number
  error_message?: string
  error_traceback?: string
  log_file_path?: string
  created_at: string
  started_at?: string
  updated_at: string
  completed_at?: string
  last_heartbeat_at?: string
  celery_task_id?: string
  worker_id?: string
  retry_count?: number
  max_retries?: number
  checkpoint_data?: any
  result_data?: any
}

export interface JobStats {
  total_jobs: number
  running: number
  completed: number
  failed: number
  pending: number
  paused: number
  cancelled: number
  stalled: number
  retrying: number
  by_type: Record<string, number>
}

export const jobsApi = {
  // List jobs
  list: async (params?: {
    status?: string
    job_type?: string
    entity_id?: string
    limit?: number
    offset?: number
  }): Promise<{ jobs: Job[]; total_count: number }> => {
    const { data } = await api.get('/jobs', { params })
    return { jobs: data.jobs, total_count: data.total_count }
  },

  // Get job by ID
  get: async (jobId: string): Promise<Job> => {
    const { data } = await api.get(`/jobs/${jobId}`)
    return data
  },

  // Get job stats
  getStats: async (jobType?: string): Promise<JobStats> => {
    const { data } = await api.get('/jobs/stats', {
      params: { job_type: jobType }
    })
    return data
  },

  // Cancel job
  cancel: async (jobId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/jobs/${jobId}/cancel`)
    return data
  },

  // Pause job
  pause: async (jobId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/jobs/${jobId}/pause`)
    return data
  },

  // Resume job
  resume: async (jobId: string): Promise<{ success: boolean; message: string; celery_task_id?: string }> => {
    const { data } = await api.post(`/jobs/${jobId}/resume`)
    return data
  },

  // Retry job
  retry: async (jobId: string): Promise<{ success: boolean; new_job_id: string }> => {
    const { data } = await api.post(`/jobs/${jobId}/retry`)
    return data
  },

  // Delete job (force=true for stale/orphaned jobs)
  delete: async (jobId: string, force: boolean = false): Promise<{ success: boolean; forced?: boolean }> => {
    const { data } = await api.delete(`/jobs/${jobId}`, {
      params: { force }
    })
    return data
  },

  // Clear all job history
  clearAll: async (includeActive: boolean = false): Promise<{ success: boolean; deleted_count: number; message: string }> => {
    const { data } = await api.delete('/jobs', {
      params: { include_active: includeActive }
    })
    return data
  },

  // Get log content for a job
  getLogContent: async (jobId: string, params?: {
    lines?: number
    offset?: number
    tail?: boolean
  }): Promise<{
    job_id: string
    job_type: string
    log_available: boolean
    content: string
    total_lines: number
    lines_returned: number
    offset: number
    tail: boolean
    log_file_path?: string
  }> => {
    const { data } = await api.get(`/jobs/${jobId}/log/content`, { params })
    return data
  },

  // Get log download URL
  getLogDownloadUrl: (jobId: string): string => {
    return `${api.defaults.baseURL}/jobs/${jobId}/log`
  },
}

// ==================== FILE ORGANIZATION ====================

export interface FileOrganizationJob {
  id: string
  job_type: string
  status: string
  progress_percent: number
  current_action?: string
  files_total: number
  files_processed: number
  files_renamed: number
  files_moved: number
  files_failed: number
  files_without_mbid?: number
  started_at?: string
  completed_at?: string
  created_at: string
  error_message?: string
  log_file_path?: string
  library_path_id?: string
  artist_id?: string
  album_id?: string
}

export interface OrganizationOptions {
  dry_run?: boolean
  create_metadata_files?: boolean
  only_with_mbid?: boolean
  only_unorganized?: boolean
}

export const fileOrganizationApi = {
  // Organize artist files
  organizeArtist: async (
    artistId: string,
    options?: OrganizationOptions
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/artists/${artistId}/organize`, options)
    return data
  },

  // Organize album files
  organizeAlbum: async (
    albumId: string,
    options?: OrganizationOptions
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/albums/${albumId}/organize`, options)
    return data
  },

  // Organize library path
  organizeLibraryPath: async (
    libraryPathId: string,
    options?: OrganizationOptions
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/library-paths/${libraryPathId}/organize`, options)
    return data
  },

  // Validate library structure
  validateLibraryPath: async (
    libraryPathId: string,
    options?: OrganizationOptions
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/library-paths/${libraryPathId}/validate`, options)
    return data
  },

  // Fetch metadata job
  fetchMetadata: async (
    libraryPathId: string,
    options?: OrganizationOptions
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/library-paths/${libraryPathId}/fetch-metadata`, options)
    return data
  },

  // Validate MBID job
  validateMbid: async (
    libraryPathId: string,
    options?: OrganizationOptions
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/library-paths/${libraryPathId}/validate-mbid`, options)
    return data
  },

  // Link files job
  linkFiles: async (
    libraryPathId: string,
    options?: OrganizationOptions
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/library-paths/${libraryPathId}/link-files`, options)
    return data
  },

  // Reindex albums job
  reindexAlbums: async (
    libraryPathId: string,
    options?: OrganizationOptions
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/library-paths/${libraryPathId}/reindex-albums`, options)
    return data
  },

  // Verify audio job
  verifyAudio: async (
    libraryPathId: string,
    daysBack?: number
  ): Promise<{ job_id: string; status: string; message: string }> => {
    const { data } = await api.post(`/file-organization/library-paths/${libraryPathId}/verify-audio`, null, {
      params: { days_back: daysBack }
    })
    return data
  },

  // Get organization job status
  getJob: async (jobId: string): Promise<FileOrganizationJob> => {
    const { data } = await api.get(`/file-organization/jobs/${jobId}`)
    return data
  },

  // List organization jobs
  listJobs: async (params?: {
    library_path_id?: string
    artist_id?: string
    album_id?: string
    status?: string
    job_type?: string
    limit?: number
    offset?: number
  }): Promise<{ jobs: FileOrganizationJob[]; total_count: number }> => {
    const { data } = await api.get('/file-organization/jobs', { params })
    return data
  },

  // Cleanup old logs
  cleanupLogs: async (retentionDays?: number): Promise<{
    success: boolean
    deleted_files: number
    space_freed_mb: number
    message: string
  }> => {
    const { data } = await api.post('/jobs/cleanup-logs', { retention_days: retentionDays })
    return data
  },

  // Preview log cleanup
  previewLogCleanup: async (retentionDays?: number): Promise<{
    files_to_delete: number
    estimated_space_mb: number
    cutoff_date: string
    retention_days: number
    file_paths: string[]
  }> => {
    const { data } = await api.get('/jobs/cleanup-logs/preview', {
      params: { retention_days: retentionDays }
    })
    return data
  },

  // ==================== LIBRARY MIGRATION ====================

  // Start library migration
  startMigration: async (params: {
    source_library_id: string
    destination_library_id?: string
    new_library_name?: string
    new_library_path?: string
    min_confidence?: number
    correct_metadata?: boolean
    create_metadata_files?: boolean
  }): Promise<{
    job_id: string
    status: string
    source_library: { id: string; name: string; path: string }
    destination_library: { id: string; name: string; path: string }
    estimated_files: number
    message: string
  }> => {
    const { data } = await api.post('/file-organization/library-migration', params)
    return data
  },

  // Get migration job status
  getMigrationStatus: async (jobId: string): Promise<{
    id: string
    job_type: string
    status: string
    progress_percent: number
    current_action: string | null
    files_total: number
    files_processed: number
    files_with_mbid: number
    files_mbid_fetched: number
    files_metadata_corrected: number
    files_validated: number
    files_moved: number
    files_failed: number
    followup_job_id: string | null
    started_at: string | null
    completed_at: string | null
    error_message: string | null
  }> => {
    const { data } = await api.get(`/file-organization/library-migration/${jobId}`)
    return data
  },

  // Get migration success log
  getMigrationSuccessLog: async (jobId: string): Promise<{
    count: number
    files: Array<{
      source_path: string
      destination_path: string
      recording_mbid: string
      confidence_score: number
      validation_tag: string
      timestamp: string
    }>
  }> => {
    const { data } = await api.get(`/file-organization/library-migration/${jobId}/logs/success`)
    return data
  },

  // Get migration failed log
  getMigrationFailedLog: async (jobId: string): Promise<{
    count: number
    files: Array<{
      file_path: string
      operation: string
      error: string
      timestamp: string
    }>
  }> => {
    const { data } = await api.get(`/file-organization/library-migration/${jobId}/logs/failed`)
    return data
  },

  // Get migration skipped log
  getMigrationSkippedLog: async (jobId: string): Promise<{
    count: number
    files: Array<{
      file_path: string
      reason: string
      ponder_eligible: boolean
      timestamp: string
    }>
  }> => {
    const { data } = await api.get(`/file-organization/library-migration/${jobId}/logs/skipped`)
    return data
  },

  // Get migration summary
  getMigrationSummary: async (jobId: string): Promise<{
    job_id: string
    status: string
    total_files: number
    success_count: number
    failed_count: number
    skipped_count: number
    ponder_count: number
    duration_seconds: number | null
  }> => {
    const { data } = await api.get(`/file-organization/library-migration/${jobId}/summary`)
    return data
  },

  // Retry failed migration files
  retryFailedMigration: async (
    jobId: string,
    includeSkipped: boolean = true
  ): Promise<{
    job_id: string
    status: string
    estimated_files: number
    message: string
  }> => {
    const { data } = await api.post(`/file-organization/library-migration/${jobId}/retry-failed`, null, {
      params: { include_skipped: includeSkipped }
    })
    return data
  },

  // Unlinked files
  getUnlinkedFiles: async (params?: {
    reason?: string
    artist?: string
    search?: string
    library_path_id?: string
    library_type?: string
    sort_by?: string
    sort_dir?: string
    page?: number
    per_page?: number
  }) => {
    const { data } = await api.get('/file-organization/unlinked-files', { params })
    return data
  },

  getUnlinkedSummary: async (params?: { library_type?: string }) => {
    const { data } = await api.get('/file-organization/unlinked-files/summary', { params })
    return data
  },

  resolveUnlinkedFiles: async (
    libraryPathId?: string
  ): Promise<{ job_id: string; status: string; message: string; estimated_files?: number }> => {
    const { data } = await api.post('/file-organization/files/resolve-unlinked', null, {
      params: libraryPathId ? { library_path_id: libraryPathId } : undefined,
      timeout: 60000,
    })
    return data
  },

  exportUnlinkedCsv: async (reason?: string) => {
    const { data } = await api.get('/file-organization/unlinked-files/export', {
      params: reason ? { reason } : undefined,
      responseType: 'blob'
    })
    return data
  },

  cleanupResolvedUnlinked: async () => {
    const { data } = await api.delete('/file-organization/unlinked-files/resolved')
    return data
  },

  // Delete unlinked file from disk and DB
  deleteUnlinkedFile: async (id: string): Promise<{ success: boolean; deleted_path: string }> => {
    const { data } = await api.delete(`/file-organization/unlinked-files/${id}`)
    return data
  },

  // Edit metadata on unlinked file (writes to audio tags + DB)
  updateUnlinkedMetadata: async (id: string, fields: { artist?: string; album?: string; title?: string }) => {
    const { data } = await api.patch(`/file-organization/unlinked-files/${id}/metadata`, fields)
    return data
  },

  // Link unlinked file to a specific track
  linkUnlinkedFile: async (id: string, trackId: string, acoustidScore?: number) => {
    const body: any = { track_id: trackId }
    if (acoustidScore !== undefined) body.acoustid_score = acoustidScore
    const { data } = await api.post(`/file-organization/unlinked-files/${id}/link`, body)
    return data as { success: boolean; new_path: string; track_title: string; album_title: string; artist_name: string }
  },

  // Search for link targets (artists, albums, tracks)
  searchLinkTargets: async (id: string, query: string, type: 'artist' | 'album' | 'track', filters?: { artist_id?: string; album_id?: string }) => {
    const { data } = await api.get(`/file-organization/unlinked-files/${id}/link-search`, {
      params: { query, type, ...filters }
    })
    return data as { type: string; results: any[] }
  },

  // Get albums for an artist (for linking flow)
  getArtistAlbumsForLinking: async (artistId: string) => {
    const { data } = await api.get(`/file-organization/unlinked-files/artists/${artistId}/albums`)
    return data as { results: any[] }
  },

  // Get tracks for an album (for linking flow)
  getAlbumTracksForLinking: async (albumId: string) => {
    const { data } = await api.get(`/file-organization/unlinked-files/albums/${albumId}/tracks`)
    return data as { results: any[] }
  },

  // AcoustID fingerprint lookup
  acoustidLookup: async (id: string) => {
    const { data } = await api.post(`/file-organization/unlinked-files/${id}/acoustid-lookup`, null, { timeout: 45000 })
    return data as {
      file_path: string
      duration: number
      matches: Array<{
        score: number
        recording_mbid: string
        title: string
        artist: string | null
        artist_mbid: string | null
        album: string | null
        album_type: string | null
        release_group_mbid: string | null
      }>
    }
  },

  // Unorganized files
  getUnorganizedFiles: async (params?: {
    search?: string
    format?: string
    library_type?: string
    sort_by?: string
    sort_dir?: string
    page?: number
    per_page?: number
  }) => {
    const { data } = await api.get('/file-organization/unorganized-files', { params })
    return data
  },

  getUnorganizedSummary: async (params?: { library_type?: string }) => {
    const { data } = await api.get('/file-organization/unorganized-files/summary', { params })
    return data
  },
}

// ==================== ROOT FOLDERS ====================

export const rootFoldersApi = {
  // List root folders
  list: async (): Promise<RootFolder[]> => {
    const { data } = await api.get('/root-folders')
    return data.root_folders
  },

  // Add root folder
  add: async (path: string, library_type: string = 'music'): Promise<RootFolder> => {
    const { data } = await api.post('/root-folders', { path, library_type })
    return data
  },

  // Delete root folder
  delete: async (rootFolderId: string): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/root-folders/${rootFolderId}`)
    return data
  },
}

// ==================== QUALITY PROFILES ====================

export const qualityProfilesApi = {
  // List quality profiles
  list: async (): Promise<QualityProfile[]> => {
    const { data } = await api.get('/quality-profiles')
    return data.quality_profiles
  },

  // Create quality profile
  create: async (profile: {
    name: string
    allowed_formats: string[]
    preferred_formats?: string[]
    min_bitrate?: number | null
    max_size_mb?: number | null
    upgrade_enabled?: boolean
    upgrade_until_quality?: string | null
    is_default?: boolean
  }): Promise<QualityProfile> => {
    const { data } = await api.post('/quality-profiles', profile)
    return data
  },

  // Update quality profile
  update: async (profileId: string, updates: Partial<QualityProfile>): Promise<QualityProfile> => {
    const { data } = await api.patch(`/quality-profiles/${profileId}`, updates)
    return data
  },

  // Delete quality profile
  delete: async (profileId: string): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/quality-profiles/${profileId}`)
    return data
  },
}

// ==================== NOTIFICATIONS ====================

export const notificationsApi = {
  // List notification profiles
  list: async (): Promise<NotificationProfile[]> => {
    const { data } = await api.get('/notifications')
    return data.notifications
  },

  // Create notification profile
  create: async (profile: {
    name: string
    provider: string
    webhook_url: string
    is_enabled: boolean
    events: string[]
  }): Promise<NotificationProfile> => {
    const { data } = await api.post('/notifications', profile)
    return data
  },

  // Update notification profile
  update: async (id: string, updates: {
    name?: string
    provider?: string
    webhook_url?: string
    is_enabled?: boolean
    events?: string[]
  }): Promise<NotificationProfile> => {
    const { data } = await api.patch(`/notifications/${id}`, updates)
    return data
  },

  // Delete notification profile
  delete: async (id: string): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/notifications/${id}`)
    return data
  },

  // Test notification
  test: async (id: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/notifications/${id}/test`)
    return data
  },
}

// ==================== DOWNLOAD HISTORY ====================

export const downloadHistoryApi = {
  getHistory: async (params?: {
    event_type?: string
    status_filter?: string
    date_from?: string
    date_to?: string
    album_id?: string
    artist_id?: string
    limit?: number
    offset?: number
  }): Promise<{
    total: number
    items: Array<{
      id: string
      event_type: string
      release_guid: string | null
      release_title: string | null
      album_id: string | null
      album_title: string | null
      artist_id: string | null
      artist_name: string | null
      quality: string | null
      source: string | null
      message: string | null
      download_path: string | null
      occurred_at: string | null
    }>
  }> => {
    const { data } = await api.get('/queue/history', { params })
    return data
  },
}

// ==================== SEARCH ====================

export const searchApi = {
  // Search for missing albums
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
}

// ==================== SYSTEM ====================

export const systemApi = {
  // Get system stats
  getStats: async (libraryType?: string): Promise<SystemStats> => {
    const { data } = await api.get('/stats', {
      params: libraryType ? { library_type: libraryType } : undefined,
    })
    return data
  },

  // Get comprehensive statistics
  getStatistics: async (libraryType?: string) => {
    const { data } = await api.get('/statistics', {
      params: libraryType ? { library_type: libraryType } : undefined,
    })
    return data
  },

  // Health check
  health: async (): Promise<{ status: string; database: string; redis: string }> => {
    const { data } = await api.get('/health')
    return data
  },
}

// ==================== ADMIN ====================

export interface SystemResourceStats {
  cpu_percent: number
  memory: {
    used_bytes: number
    total_bytes: number
    percent: number
  }
  disk: {
    used_bytes: number
    total_bytes: number
    percent: number
  }
  gpu: {
    name: string
    utilization_percent: number
    memory_used_mb: number
    memory_total_mb: number
  } | null
  top_cpu_processes: {
    pid: number
    name: string
    cpu_percent: number
  }[]
  top_memory_processes: {
    pid: number
    name: string
    memory_percent: number
    memory_mb: number
  }[]
  network?: {
    bytes_sent: number
    bytes_recv: number
  }
}

export const adminApi = {
  // Clear library database
  clearLibrary: async (options: {
    keep_playlists: boolean
    keep_watched_artists: boolean
  }): Promise<{
    success: boolean
    message: string
    summary: Record<string, number | boolean>
  }> => {
    const { data } = await api.delete('/admin/library/clear', { data: options })
    return data
  },

  // Get system resource stats (CPU, memory, disk, GPU)
  getSystemStats: async (): Promise<SystemResourceStats> => {
    const { data } = await api.get('/admin/system/stats')
    return data
  },
}

// ==================== QUEUE STATUS ====================

export interface QueueStatusResponse {
  timestamp: string
  summary: {
    total_pending: number
    total_active: number
    total_reserved: number
    total_workers: number
    active_search_locks: number
  }
  queues: Record<string, number>
  workers: Array<{
    name: string
    active_tasks: number
    reserved_tasks: number
    pool_size: number
    tasks_completed: number
    active_task_names: Array<{
      name: string
      id: string
      runtime: number
    }>
  }>
}

export const queueStatusApi = {
  getStatus: async (): Promise<QueueStatusResponse> => {
    const { data } = await api.get('/queue-status')
    return data
  },

  purgeQueue: async (queueName: string): Promise<{ success: boolean; messages_purged: number }> => {
    const { data } = await api.post(`/queue-status/purge/${queueName}`)
    return data
  },
}

// MusicBrainz Settings
export interface MusicBrainzStats {
  artists: number
  recordings: number
  release_groups: number
  releases: number
  last_replication: string | null
  replication_sequence: number | null
}

export interface MusicBrainzSettings {
  local_db_enabled: boolean
  local_db_url: string
  local_db_status: 'connected' | 'disconnected' | 'loading' | 'not_configured'
  local_db_stats: MusicBrainzStats | null
  api_rate_limit: number
  api_fallback_enabled: boolean
}

export const settingsApi = {
  getMusicBrainz: async (): Promise<MusicBrainzSettings> => {
    const { data } = await api.get('/settings/musicbrainz')
    return data
  },

  updateMusicBrainz: async (settings: { local_db_enabled?: boolean; api_rate_limit?: number }): Promise<MusicBrainzSettings> => {
    const { data } = await api.put('/settings/musicbrainz', settings)
    return data
  },

  testMusicBrainzConnection: async (): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post('/settings/musicbrainz/test-connection')
    return data
  },

  searchMusicBrainzLocal: async (params: {
    query: string
    search_type: 'artist' | 'album' | 'track'
    artist_filter?: string
    limit?: number
  }): Promise<{ results: any[]; search_type: string; query: string }> => {
    const { data } = await api.get('/settings/musicbrainz/search', { params })
    return data
  },

  getAlbumTypeFilters: async (): Promise<{ enabled_types: string[] }> => {
    const { data } = await api.get('/settings/album-type-filters')
    return data
  },

  updateAlbumTypeFilters: async (types: string[]): Promise<{ enabled_types: string[] }> => {
    const { data } = await api.put('/settings/album-type-filters', { enabled_types: types })
    return data
  },
}

// Worker Autoscale
export interface WorkerInfo {
  name: string
  active_tasks: number
}

export interface WorkerSettings {
  enabled: boolean
  max_workers: number
  current_workers: number
  total_active_tasks: number
  workers: WorkerInfo[]
  at_capacity_since: number | null
  idle_since: number | null
}

export const workersApi = {
  getSettings: async (): Promise<WorkerSettings> => {
    const { data } = await api.get('/settings/workers')
    return data
  },

  updateSettings: async (settings: { enabled?: boolean; max_workers?: number }): Promise<WorkerSettings> => {
    const { data } = await api.put('/settings/workers', settings)
    return data
  },

  scale: async (target: number): Promise<WorkerSettings> => {
    const { data } = await api.post('/settings/workers/scale', { target })
    return data
  },
}

// ==================== AUTH ====================

export const authApi = {
  login: async (username: string, password: string): Promise<LoginResponse> => {
    const { data } = await api.post('/auth/login', { username, password })
    return data
  },

  changePassword: async (currentPassword: string, newPassword: string, tempToken?: string): Promise<AuthUser> => {
    const headers: Record<string, string> = {}
    if (tempToken) {
      headers.Authorization = `Bearer ${tempToken}`
    }
    const { data } = await api.post('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    }, { headers })
    return data.user
  },

  getMe: async (): Promise<AuthUser> => {
    const { data } = await api.get('/auth/me')
    return data
  },

  listUsers: async (): Promise<AuthUser[]> => {
    const { data } = await api.get('/auth/users')
    return data.users
  },

  createUser: async (user: { username: string; password: string; display_name?: string; role: string }): Promise<AuthUser> => {
    const { data } = await api.post('/auth/users', user)
    return data.user
  },

  updateUser: async (userId: string, updates: { display_name?: string; role?: string; is_active?: boolean; password?: string }): Promise<AuthUser> => {
    const { data } = await api.patch(`/auth/users/${userId}`, updates)
    return data.user
  },

  deleteUser: async (userId: string): Promise<void> => {
    await api.delete(`/auth/users/${userId}`)
  },

  getPreferences: async (): Promise<Record<string, any>> => {
    const { data } = await api.get('/auth/me/preferences')
    return data
  },

  updatePreferences: async (prefs: Record<string, any>): Promise<Record<string, any>> => {
    const { data } = await api.put('/auth/me/preferences', prefs)
    return data
  },
}

export const djRequestsApi = {
  list: async (params?: { status_filter?: string; request_type?: string; my_requests?: boolean; user_id?: string; limit?: number; offset?: number }) => {
    const { data } = await api.get('/dj-requests', { params })
    return data as { total_count: number; requests: DjRequest[] }
  },

  listByUser: async (): Promise<{ users: DjRequestUserSummary[] }> => {
    const { data } = await api.get('/dj-requests/by-user')
    return data
  },

  create: async (body: {
    request_type: string
    title: string
    artist_name?: string
    notes?: string
    musicbrainz_id?: string
    musicbrainz_name?: string
    track_name?: string
  }): Promise<DjRequest> => {
    const { data } = await api.post('/dj-requests', body)
    return data
  },

  updateStatus: async (id: string, body: { status: string; response_note?: string }): Promise<DjRequest> => {
    const { data } = await api.patch(`/dj-requests/${id}`, body)
    return data
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/dj-requests/${id}`)
  },
}

// Scheduler API
export interface SchedulableTask {
  key: string
  name: string
  description: string
  category: string
  params: Array<{ key: string; type: string; default: any; label: string }>
}

export interface ScheduledJob {
  id: string
  name: string
  task_key: string
  task_name: string
  frequency: string
  enabled: boolean
  run_at_hour: number
  day_of_week: number | null
  day_of_month: number | null
  task_params: Record<string, any> | null
  last_run_at: string | null
  next_run_at: string | null
  last_job_id: string | null
  last_status: string | null
  created_at: string | null
}

export const schedulerApi = {
  getTasks: async (): Promise<SchedulableTask[]> => {
    const { data } = await api.get('/scheduler/tasks')
    return data
  },
  getJobs: async (): Promise<ScheduledJob[]> => {
    const { data } = await api.get('/scheduler/jobs')
    return data
  },
  createJob: async (body: {
    name: string
    task_key: string
    frequency: string
    enabled?: boolean
    run_at_hour?: number
    day_of_week?: number | null
    day_of_month?: number | null
    task_params?: Record<string, any> | null
  }): Promise<ScheduledJob> => {
    const { data } = await api.post('/scheduler/jobs', body)
    return data
  },
  updateJob: async (id: string, body: Partial<{
    name: string
    frequency: string
    enabled: boolean
    run_at_hour: number
    day_of_week: number | null
    day_of_month: number | null
    task_params: Record<string, any> | null
  }>): Promise<ScheduledJob> => {
    const { data } = await api.put(`/scheduler/jobs/${id}`, body)
    return data
  },
  deleteJob: async (id: string): Promise<void> => {
    await api.delete(`/scheduler/jobs/${id}`)
  },
  runNow: async (id: string): Promise<{ message: string; task_id: string }> => {
    const { data } = await api.post(`/scheduler/jobs/${id}/run-now`)
    return data
  },
}

// ==================== NOW PLAYING ====================

export interface NowPlayingListener {
  user_id: string
  display_name: string
  role: string
  track_title: string
  artist_name: string
  artist_id?: string | null
  album_id?: string | null
  album_title?: string | null
  cover_art_url?: string | null
  listening_since: string
}

export const nowPlayingApi = {
  heartbeat: async (data: {
    track_id: string
    track_title: string
    artist_name: string
    artist_id?: string | null
    album_id?: string | null
    album_title?: string | null
    cover_art_url?: string | null
    book_id?: string | null
    chapter_id?: string | null
    position_ms?: number | null
  }): Promise<void> => {
    await api.post('/now-playing/heartbeat', data)
  },

  clearHeartbeat: async (): Promise<void> => {
    await api.delete('/now-playing/heartbeat')
  },

  getListeners: async (): Promise<{ listeners: NowPlayingListener[] }> => {
    const { data } = await api.get('/now-playing')
    return data
  },
}

// ==================== Audiobook APIs ====================

export const authorsApi = {
  // Search MusicBrainz for authors (same search as artists)
  search: async (query: string, limit = 25): Promise<{ results: MusicBrainzArtist[] }> => {
    const { data } = await api.post('/authors/search', null, {
      params: { query, limit },
    })
    return data
  },

  // Add author by MusicBrainz ID
  add: async (params: {
    musicbrainz_id: string
    is_monitored?: boolean
    root_folder_path?: string
    quality_profile_id?: string
    monitor_type?: string
    search_for_missing?: boolean
  }): Promise<Author> => {
    const { data } = await api.post('/authors', {
      musicbrainz_id: params.musicbrainz_id,
      is_monitored: params.is_monitored ?? false,
      root_folder_path: params.root_folder_path,
      quality_profile_id: params.quality_profile_id,
      monitor_type: params.monitor_type ?? 'none',
      search_for_missing: params.search_for_missing ?? false,
    })
    return data
  },

  // List authors
  list: async (params?: {
    monitored_only?: boolean
    search_query?: string
    genre?: string
    sort_by?: string
    limit?: number
    offset?: number
  }): Promise<{ total_count: number; authors: Author[] }> => {
    const { data } = await api.get('/authors', { params })
    return data
  },

  // Get author details (includes books and series)
  get: async (authorId: string): Promise<Author & { books: Book[]; series: Series[] }> => {
    const { data } = await api.get(`/authors/${authorId}`)
    return data
  },

  // Update author
  update: async (
    authorId: string,
    updates: Partial<Pick<Author, 'is_monitored' | 'quality_profile_id' | 'root_folder_path'>>
  ): Promise<Author> => {
    const { data } = await api.patch(`/authors/${authorId}`, null, { params: updates })
    return data
  },

  // Sync author books from MusicBrainz
  sync: async (authorId: string): Promise<{ success: boolean }> => {
    const { data } = await api.post(`/authors/${authorId}/sync`)
    return data
  },

  // Delete author
  delete: async (authorId: string, deleteFiles = false): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/authors/${authorId}`, {
      params: { delete_files: deleteFiles },
    })
    return data
  },

  // List genres
  genres: async (): Promise<{ genres: string[] }> => {
    const { data } = await api.get('/authors/genres')
    return data
  },

  // Refresh metadata for all authors in the library
  refreshAllMetadata: async (force = false): Promise<{ success: boolean; message: string; total_authors: number; task_id?: string }> => {
    const { data } = await api.post(`/authors/refresh-all-metadata?force=${force}`)
    return data
  },

  // Bulk update
  bulkUpdate: async (authorIds: string[], updates: { is_monitored?: boolean; quality_profile_id?: string }): Promise<{ updated_count: number }> => {
    const { data } = await api.patch('/authors/bulk-update', {
      author_ids: authorIds,
      ...updates,
    })
    return data
  },

  uploadCoverArt: async (authorId: string, file: File): Promise<{ success: boolean; image_url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await api.post(`/authors/${authorId}/cover-art`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  uploadCoverArtFromUrl: async (authorId: string, url: string): Promise<{ success: boolean; image_url: string }> => {
    const { data } = await api.post(`/authors/${authorId}/cover-art-from-url`, { url })
    return data
  },
}

export const seriesApi = {
  // List series
  list: async (params?: {
    author_id?: string
    monitored_only?: boolean
    search_query?: string
    sort_by?: string
    limit?: number
    offset?: number
  }): Promise<{ total_count: number; series: Series[] }> => {
    const { data } = await api.get('/series', { params })
    return data
  },

  // Get series detail
  get: async (seriesId: string): Promise<Series & { books: Book[]; author: Author }> => {
    const { data } = await api.get(`/series/${seriesId}`)
    return data
  },

  // Create series
  create: async (params: {
    author_id: string
    name: string
    description?: string
    musicbrainz_series_id?: string
    monitored?: boolean
  }): Promise<Series> => {
    const { data } = await api.post('/series', params)
    return data
  },

  // Update series
  update: async (seriesId: string, updates: {
    name?: string
    description?: string
    monitored?: boolean
    cover_art_url?: string
  }): Promise<Series> => {
    const { data } = await api.patch(`/series/${seriesId}`, updates)
    return data
  },

  // Delete series
  delete: async (seriesId: string): Promise<{ success: boolean }> => {
    const { data } = await api.delete(`/series/${seriesId}`)
    return data
  },

  // Bulk delete series
  bulkDelete: async (seriesIds: string[]): Promise<{ success: boolean; deleted_count: number }> => {
    const { data } = await api.delete('/series/bulk-delete', {
      data: { series_ids: seriesIds },
    })
    return data
  },

  // Add book to series
  addBook: async (seriesId: string, bookId: string, position?: number): Promise<{ success: boolean }> => {
    const { data } = await api.post(`/series/${seriesId}/add-book`, {
      book_id: bookId,
      position,
    })
    return data
  },

  // Reorder books in series
  reorder: async (seriesId: string, bookIds: string[]): Promise<{ success: boolean }> => {
    const { data } = await api.post(`/series/${seriesId}/reorder`, {
      book_ids: bookIds,
    })
    return data
  },

  // Remove book from series
  removeBook: async (seriesId: string, bookId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post(`/series/${seriesId}/remove-book`, {
      book_id: bookId,
    })
    return data
  },

  uploadCoverArt: async (seriesId: string, file: File): Promise<{ success: boolean; cover_art_url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await api.post(`/series/${seriesId}/cover-art`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  uploadCoverArtFromUrl: async (seriesId: string, url: string): Promise<{ success: boolean; cover_art_url: string }> => {
    const { data } = await api.post(`/series/${seriesId}/cover-art-from-url`, { url })
    return data
  },
}

export const booksApi = {
  // List books
  list: async (params?: {
    search_query?: string
    status_filter?: string
    author_id?: string
    series_id?: string
    monitored_only?: boolean
    in_library?: boolean
    sort_by?: string
    limit?: number
    offset?: number
  }): Promise<{ total_count: number; books: Book[] }> => {
    const { data } = await api.get('/books', { params })
    return data
  },

  // Get wanted books
  wanted: async (limit = 100, offset = 0): Promise<{ total_count: number; wanted_books: Book[] }> => {
    const { data } = await api.get('/books/wanted', { params: { limit, offset } })
    return data
  },

  // Get book detail
  get: async (bookId: string): Promise<Book & { chapters: Chapter[]; downloads: any[] }> => {
    const { data } = await api.get(`/books/${bookId}`)
    return data
  },

  // Update book
  update: async (bookId: string, updates: {
    monitored?: boolean
    status?: string
    custom_folder_path?: string | null
    series_id?: string | null
    series_position?: number | null
    related_series?: string | null
  }): Promise<Book> => {
    const { data } = await api.patch(`/books/${bookId}`, updates)
    return data
  },

  // Search for book download
  search: async (bookId: string): Promise<{ success: boolean; download_task_id?: string }> => {
    const { data } = await api.post(`/books/${bookId}/search`)
    return data
  },

  // Bulk update
  bulkUpdate: async (bookIds: string[], monitored: boolean): Promise<{ updated_count: number }> => {
    const { data } = await api.patch('/books/bulk-update', {
      book_ids: bookIds,
      monitored,
    })
    return data
  },

  // Monitor all books by author
  monitorByAuthor: async (authorId: string, monitored: boolean): Promise<{ updated_count: number }> => {
    const { data } = await api.post('/books/monitor-by-author', {
      author_id: authorId,
      monitored,
    })
    return data
  },

  // Record a chapter play (called when chapter finishes playing)
  recordChapterPlay: async (chapterId: string): Promise<{ play_count: number }> => {
    const { data } = await api.post(`/chapters/${chapterId}/record-play`)
    return data
  },

  uploadCoverArt: async (bookId: string, file: File): Promise<{ success: boolean; cover_art_url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await api.post(`/books/${bookId}/cover-art`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  uploadCoverArtFromUrl: async (bookId: string, url: string): Promise<{ success: boolean; cover_art_url: string }> => {
    const { data } = await api.post(`/books/${bookId}/cover-art-from-url`, { url })
    return data
  },

  editMetadata: async (bookId: string, payload: { title?: string; author_name?: string }): Promise<{
    success: boolean
    book_id: string
    title: string
    credit_name: string | null
    chapters_to_update: number
    task_id: string
  }> => {
    const { data } = await api.post(`/books/${bookId}/edit-metadata`, payload)
    return data
  },
}

export const bookProgressApi = {
  get: async (bookId: string): Promise<import('../types').BookProgress | null> => {
    const { data } = await api.get(`/books/${bookId}/progress`)
    return data
  },

  upsert: async (bookId: string, payload: {
    chapter_id: string
    position_ms: number
    completed?: boolean
  }): Promise<import('../types').BookProgress> => {
    const { data } = await api.post(`/books/${bookId}/progress`, payload)
    return data
  },

  reset: async (bookId: string): Promise<void> => {
    await api.delete(`/books/${bookId}/progress`)
  },

  batchGet: async (bookIds: string[]): Promise<{ progress: Record<string, import('../types').BookProgress> }> => {
    const { data } = await api.post('/books/progress/batch', { book_ids: bookIds })
    return data
  },
}

// ==================== STORAGE MOUNTS ====================

export const storageMountsApi = {
  list: async (): Promise<{ mounts: StorageMount[]; has_pending_changes: boolean; pending_count: number }> => {
    const { data } = await api.get('/settings/storage-mounts')
    return data
  },

  add: async (mount: {
    name: string
    host_path: string
    container_path: string
    read_only?: boolean
    mount_type?: string
  }): Promise<StorageMount> => {
    const { data } = await api.post('/settings/storage-mounts', mount)
    return data
  },

  update: async (mountId: string, updates: {
    name?: string
    read_only?: boolean
    mount_type?: string
  }): Promise<StorageMount> => {
    const { data } = await api.put(`/settings/storage-mounts/${mountId}`, updates)
    return data
  },

  remove: async (mountId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.delete(`/settings/storage-mounts/${mountId}`)
    return data
  },

  validatePath: async (hostPath: string): Promise<{ valid: boolean; error: string | null; free_space_gb: number | null }> => {
    const { data } = await api.post('/settings/storage-mounts/validate-path', { host_path: hostPath })
    return data
  },

  apply: async (): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/settings/storage-mounts/apply')
    return data
  },

  rollback: async (): Promise<{ status: string; message: string }> => {
    const { data } = await api.post('/settings/storage-mounts/rollback')
    return data
  },
}

// ==================== LISTEN & ADD ====================

export const listenApi = {
  identify: async (audioBlob: Blob): Promise<IdentifyResult> => {
    const formData = new FormData()
    formData.append('file', audioBlob, 'recording.wav')
    const { data } = await api.post('/listen/identify', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
    return data
  },
}

// ==================== BOOK PLAYLISTS ====================

export const bookPlaylistsApi = {
  // Get playlist for a series
  get: async (seriesId: string): Promise<import('../types').BookPlaylistDetail> => {
    const { data } = await api.get(`/series/${seriesId}/playlist`)
    return data
  },

  // Create/refresh playlist for a series
  create: async (seriesId: string): Promise<{ status: string; task_id: string; message: string }> => {
    const { data } = await api.post(`/series/${seriesId}/playlist`)
    return data
  },

  // List all book playlists
  list: async (): Promise<import('../types').BookPlaylist[]> => {
    const { data } = await api.get('/book-playlists')
    return data
  },

  // Delete a series playlist
  delete: async (seriesId: string): Promise<void> => {
    await api.delete(`/series/${seriesId}/playlist`)
  },
}

export default api
