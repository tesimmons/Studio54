import type { WidgetDefinition, DashboardLayoutItem, WidgetCategory } from '../../types'
import StatCardWidget from './widgets/StatCardWidget'
import DiskWidget from './widgets/DiskWidget'
import AlbumStatusWidget from './widgets/AlbumStatusWidget'
import FileFormatsWidget from './widgets/FileFormatsWidget'
import DownloadTrendWidget from './widgets/DownloadTrendWidget'
import MusicBrainzWidget from './widgets/MusicBrainzWidget'
import ActiveDownloadsWidget from './widgets/ActiveDownloadsWidget'
import RecentWantedWidget from './widgets/RecentWantedWidget'
import JobsWidget from './widgets/JobsWidget'
import SectionHeaderWidget from './widgets/SectionHeaderWidget'

export const WIDGET_REGISTRY: WidgetDefinition[] = [
  // Section headers
  { id: 'section-music', label: 'Disco Lounge', category: 'section', defaultSize: { w: 12, h: 1 }, minSize: { w: 12, h: 1 }, component: SectionHeaderWidget },
  { id: 'section-audiobook', label: 'Reading Room', category: 'section', defaultSize: { w: 12, h: 1 }, minSize: { w: 12, h: 1 }, component: SectionHeaderWidget },
  { id: 'section-system', label: 'System & Activity', category: 'section', defaultSize: { w: 12, h: 1 }, minSize: { w: 12, h: 1 }, component: SectionHeaderWidget },

  // Music stats cards
  { id: 'total-artists', label: 'Total Artists', category: 'stats', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: StatCardWidget },
  { id: 'monitored-albums', label: 'Monitored Albums', category: 'stats', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: StatCardWidget },
  { id: 'wanted-albums', label: 'Linked Albums', category: 'stats', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: StatCardWidget },
  { id: 'downloaded', label: 'Downloaded', category: 'stats', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: StatCardWidget },
  { id: 'tracks', label: 'Tracks', category: 'stats', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: StatCardWidget },

  // Shared stats cards (no libraryType)
  { id: 'library-size', label: 'Library Size', category: 'stats', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, component: StatCardWidget },

  // Audiobook stats cards
  { id: 'total-authors', label: 'Total Authors', category: 'stats', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, libraryType: 'audiobook', component: StatCardWidget },
  { id: 'total-books', label: 'Books', category: 'stats', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, libraryType: 'audiobook', component: StatCardWidget },

  // System (director only)
  { id: 'system-disk', label: 'System Disk', category: 'system', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, requiredRole: 'director', component: DiskWidget },
  { id: 'storage-disk', label: 'Storage Disk', category: 'system', defaultSize: { w: 3, h: 2 }, minSize: { w: 1, h: 1 }, requiredRole: 'director', component: DiskWidget },

  // Music charts
  { id: 'album-status', label: 'Album Status', category: 'charts', defaultSize: { w: 6, h: 4 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: AlbumStatusWidget },
  { id: 'file-formats', label: 'File Formats', category: 'charts', defaultSize: { w: 6, h: 4 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: FileFormatsWidget },
  { id: 'download-trend', label: 'Download Trend', category: 'charts', defaultSize: { w: 12, h: 4 }, minSize: { w: 1, h: 1 }, component: DownloadTrendWidget },
  { id: 'musicbrainz-coverage', label: 'MusicBrainz Coverage', category: 'charts', defaultSize: { w: 4, h: 4 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: MusicBrainzWidget },

  // Lists
  { id: 'active-downloads', label: 'Active Downloads', category: 'lists', defaultSize: { w: 4, h: 4 }, minSize: { w: 1, h: 1 }, component: ActiveDownloadsWidget },
  { id: 'recent-wanted', label: 'Recent Wanted', category: 'lists', defaultSize: { w: 12, h: 4 }, minSize: { w: 1, h: 1 }, libraryType: 'music', component: RecentWantedWidget },
  { id: 'jobs-last-7d', label: 'Jobs (7 Days)', category: 'lists', defaultSize: { w: 4, h: 4 }, minSize: { w: 1, h: 1 }, component: JobsWidget },
]

export const WIDGET_MAP = new Map(WIDGET_REGISTRY.map(w => [w.id, w]))

export const CATEGORY_LABELS: Record<WidgetCategory, string> = {
  stats: 'Statistics',
  system: 'System',
  charts: 'Charts',
  lists: 'Lists',
  section: 'Sections',
}

export const DEFAULT_LAYOUT: DashboardLayoutItem[] = [
  // Disco Lounge section
  { i: 'section-music', x: 0, y: 0, w: 12, h: 1, minW: 12, minH: 1 },
  { i: 'total-artists', x: 0, y: 1, w: 3, h: 2, minW: 1, minH: 1 },
  { i: 'monitored-albums', x: 3, y: 1, w: 3, h: 2, minW: 1, minH: 1 },
  { i: 'wanted-albums', x: 6, y: 1, w: 3, h: 2, minW: 1, minH: 1 },
  { i: 'downloaded', x: 9, y: 1, w: 3, h: 2, minW: 1, minH: 1 },
  { i: 'tracks', x: 0, y: 3, w: 3, h: 2, minW: 1, minH: 1 },
  { i: 'library-size', x: 3, y: 3, w: 3, h: 2, minW: 1, minH: 1 },
  { i: 'album-status', x: 0, y: 5, w: 6, h: 4, minW: 1, minH: 1 },
  { i: 'file-formats', x: 6, y: 5, w: 6, h: 4, minW: 1, minH: 1 },
  { i: 'download-trend', x: 0, y: 9, w: 12, h: 4, minW: 1, minH: 1 },
  { i: 'musicbrainz-coverage', x: 0, y: 13, w: 4, h: 4, minW: 1, minH: 1 },
  { i: 'active-downloads', x: 4, y: 13, w: 4, h: 4, minW: 1, minH: 1 },
  { i: 'jobs-last-7d', x: 8, y: 13, w: 4, h: 4, minW: 1, minH: 1 },
  { i: 'recent-wanted', x: 0, y: 17, w: 12, h: 4, minW: 1, minH: 1 },
  // Reading Room section
  { i: 'section-audiobook', x: 0, y: 21, w: 12, h: 1, minW: 12, minH: 1 },
  { i: 'total-authors', x: 0, y: 22, w: 3, h: 2, minW: 1, minH: 1 },
  { i: 'total-books', x: 3, y: 22, w: 3, h: 2, minW: 1, minH: 1 },
  // System & Activity section
  { i: 'section-system', x: 0, y: 24, w: 12, h: 1, minW: 12, minH: 1 },
  { i: 'system-disk', x: 0, y: 25, w: 4, h: 2, minW: 1, minH: 1 },
  { i: 'storage-disk', x: 4, y: 25, w: 4, h: 2, minW: 1, minH: 1 },
]
