import { useState } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import {
  FiLogOut,
  FiX,
} from 'react-icons/fi'
import { APP_VERSION, APP_NAME, APP_DESCRIPTION } from '../version'
import PersistentPlayer from './PersistentPlayer'
import SystemMonitor from './SystemMonitor'
import { usePlayer } from '../contexts/PlayerContext'
import { useAuth } from '../contexts/AuthContext'
import type { UserRole } from '../types'
import { S54 } from '../assets/graphics'

interface NavItem {
  to: string
  iconSrc: string
  label: string
  minRole?: 'director' | 'dj'
}

const navItems: NavItem[] = [
  { to: '/dashboard', iconSrc: S54.nav.statistics, label: 'Dashboard', minRole: 'dj' },
  { to: '/disco-lounge', iconSrc: S54.nav.discoLounge, label: 'Disco Lounge' },
  { to: '/reading-room', iconSrc: S54.nav.readingRoom, label: 'Reading Room' },
  { to: '/listen', iconSrc: S54.nav.listenAdd, label: 'Listen' },
  { to: '/albums', iconSrc: S54.nav.albums, label: 'Albums' },
  { to: '/file-management', iconSrc: S54.nav.fileManagement, label: 'File Management', minRole: 'dj' },
  { to: '/playlists', iconSrc: S54.nav.playlists, label: 'Playlists' },
  { to: '/sound-booth', iconSrc: S54.nav.soundBooth, label: 'Sound Booth' },
  { to: '/dj-requests', iconSrc: S54.nav.djRequest, label: 'DJ Requests' },
  { to: '/calendar', iconSrc: S54.nav.calendar, label: 'Calendar' },
  { to: '/activity', iconSrc: S54.nav.activity, label: 'Activity', minRole: 'dj' },
  { to: '/settings', iconSrc: S54.nav.settings, label: 'Settings', minRole: 'director' },
  { to: '/how-to', iconSrc: S54.nav.howTo, label: 'How To' },
]

const ROLE_LABELS: Record<UserRole, string> = {
  director: 'Club Director',
  dj: 'DJ',
  partygoer: 'Partygoer',
}

const ROLE_COLORS: Record<UserRole, string> = {
  director: 'bg-[#FF8C00]/20 text-[#FF8C00]',
  dj: 'bg-[#FF1493]/20 text-[#FF1493]',
  partygoer: 'bg-green-500/20 text-green-400',
}

function Layout() {
  const { state: playerState, isPopOutOpen } = usePlayer()
  const { user, logout, isDirector, isDjOrAbove } = useAuth()
  const navigate = useNavigate()
  const hasPlayer = !!playerState.currentTrack
  const [showAbout, setShowAbout] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const filteredNavItems = navItems.filter((item) => {
    if (!item.minRole) return true
    if (item.minRole === 'director') return isDirector
    if (item.minRole === 'dj') return isDjOrAbove
    return true
  })

  return (
    <div className="flex h-screen bg-gray-100 dark:bg-[#0D1117]">
      <Toaster position="top-right" />

      {/* Mobile Top Bar */}
      <div className="fixed top-0 left-0 right-0 h-14 bg-white dark:bg-[#161B22] border-b border-gray-200 dark:border-[#30363D] z-30 flex items-center px-4 md:hidden">
        <button
          onClick={() => setSidebarOpen(true)}
          className="p-2 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-[#30363D] rounded-lg"
        >
          <img src={S54.menu} alt="Menu" className="w-5 h-5 object-contain" />
        </button>
        <div className="flex items-center ml-3">
          <img src={S54.logo} alt="Studio54" className="h-8 mr-2 object-contain" />
          <span className="text-lg font-bold text-gray-900 dark:text-white">Studio54</span>
        </div>
      </div>

      {/* Backdrop overlay (mobile only) */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`fixed inset-y-0 left-0 z-40 w-64 bg-white dark:bg-[#161B22] border-r border-gray-200 dark:border-[#30363D] flex flex-col transform transition-transform duration-200 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} md:relative md:translate-x-0 ${hasPlayer && !isPopOutOpen ? 'pb-48 md:pb-36 lg:pb-40 xl:pb-48' : hasPlayer && isPopOutOpen ? 'pb-20' : ''}`}>
        {/* Logo - clickable for About popup */}
        <div className="flex items-center h-24 border-b border-gray-200 dark:border-[#30363D]">
          <button
            onClick={() => setShowAbout(true)}
            className="flex-1 h-full flex items-center px-6 hover:bg-gray-50 dark:hover:bg-[#1C2128] transition-colors text-left"
          >
            <img src={S54.logo} alt="Studio54" className="w-20 h-20 mr-3 flex-shrink-0 object-contain" />
            <div>
              <h1 className="text-xl font-bold text-gray-900 dark:text-white">Studio54</h1>
              <p className="text-xs text-gray-500 dark:text-[#8B949E]">Music Acquisition</p>
            </div>
          </button>
          <button
            onClick={() => setSidebarOpen(false)}
            className="p-2 mr-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 md:hidden"
          >
            <FiX className="w-5 h-5" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-4 py-6 space-y-1 overflow-y-auto sidebar-scroll">
          {filteredNavItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex flex-col items-center px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-[#FF1493]/10 text-[#FF1493] border-l-2 border-[#FF1493]'
                    : 'text-gray-700 dark:text-[#8B949E] hover:bg-gray-100 dark:hover:bg-[#1C2128] hover:text-gray-900 dark:hover:text-[#E6EDF3]'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <img
                    src={item.iconSrc}
                    alt=""
                    className={`w-[125px] h-[125px] object-contain ${isActive ? '' : 'opacity-70'}`}
                  />
                  <span className="mt-1 text-center">{item.label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* User Menu */}
        {user && (
          <div className="px-4 py-3 border-t border-gray-200 dark:border-[#30363D]">
            <div className="flex items-center justify-between">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                  {user.display_name || user.username}
                </p>
                <span className={`inline-block mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold ${ROLE_COLORS[user.role]}`}>
                  {ROLE_LABELS[user.role]}
                </span>
              </div>
              <button
                onClick={handleLogout}
                className="ml-2 p-1.5 text-gray-400 hover:text-red-400 hover:bg-gray-100 dark:hover:bg-[#1C2128] rounded transition-colors"
                title="Sign out"
              >
                <FiLogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* System Monitor - admin only */}
        {isDirector && <SystemMonitor />}

        {/* Page Content */}
        <main className={`flex-1 overflow-y-auto bg-gray-50 dark:bg-[#0D1117] p-4 md:px-6 md:py-6 pt-[calc(1rem+3.5rem)] md:pt-6 ${hasPlayer && !isPopOutOpen ? 'pb-48 md:pb-36 lg:pb-40 xl:pb-48' : hasPlayer && isPopOutOpen ? 'pb-20' : ''}`}>
          <Outlet />
        </main>
      </div>

      {/* Persistent Player */}
      <PersistentPlayer />

      {/* About / Version Popup */}
      {showAbout && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowAbout(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-xl shadow-2xl max-w-sm w-full mx-4 border dark:border-[#30363D]" onClick={e => e.stopPropagation()}>
            <div className="p-6 text-center">
              <div className="w-20 h-20 mx-auto mb-4">
                <img src={S54.logo} alt="Studio54" className="w-full h-full object-contain" />
              </div>
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">{APP_NAME}</h2>
              <p className="text-sm text-gray-500 dark:text-[#8B949E] mt-1">{APP_DESCRIPTION}</p>
              <div className="mt-4 inline-block bg-gray-100 dark:bg-[#0D1117] rounded-lg px-4 py-2">
                <span className="text-xs text-gray-500 dark:text-[#8B949E]">Version</span>
                <p className="text-lg font-mono font-bold text-[#FF1493]">v{APP_VERSION}</p>
              </div>
              <div className="mt-4 text-left">
                <p className="text-xs font-semibold text-gray-500 dark:text-[#8B949E] mb-2">What's New</p>
                <ul className="text-xs text-gray-500 dark:text-[#8B949E] space-y-1 list-disc list-inside">
                  <li>User authentication with role-based access control</li>
                  <li>Three roles: Club Director, DJ, Partygoer</li>
                  <li>Sync All Albums — bulk backfill missing tracks from MusicBrainz</li>
                  <li>Link Files re-sync — auto-backfills zero-track albums during linking</li>
                  <li>Unorganized Files tab — view/sort files not yet organized</li>
                  <li>Sortable columns on Unlinked & Unorganized tables</li>
                  <li>MBID Resolution — search local MBDB & bulk resolve artist MBIDs</li>
                  <li>System monitor bar, scan log viewer, auto-import pipeline</li>
                  <li>Queue status monitoring & Celery architecture overhaul</li>
                </ul>
              </div>
              <div className="mt-4 pt-4 border-t border-gray-200 dark:border-[#30363D] space-y-1 text-xs text-gray-400 dark:text-[#8B949E]">
                <p>Music acquisition, library management, and playback</p>
                <p>Built with React, FastAPI, and Celery</p>
              </div>
            </div>
            <div className="px-6 pb-4">
              <button
                onClick={() => setShowAbout(false)}
                className="w-full py-2 px-4 bg-gray-100 dark:bg-[#0D1117] text-gray-700 dark:text-[#E6EDF3] rounded-lg hover:bg-gray-200 dark:hover:bg-[#30363D] transition-colors text-sm font-medium"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Layout
