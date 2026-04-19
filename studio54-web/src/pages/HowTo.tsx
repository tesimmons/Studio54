import { useState } from 'react'
import type { ComponentType } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import {
  FiExternalLink, FiLock,
  FiSearch, FiPlus, FiRefreshCw, FiX, FiTrash2, FiMusic, FiDownload, FiCheck,
  FiGrid, FiList, FiDatabase, FiFilter, FiEye, FiFolder, FiFolderPlus, FiLink,
  FiUsers, FiUser, FiDisc, FiHardDrive, FiUpload,
  FiPlay, FiPause, FiSkipBack, FiSkipForward, FiRepeat, FiVolume2, FiShuffle, FiMaximize2,
  FiBarChart2, FiPieChart, FiTrendingUp, FiActivity, FiCalendar,
  FiSliders, FiBell, FiSend, FiShield, FiGlobe,
  FiFileText, FiEdit2, FiStar, FiMoreVertical,
  FiRotateCcw, FiCheckSquare, FiSmartphone,
  FiHeadphones, FiMic, FiTag, FiBookOpen,
  FiChevronDown, FiChevronLeft, FiChevronRight,
  FiInfo, FiMinus, FiClock, FiArrowUp,
} from 'react-icons/fi'

type MinRole = 'partygoer' | 'dj' | 'director'
type Icon = ComponentType<{ className?: string }>

interface FeatureItem {
  name: string
  description: string
  minRole?: MinRole
  icon?: Icon
}

interface PageTab {
  title: string
  path?: string
  minRole?: MinRole
  description: string
  features: FeatureItem[]
}

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

function RoleBadge({ minRole }: { minRole: MinRole }) {
  if (minRole === 'partygoer') return null
  const config: Record<MinRole, { label: string; cls: string }> = {
    partygoer: { label: 'All', cls: '' },
    dj: { label: 'DJ+', cls: 'bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-700' },
    director: { label: 'Director', cls: 'bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 border border-purple-200 dark:border-purple-700' },
  }
  const { label, cls } = config[minRole]
  return (
    <span className={`inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap ${cls}`}>
      {label}
    </span>
  )
}

function IconChip({ Icon }: { Icon: Icon }) {
  return (
    <span className="inline-flex items-center justify-center w-6 h-6 rounded border border-gray-200 dark:border-[#30363D] bg-gray-100 dark:bg-[#1C2128] flex-shrink-0">
      <Icon className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" />
    </span>
  )
}

const tabs: PageTab[] = [
  {
    title: 'Dashboard',
    path: '/dashboard',
    description: 'The home screen. Shows a live snapshot of your library health, active downloads, and recent wanted albums.',
    features: [
      { name: 'System Stats', icon: FiBarChart2, description: 'Four counters at the top: total artists, monitored albums, wanted albums, and downloaded albums. Refreshes automatically.' },
      { name: 'Active Downloads', icon: FiDownload, description: 'Live counters for in-progress downloads broken down by status: downloading, completed, and failed.' },
      { name: 'Recent Wanted', icon: FiClock, description: 'A list of the last 10 albums with "Wanted" status, each showing the album title, artist, status badge, and a link to the album detail page.' },
      { name: 'Log Level Controls', icon: FiSliders, description: 'Dropdown to change the application log verbosity to DEBUG, INFO, WARNING, or ERROR. Useful for diagnosing issues without restarting the service.', minRole: 'director' },
    ],
  },
  {
    title: 'Library',
    path: '/artists',
    description: 'Your music collection. Browse by artist, album, or track. Manage scanning, importing, and file issues from the tabs along the top.',
    features: [
      { name: 'Browse Tab', icon: FiGrid, description: 'The default view. Toggle between Artist, Album, and Track browse modes using the segmented control.' },
      { name: 'Search Bar', icon: FiSearch, description: 'Type to filter the current browse mode (artists, albums, or tracks) in real time.' },
      { name: 'Genre Filter', icon: FiFilter, description: 'Dropdown that appears in Artist browse mode to narrow the list to a specific genre.' },
      { name: 'Monitoring Filter', icon: FiEye, description: 'Show All, Monitored-only, or Unmonitored-only items.' },
      { name: 'Track Status Filter', icon: FiMusic, description: 'In Track browse mode, filter by All, Has File, or Missing to find gaps in your library.' },
      { name: 'Sort Options', icon: FiArrowUp, description: 'Change the sort order for the current browse mode (e.g., name, file count, date added).' },
      { name: 'Artist / Album Cards', icon: FiGrid, description: 'Click any card to navigate to the Artist Detail or Album Detail page.' },
      { name: 'Monitoring Toggle (card)', icon: FiEye, description: 'The toggle on each artist or album card enables or disables monitoring without leaving the browse view.', minRole: 'dj' },
      { name: 'Bulk Mode', icon: FiCheckSquare, description: 'Button in the toolbar to enter bulk-selection mode. Check boxes appear on each item; use the action toolbar to monitor, unmonitor, or delete the selection.', minRole: 'dj' },
      { name: 'Add Artist', icon: FiPlus, description: 'Opens a search dialog to find an artist on MusicBrainz and add them to your library with a root folder, quality profile, and monitoring settings.', minRole: 'dj' },
      { name: 'Get Metadata', icon: FiRefreshCw, description: 'Queues a background job to refresh artist images and bios from MusicBrainz for all artists.', minRole: 'director' },
      { name: 'Sync All Albums', icon: FiRefreshCw, description: 'Queues a background job to pull the latest album lists from MusicBrainz for every artist in your library.', minRole: 'director' },
      { name: 'Cleanup Orphaned', icon: FiTrash2, description: 'Finds and removes artist or album records that have no associated tracks or files.', minRole: 'director' },
      { name: 'Scanner Tab', icon: FiFolder, description: 'Scan one or all library paths to discover new audio files and update the file index.', minRole: 'director' },
      { name: 'Import Tab', icon: FiUpload, description: 'Import artists in bulk from a MUSE library export, or search MusicBrainz to add multiple artists at once.', minRole: 'director' },
      { name: 'Unlinked Files Tab', icon: FiLink, description: 'Lists audio files that were found on disk but could not be matched to any track in the database. Shows the reason and allows manual re-resolution.', minRole: 'director' },
      { name: 'Unorganized Files Tab', icon: FiFolderPlus, description: 'Lists files that are not in the standard Artist / Album / Track folder structure. Use the organize action to move them.', minRole: 'director' },
    ],
  },
  {
    title: 'Artist Detail',
    description: 'Deep-dive view for a single artist. Shows their full discography, top tracks, and all management actions.',
    features: [
      { name: 'Top Hits — Popular', icon: FiHeadphones, description: 'The Popular column lists the artist\'s top tracks sourced from Last.fm, with listener counts. Click the play icon to hear a 30-second iTunes preview.' },
      { name: 'Top Hits — Most Played', icon: FiPlay, description: 'The Most Played column shows tracks you have played the most (or newest tracks if you have fewer than 5 plays). Each row has Play, Add to Queue, and Add to Playlist buttons.' },
      { name: 'Discography', icon: FiDisc, description: 'All albums grouped by type (Studio, EP, Single, etc.). Click any album card to open Album Detail.' },
      { name: 'Album Monitoring Toggle', icon: FiEye, description: 'The eye icon on each album card in the discography toggles that album\'s monitoring status.', minRole: 'dj' },
      { name: 'Monitor All & Download', icon: FiDownload, description: 'Sets all albums to monitored and immediately triggers a Usenet search for any that are still missing files.', minRole: 'dj' },
      { name: 'Organize Files', icon: FiFolderPlus, description: 'Moves and renames all files for this artist into the standard folder structure based on their metadata and MusicBrainz IDs.', minRole: 'dj' },
      { name: 'Sync Albums', icon: FiRefreshCw, description: 'Refreshes the album list from MusicBrainz so newly announced releases appear in the discography.', minRole: 'dj' },
      { name: 'Search Missing', icon: FiSearch, description: 'Sends a search request to your configured Usenet indexers for every wanted or missing album by this artist.', minRole: 'dj' },
      { name: 'Refresh Metadata', icon: FiRefreshCw, description: 'Re-fetches the artist\'s biography, images, and tags from MusicBrainz and updates the database.', minRole: 'dj' },
      { name: 'Search MBDB', icon: FiDatabase, description: 'Looks up this artist in the local MusicBrainz mirror database by their MBID and displays the raw record — useful for debugging mismatches.', minRole: 'dj' },
      { name: 'Remove Artist', icon: FiTrash2, description: 'Opens a confirmation dialog to delete the artist and all their albums, tracks, and optionally the audio files from disk.', minRole: 'dj' },
      { name: 'Artist Monitoring Toggle', icon: FiEye, description: 'The large toggle near the artist name enables or disables monitoring for the entire artist.', minRole: 'dj' },
      { name: '30-sec Preview', icon: FiPlay, description: 'Available on any track in the Popular column that has an iTunes preview URL. Opens a mini player without affecting the main queue.' },
      { name: 'Download Individual Track', icon: FiDownload, description: 'For tracks that exist in the database but have no file, the download icon triggers a Usenet search for just that track.', minRole: 'dj' },
    ],
  },
  {
    title: 'Album Detail',
    description: 'Full track listing for a single album with per-track actions and download history.',
    features: [
      { name: 'Play All', icon: FiPlay, description: 'Loads all available tracks from this album into the player queue and starts playback.' },
      { name: 'Fetch Lyrics', icon: FiFileText, description: 'Pre-fetches synced and plain lyrics from LRCLIB for every track on the album so they\'re available offline in the player.', minRole: 'dj' },
      { name: 'Organize Files', icon: FiFolderPlus, description: 'Reorganizes the album\'s files into the standard folder structure. Offers a dry-run preview before making changes, and options for metadata file creation and MBID embedding.', minRole: 'dj' },
      { name: 'Monitor / Unmonitor', icon: FiEye, description: 'Toggles whether this album is monitored for automatic download searches. The icon in the header reflects the current state.', minRole: 'dj' },
      { name: 'Manual Search', icon: FiSearch, description: 'Triggers a Usenet search for the whole album. Checks the MUSE library first, then falls back to configured indexers.', minRole: 'dj' },
      { name: 'Custom Folder Path', icon: FiFolder, description: 'Opens a filesystem browser so you can point Studio54 at a non-standard folder where the album\'s files are stored.' },
      { name: 'Scan & Match', icon: FiSearch, description: 'Scans the album\'s folder for audio files and automatically matches them to tracks in the database by MBID, filename, or duration.' },
      { name: 'Track — Play', icon: FiPlay, description: 'Plays the linked audio file for a track immediately, replacing the current queue.' },
      { name: 'Track — Queue', icon: FiPlus, description: 'Appends the linked audio file to the end of the current play queue.' },
      { name: 'Track — Preview', icon: FiPlay, description: 'Plays a 30-second iTunes preview for a track that has no linked file.' },
      { name: 'Track — Search', icon: FiSearch, description: 'Searches Usenet for a single missing track.', minRole: 'dj' },
      { name: 'Track — Unlink', icon: FiLink, description: 'Removes the file association from a track record without deleting the file from disk. Useful for correcting wrong matches.', minRole: 'dj' },
      { name: 'Track — Delete File', icon: FiTrash2, description: 'Permanently deletes the audio file from disk, unlinks it from the track, and cleans up any empty folders.', minRole: 'dj' },
      { name: 'Track — Download File', icon: FiDownload, description: 'Downloads the linked audio file to your local browser download folder.', minRole: 'dj' },
      { name: 'Track — Add to Playlist', icon: FiList, description: 'Opens a playlist picker to add the linked track to any playlist you own.' },
      { name: 'Download History', icon: FiClock, description: 'Expandable section at the bottom showing every download attempt for this album: NZB titles, file sizes, timestamps, indexer, and any error messages.' },
      { name: 'Clear Downloads', icon: FiTrash2, description: 'Removes failed or all download history entries and resets the album status so it can be searched again.', minRole: 'dj' },
    ],
  },
  {
    title: 'Albums',
    path: '/albums',
    description: 'A flat list of every album in your library with filtering, sorting, and quick search actions.',
    features: [
      { name: 'Status Filter', icon: FiFilter, description: 'Filter the album list by status: All, Wanted, Searching, Downloading, Downloaded, or Failed.' },
      { name: 'Monitoring Filter', icon: FiEye, description: 'Show All albums, or limit to Monitored or Unmonitored.' },
      { name: 'Sort Options', icon: FiArrowUp, description: 'Sort by album title, file count, release date, or the date the album was added to your library.' },
      { name: 'Search', icon: FiSearch, description: 'Real-time text filter that matches album title and artist name.' },
      { name: 'Album Table Row', icon: FiList, description: 'Each row shows title, artist, release year, track count, status badge, and album type. Click the title or artist name to navigate to the respective detail page.' },
      { name: 'Search Icon (row)', icon: FiSearch, description: 'The magnifying-glass button on each row triggers an immediate Usenet search for that album.', minRole: 'dj' },
      { name: 'Pagination', icon: FiChevronRight, description: 'Navigate between pages when the list exceeds the items-per-page limit.' },
    ],
  },
  {
    title: 'File Management',
    path: '/file-management',
    minRole: 'director',
    description: 'Low-level tools for managing files across your library paths. Run bulk organization, MBID writing, linking, and maintenance jobs.',
    features: [
      { name: 'Library Jobs Tab', icon: FiHardDrive, description: 'Select a library path and run one of the bulk operations against all files in that path.' },
      { name: 'Organize Library', icon: FiFolderPlus, description: 'Moves and renames all files in a library path to match the standard Artist / Album / Track folder structure.' },
      { name: 'Validate Structure', icon: FiCheck, description: 'Checks that every file is in the correct folder location and reports any mismatches without moving anything.' },
      { name: 'Fetch Metadata', icon: FiDatabase, description: 'Searches MusicBrainz for files that lack MBIDs and writes the discovered IDs into the file\'s comment tag.' },
      { name: 'Validate MBIDs', icon: FiCheck, description: 'Reads the MBIDs written into file comment tags and verifies they still match the correct recordings in MusicBrainz.' },
      { name: 'Link Files', icon: FiLink, description: 'Matches audio files that have valid MBIDs to their corresponding track records in the database.' },
      { name: 'Reindex Albums', icon: FiRefreshCw, description: 'Reads file metadata to detect albums and singles, then creates or updates the corresponding database records.' },
      { name: 'Verify Audio', icon: FiCheck, description: 'Runs an integrity check on recently downloaded audio files to confirm they are valid and fully playable.' },
      { name: 'Artist Organization Tab', icon: FiUser, description: 'Same as Organize Library but scoped to a single artist. Useful for fixing one artist without touching the rest of the library.' },
      { name: 'Jobs & Audit Tab', icon: FiActivity, description: 'Lists all running and completed file management jobs with live progress bars. The audit log shows every file operation (move, rename, delete) performed.' },
      { name: 'Rollback', icon: FiRotateCcw, description: 'Reverses a completed organization job, moving every file back to its original location.' },
      { name: 'Maintenance Tab', icon: FiSliders, description: 'Clean up old job log files. Set a retention period, preview what will be deleted, then confirm.' },
    ],
  },
  {
    title: 'DJ Requests',
    path: '/dj-requests',
    description: 'Submit and manage requests for new artists, albums, or tracks to be added to the library.',
    features: [
      { name: 'New Request', icon: FiPlus, description: 'Opens a form to request an artist, album, or track. Include any notes to help the reviewer understand what you\'re looking for.' },
      { name: 'Request List', icon: FiList, description: 'Paginated table of all requests showing type, title, status, who submitted it, and when.' },
      { name: 'Status Filter', icon: FiFilter, description: 'Filter requests by status: All, Pending, Approved, Rejected, or Fulfilled.' },
      { name: 'Type Filter', icon: FiFilter, description: 'Filter by request type: Artist, Album, or Track.' },
      { name: 'My Requests Toggle', icon: FiUser, description: 'Show only requests submitted by you, hiding everyone else\'s.' },
      { name: 'Approve / Reject', icon: FiCheck, description: 'Opens a response dialog where you can write a note and mark the request approved or rejected.', minRole: 'director' },
      { name: 'Fulfill Request', icon: FiCheck, description: 'Marks an approved request as fulfilled once the content has been added to the library.', minRole: 'director' },
      { name: 'Add to Library', icon: FiPlus, description: 'For approved artist requests, this button searches MusicBrainz for the artist and adds them to the library with a single click.', minRole: 'director' },
      { name: 'View by User', icon: FiUsers, description: 'Switches to a grouped view that shows all requests organized by the user who submitted them.', minRole: 'director' },
    ],
  },
  {
    title: 'Playlists',
    path: '/playlists',
    description: 'Create and manage personal playlists. Add tracks from anywhere in the app and play them back in order.',
    features: [
      { name: 'Create Playlist', icon: FiPlus, description: 'Opens a dialog to name your new playlist and add an optional description.' },
      { name: 'Edit Playlist', icon: FiEdit2, description: 'Rename a playlist or update its description by clicking the edit icon next to its name.' },
      { name: 'Delete Playlist', icon: FiTrash2, description: 'Permanently removes the playlist. The actual audio files are not affected.' },
      { name: 'Play All', icon: FiPlay, description: 'Loads the entire playlist into the player queue and begins playback from the first track.' },
      { name: 'Track List', icon: FiList, description: 'Shows all tracks in the playlist with their position, title, artist, album, and duration.' },
      { name: 'Play Track', icon: FiPlay, description: 'Clicking the play icon on any track in the list starts playback from that track.' },
      { name: 'Remove Track', icon: FiX, description: 'Removes a track from the playlist without deleting the file.' },
      { name: 'Add Tracks (elsewhere)', icon: FiPlus, description: 'Tracks can be added from Album Detail, Artist Detail, and Library browse views using the playlist icon on any track row.' },
    ],
  },
  {
    title: 'Calendar',
    path: '/calendar',
    description: 'See upcoming album releases for all monitored artists, displayed on a monthly calendar.',
    features: [
      { name: 'Monthly Calendar Grid', icon: FiCalendar, description: 'Each day cell shows album releases scheduled for that date. Scroll or navigate with the arrow buttons to move between months.' },
      { name: 'Release Entry', icon: FiDisc, description: 'Each entry shows the album cover thumbnail, album title, and artist name.' },
      { name: 'Navigate to Album', icon: FiExternalLink, description: 'Click any release entry to open the Album Detail page for that release.' },
      { name: 'Month Navigation', icon: FiChevronLeft, description: 'Use the left and right arrow buttons at the top to step back and forward one month at a time.' },
    ],
  },
  {
    title: 'Statistics',
    path: '/statistics',
    description: 'Charts and counters giving you a high-level view of your library health and download activity.',
    features: [
      { name: 'Summary Cards', icon: FiBarChart2, description: 'Four top-level counters: total artists, total albums, total tracks, and total library size on disk.' },
      { name: 'Album Status Chart', icon: FiPieChart, description: 'Pie or donut chart showing the proportion of albums in each status (Wanted, Downloading, Downloaded, Failed, etc.).' },
      { name: 'File Formats Chart', icon: FiBarChart2, description: 'Bar chart showing how many tracks are in each audio format: FLAC, MP3, AAC, OGG, etc.' },
      { name: 'Download Trend', icon: FiTrendingUp, description: '30-day bar chart overlaying completed vs failed downloads per day. Helps spot periods of indexer problems.' },
      { name: 'MusicBrainz Coverage', icon: FiDatabase, description: 'Percentage of your tracks and albums that have MusicBrainz IDs embedded. Higher is better for organization and matching.' },
      { name: 'Jobs Summary', icon: FiActivity, description: 'Table of job activity from the last 7 days, broken down by job type and status (completed, failed, running).' },
    ],
  },
  {
    title: 'Activity',
    path: '/activity',
    description: 'Monitor all background jobs (syncs, downloads, scans, searches) in real time.',
    features: [
      { name: 'Job List', icon: FiList, description: 'Table of all jobs with their type, status, progress bar, start time, and duration.' },
      { name: 'Filter by Status', icon: FiFilter, description: 'Show only jobs in a given state: Running, Completed, Failed, Paused, Stalled, or Pending.' },
      { name: 'Filter by Type', icon: FiFilter, description: 'Narrow the list to a specific job type: sync, search, download, import, organize, scan, etc.' },
      { name: 'View Logs', icon: FiFileText, description: 'Click the log icon on any job to open a scrollable log viewer modal with the full stdout/stderr output.' },
      { name: 'Cancel Job', icon: FiX, description: 'Sends a cancellation signal to a running job, stopping it as soon as the current step finishes.', minRole: 'dj' },
      { name: 'Retry Job', icon: FiRefreshCw, description: 'Re-queues a failed job so it runs again from the beginning.', minRole: 'dj' },
      { name: 'Pause / Resume', icon: FiPause, description: 'Pauses a running job after the current step and resumes it when you\'re ready.', minRole: 'dj' },
      { name: 'Clear History', icon: FiTrash2, description: 'Removes completed jobs from the list. Choose to clear only completed jobs or everything including failures.', minRole: 'director' },
      { name: 'Auto-refresh', icon: FiRefreshCw, description: 'The activity list polls automatically so running job progress stays current without a manual page reload.' },
    ],
  },
  {
    title: 'Settings',
    path: '/settings',
    minRole: 'director',
    description: 'Configure indexers, download clients, root folders, quality profiles, and notifications.',
    features: [
      { name: 'Indexers Tab', icon: FiGlobe, description: 'Add and configure Newznab-compatible indexers. Each indexer needs a name, URL, API key, and category list.' },
      { name: 'Test Indexer', icon: FiCheck, description: 'Sends a test query to the indexer to verify the URL and API key are correct before saving.' },
      { name: 'Enable / Disable Indexer', icon: FiEye, description: 'Toggle individual indexers on or off without deleting them — useful for temporarily bypassing a slow or broken indexer.' },
      { name: 'Download Clients Tab', icon: FiDownload, description: 'Add SABnzbd (or compatible) download clients. Requires host, port, API key, and a category name to route downloads.' },
      { name: 'Test Download Client', icon: FiCheck, description: 'Pings the download client to verify it is reachable and the API key is accepted.' },
      { name: 'Root Folders Tab', icon: FiFolder, description: 'Add the root directories where music will be stored. A filesystem browser helps you navigate to the correct path.' },
      { name: 'Quality Profiles Tab', icon: FiSliders, description: 'Create profiles that define which audio formats and bitrates are acceptable. Profiles can be assigned to artists at import time.' },
      { name: 'Notifications Tab', icon: FiBell, description: 'Set up webhooks for Discord, Slack, or any generic HTTP endpoint. Select which events trigger a notification (e.g., download completed, album added).' },
      { name: 'Test Notification', icon: FiSend, description: 'Sends a sample payload to a configured webhook to confirm it is receiving messages.' },
    ],
  },
  {
    title: 'Listen & Add',
    path: '/listen',
    description: 'Identify a song playing near you using your microphone, then add the artist to your library or search for the album.',
    features: [
      { name: 'HTTPS Requirement', icon: FiLock, description: 'Microphone access requires a secure (HTTPS) connection. If the listen button is disabled, make sure you are accessing Studio54 via https://, not http://.' },
      { name: 'Grant Microphone Permission', icon: FiShield, description: 'On first use your browser will ask for microphone permission. In Chrome: click the lock icon → Site settings → Microphone → Allow. In Firefox: click the lock icon → Permissions. In Safari: Settings → Privacy → Microphone.' },
      { name: 'Listen Button', icon: FiMic, description: 'Tap to start recording. About 12 seconds of audio is captured and fingerprinted via AcoustID. A spinner shows while the lookup is in progress.' },
      { name: 'Identification Result', icon: FiMusic, description: 'If a match is found, the card displays track title, artist, album, and a confidence percentage.' },
      { name: 'Add Artist', icon: FiPlus, description: 'If the identified artist is not already in your library, this button imports them from MusicBrainz with their full discography.' },
      { name: 'Search for Download', icon: FiSearch, description: 'If the album is already in your library but missing files, this button triggers a Usenet search for it immediately.' },
      { name: 'PWA / Home Screen', icon: FiSmartphone, description: 'For the best mobile experience add Studio54 to your home screen. Chrome: three-dot menu → "Add to Home screen". Safari: Share → "Add to Home Screen".' },
    ],
  },
  {
    title: 'Sound Booth',
    path: '/sound-booth',
    description: 'See who is currently listening and what they\'re playing. Browse and play shared playlists.',
    features: [
      { name: 'Now Listening', icon: FiHeadphones, description: 'Cards showing every user currently playing music with their display name, role badge, current track title, and album art.' },
      { name: 'Click Listener Card', icon: FiExternalLink, description: 'Clicking a listener\'s card navigates to the album or artist they are currently listening to.' },
      { name: 'Role Badge', icon: FiShield, description: 'Each listener card displays a colour-coded role badge: Director (amber), DJ (purple), Bouncer (blue), Partygoer (green).' },
      { name: 'Live Updates', icon: FiRefreshCw, description: 'The Now Listening section automatically polls every few seconds so the list stays current without a manual refresh.' },
      { name: 'Playlists Section', icon: FiList, description: 'Below the listeners, all shared playlists are listed with their name and track count.' },
      { name: 'Expand / Collapse Playlists', icon: FiChevronDown, description: 'The chevron button next to each playlist name expands or collapses the track list for that playlist.' },
      { name: 'Play Playlist', icon: FiPlay, description: 'The play button next to a playlist name loads its entire track list into the player queue.' },
      { name: 'Play Track (playlist)', icon: FiPlay, description: 'The play icon on any track inside an expanded playlist starts playback from that track.' },
      { name: 'Queue Track (playlist)', icon: FiPlus, description: 'The queue icon on any expanded track appends it to the end of the current play queue.' },
    ],
  },
  {
    title: 'Reading Room',
    path: '/reading-room',
    description: 'Your audiobook and e-book library. Browse authors, books, and series. Same tab structure as the music Library.',
    features: [
      { name: 'Browse Tab', icon: FiGrid, description: 'Toggle between Author, Book, and Series browse modes. Each mode has its own sort and filter options.' },
      { name: 'Search Bar', icon: FiSearch, description: 'Filters the current browse mode in real time.' },
      { name: 'Genre Filter', icon: FiFilter, description: 'In Author mode, a dropdown to narrow the list to a specific genre.' },
      { name: 'Monitoring Filter', icon: FiEye, description: 'Show All, Monitored-only, or Unmonitored-only items.' },
      { name: 'Author Sort', icon: FiArrowUp, description: 'Sort authors by name, total file count (ascending or descending), or date added.' },
      { name: 'Book Sort', icon: FiArrowUp, description: 'Sort books by release date, title, author name, file count, or date added.' },
      { name: 'Series Sort', icon: FiArrowUp, description: 'Sort series by name, book count, or date added.' },
      { name: 'Book Card — "..." Menu', icon: FiMoreVertical, description: 'For books with co-authors, hover the book cover to reveal a "..." button. Click it to open the Set Lead Author menu.' },
      { name: 'Set Lead Author', icon: FiStar, description: 'For books with co-authors, choose which author appears as the primary author on the book card and in file organization.', minRole: 'dj' },
      { name: 'Bulk Mode', icon: FiCheckSquare, description: 'Enables checkboxes on author cards. Use the action toolbar to monitor, unmonitor, or delete selected authors in bulk.', minRole: 'dj' },
      { name: 'Move to Author', icon: FiUser, description: 'In bulk mode, reassign selected books to a different author.', minRole: 'dj' },
      { name: 'Merge Authors', icon: FiUsers, description: 'Combine two author records into one, transferring all books to the surviving record.', minRole: 'director' },
      { name: 'Add Author', icon: FiPlus, description: 'Search and add a new author with a root folder and monitoring options.', minRole: 'dj' },
      { name: 'Get Metadata', icon: FiRefreshCw, description: 'Refreshes author images and biographies for all authors.', minRole: 'director' },
      { name: 'Sync All Books', icon: FiRefreshCw, description: 'Syncs the book list for all authors to pick up newly catalogued titles.', minRole: 'director' },
      { name: 'Scanner Tab', icon: FiFolder, description: 'Scan library paths to discover and index audiobook files.', minRole: 'director' },
      { name: 'Import Tab', icon: FiUpload, description: 'Import authors in bulk or search to add new ones.', minRole: 'director' },
      { name: 'Unlinked Files Tab', icon: FiLink, description: 'Lists audio files that could not be matched to any book chapter.', minRole: 'director' },
      { name: 'Unorganized Files Tab', icon: FiFolderPlus, description: 'Lists files outside the standard folder structure.', minRole: 'director' },
    ],
  },
  {
    title: 'Author Detail',
    description: 'All books by a single author. Manage monitoring, file organization, and series detection.',
    features: [
      { name: 'Book Grid', icon: FiGrid, description: 'Cover art grid of every book by this author showing title, series position, and chapter count.' },
      { name: 'Navigate to Book', icon: FiExternalLink, description: 'Click any book card to open the Book Detail page.' },
      { name: 'Author Monitoring Toggle', icon: FiEye, description: 'Enables or disables monitoring for this author, controlling whether new books are automatically searched.', minRole: 'dj' },
      { name: 'Monitor All & Download', icon: FiDownload, description: 'Sets all books to monitored and immediately triggers a search for any that are missing files.', minRole: 'dj' },
      { name: 'Organize Files', icon: FiFolderPlus, description: 'Moves and renames all files for this author into the standard Author / Book folder structure.', minRole: 'dj' },
      { name: 'Sync Books', icon: FiRefreshCw, description: 'Refreshes the book list to add newly catalogued titles.', minRole: 'dj' },
      { name: 'Search Missing', icon: FiSearch, description: 'Triggers a search for every monitored book that has no files.', minRole: 'dj' },
      { name: 'Refresh Metadata', icon: FiRefreshCw, description: 'Re-fetches author images, biography, and book metadata.', minRole: 'dj' },
      { name: 'Detect Series', icon: FiTag, description: 'Analyses book metadata to automatically group books into series.', minRole: 'dj' },
      { name: 'Book Monitoring Toggle', icon: FiEye, description: 'The eye icon on each book card toggles monitoring for that individual book.', minRole: 'dj' },
      { name: 'Add to Series (book card)', icon: FiTag, description: 'Assigns the book to an existing or new series directly from the author detail view.', minRole: 'dj' },
      { name: 'Remove Author', icon: FiTrash2, description: 'Deletes the author and all their books from the library, with an option to also delete the audio files from disk.', minRole: 'dj' },
    ],
  },
  {
    title: 'Book Detail',
    description: 'Full chapter listing for a single book with playback, progress tracking, and management actions.',
    features: [
      { name: 'Play Book', icon: FiPlay, description: 'Loads all available chapters into the player queue in order and starts playback.' },
      { name: 'Shuffle Play', icon: FiShuffle, description: 'Loads all chapters in random order and starts playback.' },
      { name: 'Author Link', icon: FiUser, description: 'Click the author name under the book title to navigate to the Author Detail page.' },
      { name: 'Series Link', icon: FiBookOpen, description: 'If the book belongs to a series, click the series name to open the Series Detail page.' },
      { name: 'Prev / Next Book', icon: FiChevronRight, description: 'Arrow buttons next to the series name jump to the previous or next book in the series.' },
      { name: 'Mark Finished', icon: FiCheck, description: 'Toggles the book\'s finished/read status in your personal progress tracker.' },
      { name: 'Reset Progress', icon: FiRotateCcw, description: 'Clears your listening progress so the book shows as unstarted again.' },
      { name: 'Set Lead Author', icon: FiStar, description: 'For books with co-authors, opens a dialog to choose the primary author.', minRole: 'dj' },
      { name: 'Organize Files', icon: FiFolderPlus, description: 'Reorganizes the book\'s files with a dry-run preview option before making changes.', minRole: 'dj' },
      { name: 'Monitor / Unmonitor', icon: FiEye, description: 'Toggles whether this book is monitored for automatic download searches.', minRole: 'dj' },
      { name: 'Manual Search', icon: FiSearch, description: 'Triggers a search for this book. Checks the MUSE library first, then falls back to Usenet indexers.', minRole: 'dj' },
      { name: 'Custom Folder Path', icon: FiFolder, description: 'Opens a filesystem browser to point Studio54 at a non-standard folder where the book\'s files are located.', minRole: 'dj' },
      { name: 'Scan & Match Files', icon: FiSearch, description: 'Scans the book\'s folder for audio files and matches them to chapters by metadata or filename.', minRole: 'dj' },
      { name: 'Edit Related Series', icon: FiEdit2, description: 'Add a free-text note linking this book to related series for reference.', minRole: 'dj' },
      { name: 'Delete Book', icon: FiTrash2, description: 'Removes the book from the library with an option to also delete the audio files from disk.', minRole: 'dj' },
      { name: 'Chapter — Play', icon: FiPlay, description: 'Plays a single chapter immediately.' },
      { name: 'Chapter — Queue', icon: FiPlus, description: 'Appends a single chapter to the end of the current play queue.' },
    ],
  },
  {
    title: 'Series Detail',
    description: 'All books in a single series, in reading order. Manage the series and create a playlist.',
    features: [
      { name: 'Book List', icon: FiList, description: 'All books in the series displayed in order with cover art, title, and series position number.' },
      { name: 'Navigate to Book', icon: FiExternalLink, description: 'Click any book in the list to open its Book Detail page.' },
      { name: 'Monitor / Unmonitor', icon: FiEye, description: 'Toggles monitoring for the entire series.', minRole: 'dj' },
      { name: 'Create Playlist', icon: FiList, description: 'Automatically creates a new playlist from every available chapter across all books in the series, in reading order.', minRole: 'dj' },
      { name: 'Add Book', icon: FiPlus, description: 'Opens a picker to assign an existing book to this series.', minRole: 'dj' },
      { name: 'Remove Book', icon: FiMinus, description: 'Removes a book from the series without deleting the book or its files.', minRole: 'dj' },
      { name: 'Delete Series', icon: FiTrash2, description: 'Deletes the series record. Books belonging to the series are not deleted — they become unassigned.', minRole: 'dj' },
    ],
  },
  {
    title: 'Player',
    description: 'The persistent playback bar at the bottom of every page. Controls all audio playback.',
    features: [
      { name: 'Play / Pause', icon: FiPlay, description: 'The large centre button starts or pauses playback of the current track.' },
      { name: 'Previous / Next', icon: FiSkipBack, description: 'Skip to the previous or next track in the queue.' },
      { name: 'Seek Bar', icon: FiInfo, description: 'Click or drag the progress bar to jump to any position in the current track.' },
      { name: 'Volume Slider', icon: FiVolume2, description: 'Drag to adjust playback volume. Click the speaker icon to mute and unmute.' },
      { name: 'Repeat Modes', icon: FiRepeat, description: 'Click the repeat icon to cycle through: Off → Repeat All → Repeat One.' },
      { name: 'Queue Sidebar', icon: FiList, description: 'Click the queue icon (right side of player bar) to open a panel showing the upcoming tracks and play history.' },
      { name: 'Remove from Queue', icon: FiX, description: 'In the queue sidebar, click the × on any track to remove it from the queue.' },
      { name: 'Floating Mode', icon: FiMaximize2, description: 'Detach the player into a resizable, draggable floating window that stays on top while you browse other pages.' },
      { name: 'Synced Lyrics', icon: FiFileText, description: 'When lyrics are available, a lyrics button appears. Click it to open a panel showing time-synced lyrics that highlight as the track plays.' },
      { name: '30-sec Previews', icon: FiPlay, description: 'iTunes previews play through the same player bar but are capped at 30 seconds and do not affect the main queue.' },
      { name: 'Now Playing Info', icon: FiDisc, description: 'The left side of the player bar shows album art, track title, and artist name. Click the album art to navigate to the Album Detail page.' },
      { name: 'Skip Forward / Back', icon: FiSkipForward, description: 'Skip forward or back within a track by the configured interval (useful for audiobooks and podcasts).' },
    ],
  },
]

function HowTo() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const userRole = user?.role || 'partygoer'

  const visibleTabs = tabs
    .filter(tab => hasAccess(userRole, tab.minRole))
    .map(tab => ({
      ...tab,
      features: tab.features.filter(f => hasAccess(userRole, f.minRole)),
    }))

  const [activeIndex, setActiveIndex] = useState(0)
  const activeTab = visibleTabs[activeIndex] ?? visibleTabs[0]

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 mb-4">
        <h1 className="text-xl md:text-2xl font-bold text-gray-900 dark:text-white">How To Use Studio54</h1>
        <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
          A guide to every page and feature, filtered to your permission level.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex-shrink-0 border-b border-gray-200 dark:border-[#30363D]">
        <div className="overflow-x-auto scrollbar-hide">
          <div className="flex min-w-max">
            {visibleTabs.map((tab, i) => (
              <button
                key={i}
                onClick={() => setActiveIndex(i)}
                className={`
                  px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors
                  ${i === activeIndex
                    ? 'border-[#FF1493] text-[#FF1493] dark:text-[#ff4da6] dark:border-[#ff4da6]'
                    : 'border-transparent text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:border-gray-300 dark:hover:border-[#484F58]'
                  }
                `}
              >
                {tab.title}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Tab content — fills remaining height, scrolls independently */}
      <div className="flex-1 min-h-0 overflow-y-auto pt-4 pb-2">
        {activeTab && (
          <div className="card overflow-hidden">
            {/* Page header */}
            <div className="px-5 py-4 border-b border-gray-200 dark:border-[#30363D] flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-gray-900 dark:text-white">{activeTab.title}</h2>
                <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">{activeTab.description}</p>
              </div>
              {activeTab.path && !activeTab.path.includes(':') && (
                <button
                  onClick={() => navigate(activeTab.path!)}
                  className="flex-shrink-0 flex items-center gap-1 text-xs text-[#FF1493] dark:text-[#ff4da6] hover:underline"
                >
                  <span>Go to page</span>
                  <FiExternalLink className="w-3 h-3" />
                </button>
              )}
            </div>

            {/* Feature table */}
            <table className="w-full">
              <tbody className="divide-y divide-gray-100 dark:divide-[#30363D]">
                {activeTab.features.map((feature, i) => (
                  <tr key={i} className="hover:bg-gray-50 dark:hover:bg-[#161B22]/50">
                    <td className="px-5 py-3 align-top w-56">
                      <div className="flex items-start gap-2">
                        {feature.icon && <IconChip Icon={feature.icon} />}
                        <div className="flex items-center gap-2 flex-wrap min-w-0">
                          <span className="text-sm font-medium text-gray-900 dark:text-white">
                            {feature.name}
                          </span>
                          {feature.minRole && feature.minRole !== 'partygoer' && (
                            <RoleBadge minRole={feature.minRole} />
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3 align-top">
                      <span className="text-sm text-gray-600 dark:text-gray-400">
                        {feature.description}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Footer: permission note */}
            {activeTab.minRole && activeTab.minRole !== 'partygoer' && (
              <div className="px-5 py-3 border-t border-gray-200 dark:border-[#30363D] flex items-center gap-2 bg-gray-50 dark:bg-[#0D1117]">
                <FiLock className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  This page requires{' '}
                  <span className="font-medium">{activeTab.minRole === 'dj' ? 'DJ or above' : 'Director'}</span>{' '}
                  permissions.
                </span>
              </div>
            )}
          </div>
        )}

        {/* Role legend */}
        <div className="mt-3 flex items-center gap-4 flex-wrap">
          <span className="text-xs text-gray-400 dark:text-gray-500">Permission required:</span>
          <RoleBadge minRole="dj" />
          <RoleBadge minRole="director" />
          <span className="text-xs text-gray-400 dark:text-gray-500">Items with no badge are available to all users.</span>
        </div>
      </div>
    </div>
  )
}

export default HowTo
