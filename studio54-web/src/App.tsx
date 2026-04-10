import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { PlayerProvider } from './contexts/PlayerContext'
import { AuthProvider } from './contexts/AuthContext'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import ArtistDetail from './pages/ArtistDetail'
import AlbumDetail from './pages/AlbumDetail'
import Albums from './pages/Albums'
import Calendar from './pages/Calendar'
import Activity from './pages/Activity'
import Settings from './pages/Settings'
import Playlists from './pages/Playlists'
import Library from './pages/Library'
import FileManagement from './pages/FileManagement'
import HowTo from './pages/HowTo'
import ListenAdd from './pages/ListenAdd'
import SoundBooth from './pages/SoundBooth'
import DjRequests from './pages/DjRequests'
import ReadingRoom from './pages/ReadingRoom'
import AuthorDetail from './pages/AuthorDetail'
import BookDetail from './pages/BookDetail'
import SeriesDetail from './pages/SeriesDetail'
import PopOutPlayer from './pages/PopOutPlayer'

function App() {
  return (
    <AuthProvider>
      <PlayerProvider>
        <BrowserRouter>
          <Routes>
            {/* Public route */}
            <Route path="/login" element={<Login />} />

            {/* Pop-out player (standalone, no Layout) */}
            <Route path="/player" element={<ProtectedRoute><PopOutPlayer /></ProtectedRoute>} />

            {/* Protected routes */}
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Navigate to="/disco-lounge" replace />} />
              <Route path="dashboard" element={<ProtectedRoute requiredRoles={['director', 'dj']}><Dashboard /></ProtectedRoute>} />

              {/* Disco Lounge (Music Library) */}
              <Route path="disco-lounge" element={<Library />} />
              <Route path="disco-lounge/artists/:id" element={<ArtistDetail />} />
              <Route path="disco-lounge/albums/:id" element={<AlbumDetail />} />

              {/* Reading Room (Audiobook Library) */}
              <Route path="reading-room" element={<ReadingRoom />} />
              <Route path="reading-room/authors/:id" element={<AuthorDetail />} />
              <Route path="reading-room/books/:id" element={<BookDetail />} />
              <Route path="reading-room/series/:id" element={<SeriesDetail />} />

              {/* Legacy redirects */}
              <Route path="artists" element={<Navigate to="/disco-lounge" replace />} />
              <Route path="artists/:id" element={<Navigate to="/disco-lounge" replace />} />
              <Route path="library" element={<Navigate to="/disco-lounge" replace />} />

              <Route path="albums" element={<Albums />} />
              <Route path="albums/:id" element={<AlbumDetail />} />
              <Route path="playlists" element={<Playlists />} />
              <Route path="sound-booth" element={<SoundBooth />} />
              <Route path="dj-requests" element={<DjRequests />} />
              <Route path="library/import" element={<Navigate to="/file-management" replace />} />
              <Route path="file-management" element={<ProtectedRoute requiredRoles={['director', 'dj']}><FileManagement /></ProtectedRoute>} />
              <Route path="calendar" element={<Calendar />} />
              <Route path="statistics" element={<Navigate to="/dashboard" replace />} />
              <Route path="download-history" element={<Navigate to="/activity" replace />} />
              <Route path="download-clients" element={<Navigate to="/settings" replace />} />
              <Route path="activity" element={<ProtectedRoute requiredRoles={['director', 'dj']}><Activity /></ProtectedRoute>} />
              <Route path="queue-status" element={<Navigate to="/activity" replace />} />
              <Route path="settings" element={<ProtectedRoute requiredRoles={['director']}><Settings /></ProtectedRoute>} />
              <Route path="listen" element={<ListenAdd />} />
              <Route path="how-to" element={<HowTo />} />
              <Route path="*" element={<Navigate to="/disco-lounge" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </PlayerProvider>
    </AuthProvider>
  )
}

export default App
