import { useState } from 'react'
import { FiChevronDown, FiChevronRight, FiExternalLink } from 'react-icons/fi'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

type MinRole = 'partygoer' | 'dj' | 'director'

interface FeatureItem {
  name: string
  description: string
  minRole?: MinRole
}

interface PageSection {
  title: string
  path: string
  icon: string
  minRole?: MinRole
  features: FeatureItem[]
}

const sections: PageSection[] = [
  {
    title: 'Dashboard',
    path: '/dashboard',
    icon: 'Home',
    features: [
      { name: 'System Stats', description: 'View total artists, monitored albums, wanted albums, and downloaded albums at a glance.' },
      { name: 'Active Downloads', description: 'Monitor current download activity with status counts (downloading, completed, failed).' },
      { name: 'Recent Wanted', description: 'See the last 10 wanted albums with status badges and quick navigation.' },
      { name: 'Log Level Controls', description: 'Change application log level (DEBUG/INFO/WARNING/ERROR) for troubleshooting.', minRole: 'director' },
    ],
  },
  {
    title: 'Library',
    path: '/artists',
    icon: 'Users',
    features: [
      { name: 'Browse Tab', description: 'Browse your library by Artists, Albums, or Tracks with sorting, filtering, and search.' },
      { name: 'Genre Filter', description: 'Filter artists by genre when browsing in artist mode.' },
      { name: 'Monitoring Filter', description: 'Filter by All, Monitored, or Unmonitored items.' },
      { name: 'Track Status Filter', description: 'Filter tracks by All, Has File, or Missing status.' },
      { name: 'Bulk Mode', description: 'Select multiple artists to monitor/unmonitor or delete in bulk.', minRole: 'dj' },
      { name: 'Scanner Tab', description: 'Scan library paths to discover and index music files.', minRole: 'director' },
      { name: 'Import Tab', description: 'Import artists from MUSE library or search MusicBrainz to add new artists.', minRole: 'director' },
      { name: 'Unlinked Files Tab', description: 'View and manage files that could not be linked to album tracks.', minRole: 'director' },
      { name: 'Unorganized Files Tab', description: 'View files that have not been organized into the standard folder structure.', minRole: 'director' },
      { name: 'Add Artist', description: 'Search MusicBrainz and add an artist with root folder, quality profile, and monitoring options.', minRole: 'dj' },
      { name: 'Get Metadata', description: 'Refresh metadata (images, bios) for all artists from MusicBrainz.', minRole: 'director' },
      { name: 'Sync All Albums', description: 'Sync album lists from MusicBrainz for all artists.', minRole: 'director' },
      { name: 'Cleanup Orphaned', description: 'Find and remove artists with no albums or tracks.', minRole: 'director' },
    ],
  },
  {
    title: 'Artist Detail',
    path: '/disco-lounge/artists/:id',
    icon: 'User',
    features: [
      { name: 'Top Hits - Popular', description: 'Shows top tracks from Last.fm with listener counts and 30-sec iTunes preview.' },
      { name: 'Top Hits - Most Played', description: 'Shows your most played tracks (or newest if <5 plays), with play, queue, and playlist buttons.' },
      { name: 'Monitor All & Download', description: 'One-click to monitor all albums and trigger Usenet search for missing ones.', minRole: 'dj' },
      { name: 'Organize Files', description: 'Move and rename files into standardized folder structure based on metadata and MBIDs.', minRole: 'dj' },
      { name: 'Sync Albums', description: 'Refresh album list from MusicBrainz to discover new releases.', minRole: 'dj' },
      { name: 'Search Missing', description: 'Search Usenet indexers for all wanted/missing albums by this artist.', minRole: 'dj' },
      { name: 'Refresh Metadata', description: 'Update artist images, biography, and other metadata from MusicBrainz.', minRole: 'dj' },
      { name: 'Search MBDB', description: 'Search the local MusicBrainz database for this artist\'s MBID.', minRole: 'dj' },
      { name: 'Remove Artist', description: 'Delete artist and all associated data, with optional file deletion.', minRole: 'dj' },
      { name: 'Artist Monitoring', description: 'Toggle monitoring for this artist to enable/disable automatic downloads.', minRole: 'dj' },
      { name: 'Album Monitoring', description: 'Toggle monitoring per album directly from the artist page.', minRole: 'dj' },
      { name: '30-sec Preview', description: 'Listen to a 30-second iTunes preview for any track in the Popular column.' },
      { name: 'Download Track', description: 'Search Usenet for individual tracks that are in your library but missing files.', minRole: 'dj' },
    ],
  },
  {
    title: 'Album Detail',
    path: '/disco-lounge/albums/:id',
    icon: 'Disc',
    features: [
      { name: 'Play All', description: 'Play all available tracks in the album sequentially.' },
      { name: 'Fetch Lyrics', description: 'Prefetch synced and plain lyrics from LRCLIB for all tracks.', minRole: 'dj' },
      { name: 'Organize Files', description: 'Reorganize album files with dry-run preview, metadata file creation, and MBID options.', minRole: 'dj' },
      { name: 'Monitor/Unmonitor', description: 'Toggle album monitoring for automatic download searches.', minRole: 'dj' },
      { name: 'Manual Search', description: 'Trigger a Usenet search for this album (checks MUSE library first).', minRole: 'dj' },
      { name: 'Custom Folder Path', description: 'Set a custom folder path and browse the filesystem to locate album files.' },
      { name: 'Scan & Match', description: 'Scan album folder for audio files and auto-match them to tracks by metadata.' },
      { name: 'Track Actions - Play', description: 'Play an individual track from your library.' },
      { name: 'Track Actions - Queue', description: 'Add a linked track to the play queue.' },
      { name: 'Track Actions - Preview', description: 'Listen to a 30-second iTunes preview for missing tracks.' },
      { name: 'Track Actions - Search', description: 'Search Usenet for an individual missing track.', minRole: 'dj' },
      { name: 'Track Actions - Unlink', description: 'Remove the file association from a track (keeps the file on disk).', minRole: 'dj' },
      { name: 'Track Actions - Delete File', description: 'Permanently delete the track\'s audio file from disk and clean up empty folders.', minRole: 'dj' },
      { name: 'Track Actions - Download', description: 'Download a linked track\'s audio file to your computer.', minRole: 'dj' },
      { name: 'Track Actions - Playlist', description: 'Add a linked track to any playlist.' },
      { name: 'Download History', description: 'View all download attempts with NZB titles, sizes, timestamps, and error messages.' },
      { name: 'Clear Downloads', description: 'Clear failed or all download history and reset album status.', minRole: 'dj' },
    ],
  },
  {
    title: 'Albums',
    path: '/albums',
    icon: 'Disc',
    features: [
      { name: 'Status Filter', description: 'Filter albums by status: All, Wanted, Searching, Downloading, Downloaded, Failed.' },
      { name: 'Monitoring Filter', description: 'Filter by All, Monitored, or Unmonitored albums.' },
      { name: 'Sort Options', description: 'Sort by title, file count, release date, or date added.' },
      { name: 'Album Table', description: 'Paginated table with title, artist, year, track count, status, and type.' },
      { name: 'Manual Search', description: 'Click the search icon to trigger a Usenet search for any album.', minRole: 'dj' },
    ],
  },
  {
    title: 'File Management',
    path: '/file-management',
    icon: 'FolderPlus',
    minRole: 'director',
    features: [
      { name: 'Library Jobs Tab', description: 'Run organization and MBID jobs against an entire library path.' },
      { name: 'Organize Library', description: 'Move and rename all files in a library path into the standard folder structure.' },
      { name: 'Validate Structure', description: 'Check that files are in the correct locations without moving anything.' },
      { name: 'Fetch Metadata', description: 'Search MusicBrainz for files without MBIDs and write them to file comment tags.' },
      { name: 'Validate MBIDs', description: 'Verify that MBIDs written to file comments are correct.' },
      { name: 'Link Files', description: 'Match files with MBIDs to album tracks in the database.' },
      { name: 'Reindex Albums', description: 'Detect albums and singles from file metadata and create/update database records.' },
      { name: 'Verify Audio', description: 'Verify recently downloaded audio files are valid and playable.' },
      { name: 'Artist Organization Tab', description: 'Organize files for a specific artist into the standardized folder structure.' },
      { name: 'Jobs & Audit Tab', description: 'Monitor running jobs with progress, view audit log of all file operations.' },
      { name: 'Rollback', description: 'Reverse completed file organization jobs to restore files to original locations.' },
      { name: 'Maintenance Tab', description: 'Clean up old log files with configurable retention period and preview before deletion.' },
    ],
  },
  {
    title: 'DJ Requests',
    path: '/dj-requests',
    icon: 'Mic',
    features: [
      { name: 'New Request', description: 'Submit a request for an artist, album, or track to be added to the library.' },
      { name: 'Browse Requests', description: 'View all DJ requests from all users with status, type, and date filters.' },
      { name: 'My Requests Filter', description: 'Toggle to show only your own requests.' },
      { name: 'Approve/Reject', description: 'Approve or reject pending requests with optional response notes.', minRole: 'director' },
      { name: 'Fulfill Request', description: 'Mark an approved request as fulfilled once the content is available.', minRole: 'director' },
      { name: 'Add to Library', description: 'Add an approved artist request directly to the library with auto-search.', minRole: 'director' },
      { name: 'View by User', description: 'View requests grouped by user to see submission patterns.', minRole: 'director' },
    ],
  },
  {
    title: 'Playlists',
    path: '/playlists',
    icon: 'List',
    features: [
      { name: 'Create Playlist', description: 'Create a new playlist with a name and optional description.' },
      { name: 'Edit Playlist', description: 'Rename or update the description of an existing playlist.' },
      { name: 'Delete Playlist', description: 'Remove a playlist (does not affect the actual music files).' },
      { name: 'Play All', description: 'Play all tracks in a playlist sequentially.' },
      { name: 'Add Tracks', description: 'Add tracks to playlists from album detail or library views.' },
      { name: 'Remove Tracks', description: 'Remove individual tracks from a playlist.' },
      { name: 'Track Playback', description: 'Play individual tracks directly from the playlist view.' },
    ],
  },
  {
    title: 'Calendar',
    path: '/calendar',
    icon: 'Calendar',
    features: [
      { name: 'Upcoming Releases', description: 'View upcoming album releases for all monitored artists.' },
      { name: 'Release Info', description: 'Each release shows album title, artist name, release date, and album type.' },
      { name: 'Navigation', description: 'Click on any release to navigate to the album detail page.' },
    ],
  },
  {
    title: 'Statistics',
    path: '/statistics',
    icon: 'BarChart',
    features: [
      { name: 'Summary Cards', description: 'Total artists, albums, tracks, and library size at a glance.' },
      { name: 'Album Status Chart', description: 'Visual breakdown of albums by status (wanted, downloading, downloaded, etc.).' },
      { name: 'File Formats Chart', description: 'Distribution of audio formats in your library (FLAC, MP3, AAC, etc.).' },
      { name: 'Download Trend', description: '30-day bar chart showing completed vs failed downloads over time.' },
      { name: 'MusicBrainz Coverage', description: 'Percentage of tracks and albums tagged with MusicBrainz IDs.' },
      { name: 'Jobs Summary', description: 'Last 7 days of job activity broken down by status.' },
    ],
  },
  {
    title: 'Activity',
    path: '/activity',
    icon: 'Activity',
    features: [
      { name: 'Job Monitor', description: 'View all background jobs with status, progress bars, and timing information.' },
      { name: 'Filter by Status', description: 'Filter jobs by Running, Completed, Failed, Paused, Stalled, or Pending.' },
      { name: 'Filter by Type', description: 'Filter by job type (sync, search, download, import, organize, etc.).' },
      { name: 'View Logs', description: 'Open a log viewer modal to see detailed output from any job.' },
      { name: 'Cancel Job', description: 'Cancel a running job to stop it immediately.', minRole: 'dj' },
      { name: 'Retry Job', description: 'Retry a failed job to attempt it again.', minRole: 'dj' },
      { name: 'Pause/Resume', description: 'Pause a running job and resume it later.', minRole: 'dj' },
      { name: 'Clear History', description: 'Clear completed jobs or all job history to clean up the activity view.', minRole: 'director' },
    ],
  },
  {
    title: 'Settings',
    path: '/settings',
    icon: 'Settings',
    minRole: 'director',
    features: [
      { name: 'Indexers Tab', description: 'Add and configure Newznab indexers with URL, API key, categories, and priority.' },
      { name: 'Test Indexer', description: 'Test indexer connection before saving to verify API key and URL are correct.' },
      { name: 'Download Clients Tab', description: 'Configure SABnzbd download clients with host, port, API key, and category.' },
      { name: 'Test Download Client', description: 'Test download client connection to verify it\'s reachable and configured correctly.' },
      { name: 'Root Folders Tab', description: 'Add root folders where music will be stored, with a filesystem browser.' },
      { name: 'Quality Profiles Tab', description: 'Create quality profiles with allowed/preferred formats, bitrate limits, and upgrade rules.' },
      { name: 'Notifications Tab', description: 'Set up Discord, Slack, or generic webhooks for events like downloads and failures.' },
      { name: 'Test Notification', description: 'Send a test notification to verify webhook configuration.' },
    ],
  },
  {
    title: 'Listen & Add',
    path: '/listen',
    icon: 'Mic',
    features: [
      { name: 'HTTPS Required', description: 'Microphone access requires HTTPS (or localhost). Ensure you access Studio54 over a secure connection.' },
      { name: 'Grant Microphone Permission', description: 'Your browser will ask for microphone access on first use. In Chrome, click the lock icon > Site settings > Microphone > Allow. In Firefox, click the lock icon > Permissions. In Safari, go to Settings > Privacy.' },
      { name: 'Identify a Song', description: 'Tap the listen button and hold your device near the speaker. About 12 seconds of audio is recorded and fingerprinted using AcoustID.' },
      { name: 'Review Results', description: 'If the song is identified, you\'ll see the title, artist, album, and a confidence score.' },
      { name: 'Add to Library', description: 'If the artist isn\'t already in your library, click "Add Artist" to add them with their MusicBrainz data.' },
      { name: 'Search for Download', description: 'If the album is in your library, click "Search for Download" to trigger a Usenet search.' },
      { name: 'Mobile Use (PWA)', description: 'For the best mobile experience, add Studio54 to your home screen. In Chrome, tap the three-dot menu > "Add to Home screen". In Safari, tap Share > "Add to Home Screen".' },
    ],
  },
  {
    title: 'Player',
    path: '',
    icon: 'Music',
    features: [
      { name: 'Persistent Player Bar', description: 'Bottom bar showing current track with playback controls, always visible.' },
      { name: 'Play/Pause/Skip', description: 'Standard playback controls with previous, next, play, and pause.' },
      { name: 'Repeat Modes', description: 'Cycle through no repeat, repeat all, and repeat one modes.' },
      { name: 'Queue Sidebar', description: 'View and manage the play queue in a right-side panel.' },
      { name: 'Queue History', description: 'See previously played tracks in the queue history.' },
      { name: 'Floating Mode', description: 'Resize and drag the player as a floating window.' },
      { name: 'Synced Lyrics', description: 'View time-synced lyrics that scroll with playback (when available).' },
      { name: 'Volume Control', description: 'Adjust playback volume with a slider.' },
      { name: 'Seek Bar', description: 'Click or drag to seek to any position in the track.' },
      { name: '30-sec Previews', description: 'Play iTunes previews for tracks not yet in your library.' },
    ],
  },
]

const ROLE_LEVEL: Record<MinRole, number> = {
  partygoer: 0,
  dj: 1,
  director: 2,
}

function hasAccess(userRole: string | undefined, minRole?: MinRole): boolean {
  if (!minRole) return true
  const level = ROLE_LEVEL[userRole as MinRole] ?? 0
  return level >= ROLE_LEVEL[minRole]
}

function HowTo() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const userRole = user?.role || 'partygoer'

  // Filter sections and features by role
  const visibleSections = sections
    .filter(s => hasAccess(userRole, s.minRole))
    .map(s => ({
      ...s,
      features: s.features.filter(f => hasAccess(userRole, f.minRole)),
    }))
    .filter(s => s.features.length > 0)

  const [expandedSections, setExpandedSections] = useState<Set<number>>(new Set(visibleSections.map((_, i) => i)))

  const toggleSection = (index: number) => {
    setExpandedSections(prev => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

  const expandAll = () => setExpandedSections(new Set(visibleSections.map((_, i) => i)))
  const collapseAll = () => setExpandedSections(new Set())

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">How To Use Studio54</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            A complete guide to every feature, organized by page.
          </p>
        </div>
        <div className="flex items-center space-x-2">
          <button
            onClick={expandAll}
            className="px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-[#161B22] rounded hover:bg-gray-200 dark:hover:bg-[#1C2128] transition-colors"
          >
            Expand All
          </button>
          <button
            onClick={collapseAll}
            className="px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-[#161B22] rounded hover:bg-gray-200 dark:hover:bg-[#1C2128] transition-colors"
          >
            Collapse All
          </button>
        </div>
      </div>

      {/* Sections */}
      <div className="space-y-3">
        {visibleSections.map((section, index) => (
          <div key={index} className="card overflow-hidden">
            {/* Section Header */}
            <button
              onClick={() => toggleSection(index)}
              className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors text-left"
            >
              <div className="flex items-center space-x-3">
                {expandedSections.has(index) ? (
                  <FiChevronDown className="w-5 h-5 text-gray-400 flex-shrink-0" />
                ) : (
                  <FiChevronRight className="w-5 h-5 text-gray-400 flex-shrink-0" />
                )}
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{section.title}</h2>
                <span className="text-xs text-gray-400 bg-gray-100 dark:bg-[#0D1117] px-2 py-0.5 rounded-full">
                  {section.features.length} features
                </span>
              </div>
              {section.path && !section.path.includes(':') && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    navigate(section.path)
                  }}
                  className="flex items-center space-x-1 text-xs text-[#FF1493] dark:text-[#ff4da6] hover:text-[#d10f7a] dark:hover:text-[#ff4da6]"
                >
                  <span>Go to page</span>
                  <FiExternalLink className="w-3 h-3" />
                </button>
              )}
            </button>

            {/* Section Content */}
            {expandedSections.has(index) && (
              <div className="border-t border-gray-200 dark:border-[#30363D]">
                <table className="w-full">
                  <tbody className="divide-y divide-gray-100 dark:divide-[#30363D]">
                    {section.features.map((feature, fIndex) => (
                      <tr key={fIndex} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                        <td className="px-5 py-3 w-48 align-top">
                          <span className="text-sm font-medium text-gray-900 dark:text-white whitespace-nowrap">
                            {feature.name}
                          </span>
                        </td>
                        <td className="px-5 py-3">
                          <span className="text-sm text-gray-600 dark:text-gray-400">
                            {feature.description}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export default HowTo
