/**
 * Studio54 TypeScript Type Definitions
 */

// User Roles
export type UserRole = 'director' | 'dj' | 'partygoer'

// Auth User
export interface AuthUser {
  id: string
  username: string
  display_name: string | null
  role: UserRole
  is_active: boolean
  must_change_password: boolean
  last_login_at: string | null
  created_at: string | null
}

// Login Response
export interface LoginResponse {
  access_token: string
  token_type: string
  user: AuthUser
}

// Monitor Type Enum
export enum MonitorType {
  ALL_ALBUMS = 'all_albums',
  FUTURE_ONLY = 'future_only',
  EXISTING_ONLY = 'existing_only',
  FIRST_ALBUM = 'first_album',
  LATEST_ALBUM = 'latest_album',
  NONE = 'none',
}

// Notification Profile Interface
export interface NotificationProfile {
  id: string
  name: string
  provider: 'webhook' | 'discord' | 'slack'
  is_enabled: boolean
  events: string[]
  created_at: string | null
  updated_at: string | null
}

// Notification Events
export const NOTIFICATION_EVENTS = [
  { value: 'album_downloaded', label: 'Album Downloaded' },
  { value: 'album_imported', label: 'Album Imported' },
  { value: 'album_failed', label: 'Album Download Failed' },
  { value: 'job_failed', label: 'Job Failed' },
  { value: 'job_completed', label: 'Job Completed' },
  { value: 'artist_added', label: 'Artist Added' },
] as const

// Root Folder Interface
export interface RootFolder {
  id: string
  path: string
  name: string
  is_root_folder: boolean
  library_type?: LibraryType
  free_space_bytes: number | null
  free_space_gb: number | null
  artist_count: number
}

// Quality Profile Interface
export interface QualityProfile {
  id: string
  name: string
  is_default: boolean
  allowed_formats: string[]
  preferred_formats: string[]
  min_bitrate: number | null
  max_size_mb: number | null
  upgrade_enabled: boolean
  upgrade_until_quality: string | null
  created_at: string | null
  updated_at: string | null
}

// Library Type
export type LibraryType = 'music' | 'audiobook'

// Book Status Enum
export enum BookStatus {
  WANTED = 'wanted',
  SEARCHING = 'searching',
  DOWNLOADING = 'downloading',
  DOWNLOADED = 'downloaded',
  FAILED = 'failed',
}

// Album Status Enum
export enum AlbumStatus {
  WANTED = 'wanted',
  SEARCHING = 'searching',
  DOWNLOADING = 'downloading',
  DOWNLOADED = 'downloaded',
  FAILED = 'failed',
}

// Download Status Enum
export enum DownloadStatus {
  QUEUED = 'queued',
  DOWNLOADING = 'downloading',
  POST_PROCESSING = 'post_processing',
  IMPORTING = 'importing',
  COMPLETED = 'completed',
  FAILED = 'failed',
}

// Artist Interface
export interface Artist {
  id: string
  name: string
  musicbrainz_id: string | null
  is_monitored: boolean
  quality_profile_id: string | null
  root_folder_path: string | null
  overview: string | null
  genre: string | null
  country: string | null
  image_url: string | null
  album_count: number
  monitored_album_count?: number
  single_count: number
  track_count: number
  linked_files_count: number
  total_track_files: number
  monitor_type?: string
  rating_override: number | null
  average_rating: number | null
  rated_track_count: number
  added_at: string
  last_sync_at: string | null
  import_source?: string | null
  muse_library_id?: string | null
  studio54_library_path_id?: string | null
}

// Album Interface
export interface Album {
  id: string
  title: string
  artist_id: string
  artist_name?: string
  musicbrainz_id: string | null
  release_mbid: string | null
  release_date: string | null
  album_type: string | null
  secondary_types: string | null
  status: AlbumStatus
  monitored: boolean
  cover_art_url: string | null
  custom_folder_path: string | null
  track_count: number
  linked_files_count?: number
  muse_library_id: string | null
  muse_verified: boolean
  added_at?: string
  updated_at?: string
}

// Track Interface
export interface Track {
  id: string
  album_id: string
  title: string
  musicbrainz_id: string | null
  track_number: number
  duration_ms: number | null
  has_file: boolean
  muse_file_id: string | null
  rating: number | null
  average_rating: number | null
  user_rating: number | null
  rating_count?: number
}

// Author Interface (audiobook equivalent of Artist)
export interface Author {
  id: string
  name: string
  musicbrainz_id: string | null
  is_monitored: boolean
  quality_profile_id: string | null
  root_folder_path: string | null
  overview: string | null
  genre: string | null
  country: string | null
  image_url: string | null
  book_count: number
  series_count: number
  chapter_count: number
  linked_files_count?: number
  monitor_type?: string
  import_source?: string | null
  studio54_library_path_id?: string | null
  added_at: string
  last_sync_at: string | null
}

// Series Interface
export interface Series {
  id: string
  name: string
  author_id: string
  author_name?: string
  musicbrainz_series_id: string | null
  description: string | null
  total_expected_books: number | null
  book_count?: number
  monitored: boolean
  cover_art_url: string | null
  added_at?: string
  updated_at?: string
}

// Book Interface (audiobook equivalent of Album)
export interface Book {
  id: string
  title: string
  author_id: string
  author_name?: string
  musicbrainz_id: string | null
  release_mbid: string | null
  release_date: string | null
  album_type: string | null
  secondary_types: string | null
  status: BookStatus
  monitored: boolean
  cover_art_url: string | null
  custom_folder_path: string | null
  chapter_count: number
  linked_files_count?: number
  series_id: string | null
  series_name?: string | null
  series_position: number | null
  related_series: string | null
  added_at?: string
  updated_at?: string
}

// Chapter Interface (audiobook equivalent of Track)
export interface Chapter {
  id: string
  book_id: string
  title: string
  musicbrainz_id: string | null
  chapter_number: number
  disc_number: number
  duration_ms: number | null
  has_file: boolean
  file_path: string | null
}

export interface BookProgress {
  book_id: string
  chapter_id: string
  chapter_title: string | null
  chapter_number: number | null
  position_ms: number
  completed: boolean
  updated_at: string | null
}

// Indexer Interface
export interface Indexer {
  id: string
  name: string
  base_url: string
  indexer_type: string
  priority: number
  is_enabled: boolean
  categories: number[]
  rate_limit_per_second: number
}

// Download Queue Entry
export interface DownloadQueueEntry {
  id: string
  album_id: string
  indexer_id: string
  download_client_id: string
  nzb_title: string
  nzb_guid: string
  nzb_url: string
  sabnzbd_id: string | null
  status: DownloadStatus
  progress_percent: number
  size_bytes: number
  download_path: string | null
  error_message: string | null
  queued_at: string
  started_at: string | null
  completed_at: string | null
}

// Download Client Interface
export interface DownloadClient {
  id: string
  name: string
  client_type: string
  host: string
  port: number
  use_ssl: boolean
  category: string
  is_enabled: boolean
  is_default: boolean
}

// API Response Wrappers
export interface PaginatedResponse<T> {
  total_count: number
  limit: number
  offset: number
  items: T[]
}

export interface ApiResponse<T = unknown> {
  success: boolean
  data?: T
  error?: string
  message?: string
}

// MusicBrainz Search Result
export interface MusicBrainzArtist {
  id: string
  name: string
  sort_name: string
  type: string
  country: string | null
  life_span: {
    begin: string | null
    end: string | null
  } | null
  tags: string[]
}

// System Stats
export interface DiskInfo {
  used_bytes: number
  total_bytes: number
  free_bytes: number
  percent: number
}

export interface SystemStats {
  monitored_artists: number
  total_artists: number
  monitored_albums: number
  total_albums: number
  wanted_albums: number
  downloaded_albums: number
  linked_albums: number
  linked_tracks: number
  total_tracks: number
  active_downloads: number
  completed_downloads: number
  failed_downloads: number
  total_download_size_bytes: number
  total_download_size: string
  disk?: {
    root?: DiskInfo
    docker?: DiskInfo
  }
  // Audiobook stats
  total_authors?: number
  monitored_authors?: number
  total_books?: number
  wanted_books?: number
  downloaded_books?: number
  total_chapters?: number
  linked_chapters?: number
}

// MUSE Library
export interface MuseLibrary {
  id: string
  name: string
  path: string
  total_files: number
  total_size_bytes: number
  last_scan_at: string | null
}

// Playlist Interfaces
export interface Playlist {
  id: string
  name: string
  description: string | null
  user_id: string | null
  owner_name: string | null
  is_published: boolean
  cover_art_url: string | null
  track_count: number
  created_at: string
  updated_at: string
}

export interface PlaylistTrack {
  id: string
  title: string
  track_number: number
  duration_ms: number | null
  has_file: boolean
  muse_file_id: string | null
  album_id: string
  album_title: string
  artist_name: string
  cover_art_url: string | null
  position: number
  added_at: string
}

export interface PlaylistDetail extends Playlist {
  tracks: PlaylistTrack[]
}

// Library Scanner Interfaces
export interface LibraryPath {
  id: string
  path: string
  name: string
  is_enabled: boolean
  library_type?: LibraryType
  total_files: number
  total_size_bytes: number
  last_scan_at: string | null
  created_at: string
}

export interface LibraryFile {
  id: string
  file_path: string
  title: string | null
  artist: string | null
  album: string | null
  track_number: number | null
  year: number | null
  format: string | null
  duration_seconds: number | null
  musicbrainz_trackid: string | null
  musicbrainz_albumid: string | null
  musicbrainz_artistid: string | null
  album_art_url: string | null
  artist_image_url: string | null
}

export interface ScanJob {
  id: string
  library_path_id: string
  status: string
  files_scanned: number
  files_added: number
  files_updated: number
  files_skipped: number
  files_failed: number
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  duration_seconds?: number
}

export interface UnlinkedFile {
  id: string
  library_file_id: string
  file_path: string
  filesystem_path: string | null
  artist: string | null
  album: string | null
  title: string | null
  musicbrainz_trackid: string | null
  reason: string
  reason_detail: string | null
  detected_at: string | null
  resolved_at: string | null
  format: string | null
  bitrate_kbps: number | null
  sample_rate_hz: number | null
  duration_seconds: number | null
}

export interface UnlinkedFilesSummary {
  total: number
  by_reason: Record<string, number>
  last_scan: string | null
}

export interface UnlinkedFilesListResponse {
  items: UnlinkedFile[]
  total: number
  page: number
  per_page: number
  reason_summary: Record<string, number>
}

export interface UnorganizedFile {
  id: string
  file_path: string
  file_name: string
  artist: string | null
  album_artist: string | null
  album: string | null
  title: string | null
  track_number: number | null
  disc_number: number | null
  year: number | null
  genre: string | null
  format: string | null
  bitrate_kbps: number | null
  duration_seconds: number | null
  file_size_bytes: number | null
  musicbrainz_trackid: string | null
  musicbrainz_artistid: string | null
  musicbrainz_albumid: string | null
  indexed_at: string | null
}

export interface LibraryStats {
  total_files: number
  total_size_bytes: number
  total_size_gb: number
  total_library_paths: number
  formats: Array<{ format: string; count: number }>
  musicbrainz_coverage: {
    tracks_with_mb_id: number
    albums_with_mb_id: number
    artists_with_mb_id: number
    track_coverage_percent: number
  }
}

// DJ Requests
export type DjRequestType = 'artist' | 'album' | 'track' | 'problem'
export type DjRequestStatus = 'pending' | 'approved' | 'rejected' | 'fulfilled'

export interface DjRequest {
  id: string
  user_id: string
  requester_name: string
  request_type: DjRequestType
  title: string
  artist_name: string | null
  notes: string | null
  musicbrainz_id: string | null
  musicbrainz_name: string | null
  track_name: string | null
  status: DjRequestStatus
  response_note: string | null
  fulfilled_by_name: string | null
  created_at: string
  updated_at: string
}

// Dashboard Layout Types
export interface DashboardLayoutItem {
  i: string
  x: number
  y: number
  w: number
  h: number
  minW?: number
  minH?: number
}

export interface DashboardPreferences {
  version: number
  layouts: { lg: DashboardLayoutItem[]; md?: DashboardLayoutItem[]; sm?: DashboardLayoutItem[] }
  hiddenWidgets: string[]
}

export interface UserPreferences {
  dashboard?: DashboardPreferences
}

export type WidgetCategory = 'stats' | 'system' | 'charts' | 'lists' | 'section'

export interface WidgetDefinition {
  id: string
  label: string
  category: WidgetCategory
  defaultSize: { w: number; h: number }
  minSize: { w: number; h: number }
  requiredRole?: 'director'
  libraryType?: 'music' | 'audiobook'
  component: React.ComponentType<WidgetComponentProps>
}

export interface WidgetComponentProps {
  widgetId: string
  isEditMode: boolean
  libraryType?: 'music' | 'audiobook'
}

// Storage Mount Types
export type StorageMountType = 'music' | 'audiobook' | 'generic'
export type StorageMountStatus = 'applied' | 'pending' | 'failed'

export interface StorageMount {
  id: string
  name: string
  host_path: string
  container_path: string
  read_only: boolean
  mount_type: StorageMountType
  is_system: boolean
  is_active: boolean
  status: StorageMountStatus
  last_applied_at: string | null
  error_message: string | null
  created_at: string | null
  updated_at: string | null
}

// Listen & Add (Audio Recognition)
export interface IdentifyArtistResult {
  name: string
  mbid: string | null
  exists_in_library: boolean
  library_id: string | null
}

export interface IdentifyAlbumResult {
  name: string | null
  mbid: string | null
  exists_in_library: boolean
  library_id: string | null
}

export interface IdentifyResult {
  identified: boolean
  title?: string
  recording_mbid?: string
  artist?: IdentifyArtistResult
  album?: IdentifyAlbumResult
  confidence?: number
  message?: string
}

// Book Playlist Interfaces (series-ordered chapter playlists)
export interface BookPlaylist {
  id: string
  series_id: string
  name: string
  description: string | null
  chapter_count: number
  total_duration_ms: number
  series_name?: string | null
  created_at: string | null
  updated_at: string | null
}

export interface BookPlaylistChapter {
  id: string
  chapter_id: string
  chapter_title: string
  chapter_number: number | null
  duration_ms: number | null
  has_file: boolean
  file_path: string | null
  position: number
  book_position: number
  book_id: string | null
  book_title: string | null
  book_cover_art_url: string | null
}

export interface BookPlaylistDetail extends BookPlaylist {
  chapters: BookPlaylistChapter[]
}

export interface DjRequestUserSummary {
  user_id: string
  username: string
  display_name: string
  total_count: number
  pending_count: number
}
