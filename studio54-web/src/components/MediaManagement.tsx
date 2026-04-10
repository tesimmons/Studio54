/**
 * Media Management Settings Component
 * Lidarr-inspired file organization and naming configuration
 */

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { FiSave, FiFolder, FiHelpCircle } from 'react-icons/fi'
import { settingsApi, authFetch } from '../api/client'
import DirectoryBrowser from './DirectoryBrowser'
import RootFoldersSettings from './RootFoldersSettings'

interface MediaManagementConfig {
  id: string
  // File naming templates
  artist_folder_template: string
  album_folder_template: string
  track_file_template: string
  multi_disc_track_template: string
  colon_replacement: string

  // File organization
  music_library_path: string
  rename_tracks: boolean
  replace_existing_files: boolean
  use_hardlinks: boolean

  // Recycle bin
  recycle_bin_path: string | null
  recycle_bin_cleanup_days: number
  auto_cleanup_recycle_bin: boolean

  // Import behavior
  minimum_file_size_mb: number
  skip_free_space_check: boolean
  minimum_free_space_mb: number
  sabnzbd_download_path: string | null
  import_extra_files: boolean
  extra_file_extensions: string

  // Folder management
  create_empty_artist_folders: boolean
  delete_empty_folders: boolean
  create_folders_on_monitor: boolean

  // Unix permissions
  set_permissions_linux: boolean
  chmod_folder: string | null
  chmod_file: string | null
  chown_group: string | null

  // Quality preferences
  upgrade_allowed: boolean
  prefer_lossless: boolean
  minimum_quality_score: number
}

interface NamingTemplate {
  name: string
  artist_folder: string
  album_folder: string
  track_file: string
  description: string
}

const ALL_ALBUM_TYPES = ['Album', 'EP', 'Single', 'Compilation', 'Live', 'Soundtrack', 'Audiobook']

function AlbumTypeFilterSettings() {
  const [enabledTypes, setEnabledTypes] = useState<string[]>(ALL_ALBUM_TYPES)
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    settingsApi.getAlbumTypeFilters().then(res => {
      setEnabledTypes(res.enabled_types)
      setLoaded(true)
    }).catch(() => setLoaded(true))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      await settingsApi.updateAlbumTypeFilters(enabledTypes)
      toast.success('Album type filters saved')
    } catch {
      toast.error('Failed to save album type filters')
    }
    setSaving(false)
  }

  const toggleType = (type: string) => {
    setEnabledTypes(prev =>
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    )
  }

  if (!loaded) return null

  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white">Album Type Filters</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Default album types to display on artist pages
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="btn btn-primary text-sm"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {ALL_ALBUM_TYPES.map(type => (
          <label key={type} className="flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={enabledTypes.includes(type)}
              onChange={() => toggleType(type)}
              className="checkbox"
            />
            <span className="ml-2 text-sm text-gray-900 dark:text-white">{type}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

export default function MediaManagement() {
  const queryClient = useQueryClient()
  const [activeSection, setActiveSection] = useState<'libraries' | 'naming' | 'organization' | 'quality' | 'root-folders'>('libraries')

  // Fetch current configuration
  const { data: config, isLoading } = useQuery<MediaManagementConfig>({
    queryKey: ['mediaManagement'],
    queryFn: async () => {
      const response = await authFetch('/api/v1/media-management')
      if (!response.ok) throw new Error('Failed to fetch media management settings')
      return response.json()
    },
  })

  // Fetch predefined templates
  const { data: templates } = useQuery<{ templates: Record<string, NamingTemplate> }>({
    queryKey: ['namingTemplates'],
    queryFn: async () => {
      const response = await authFetch('/api/v1/media-management/naming-templates')
      if (!response.ok) throw new Error('Failed to fetch naming templates')
      return response.json()
    },
  })

  // Form state
  const [formData, setFormData] = useState<Partial<MediaManagementConfig>>({})

  // Directory browser state
  const [musicLibraryBrowserOpen, setMusicLibraryBrowserOpen] = useState(false)
  const [sabnzbdBrowserOpen, setSabnzbdBrowserOpen] = useState(false)

  // Update form data when config loads
  useState(() => {
    if (config) {
      setFormData(config)
    }
  })

  // Update configuration mutation
  const updateMutation = useMutation({
    mutationFn: async (updates: Partial<MediaManagementConfig>) => {
      const response = await authFetch('/api/v1/media-management', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to update settings')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mediaManagement'] })
      toast.success('Settings saved successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to save settings: ${error.message}`)
    },
  })

  // Validate template
  const validateTemplate = async (template: string) => {
    try {
      const response = await authFetch('/api/v1/media-management/validate-template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template }),
      })
      const result = await response.json()
      if (result.is_valid) {
        toast.success('Template is valid')
      } else {
        toast.error(`Invalid template: ${result.error}`)
      }
    } catch (error) {
      toast.error('Failed to validate template')
    }
  }

  // Apply template preset
  const applyTemplate = (template: NamingTemplate) => {
    setFormData({
      ...formData,
      artist_folder_template: template.artist_folder,
      album_folder_template: template.album_folder,
      track_file_template: template.track_file,
    })
    toast.success(`Applied ${template.name} template`)
  }

  // Handle save
  const handleSave = () => {
    updateMutation.mutate(formData)
  }

  if (isLoading || !config) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
      </div>
    )
  }

  const currentFormData = { ...config, ...formData }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Media Management</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
            Configure file organization, naming conventions, and import behavior
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={updateMutation.isPending}
          className="btn btn-primary"
        >
          {updateMutation.isPending ? (
            <>
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2" />
              Saving...
            </>
          ) : (
            <>
              <FiSave className="w-4 h-4 mr-2" />
              Save Changes
            </>
          )}
        </button>
      </div>

      {/* Section Navigation */}
      <div className="border-b border-gray-200 dark:border-[#30363D]">
        <nav className="-mb-px flex space-x-8 overflow-x-auto">
          <button
            onClick={() => setActiveSection('libraries')}
            className={`py-2 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
              activeSection === 'libraries'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Libraries
          </button>
          <button
            onClick={() => setActiveSection('naming')}
            className={`py-2 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
              activeSection === 'naming'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            File Naming
          </button>
          <button
            onClick={() => setActiveSection('organization')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeSection === 'organization'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            File Organization
          </button>
          <button
            onClick={() => setActiveSection('quality')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeSection === 'quality'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Quality & Import
          </button>
          <button
            onClick={() => setActiveSection('root-folders')}
            className={`py-2 px-1 border-b-2 font-medium text-sm ${
              activeSection === 'root-folders'
                ? 'border-[#FF1493] text-[#FF1493]'
                : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'
            }`}
          >
            Root Folders
          </button>
        </nav>
      </div>

      {/* Section Content */}
      <div>
        {/* Libraries Section */}
        {activeSection === 'libraries' && (
          <div className="space-y-6">
            <RootFoldersSettings />
          </div>
        )}

        {/* File Naming Section */}
        {activeSection === 'naming' && (
          <div className="space-y-6">
            {/* Template Presets */}
            {templates && (
              <div className="card p-4">
                <h3 className="font-semibold text-gray-900 dark:text-white mb-3">Template Presets</h3>
                <div className="grid grid-cols-2 gap-3">
                  {Object.values(templates.templates).map((template) => (
                    <button
                      key={template.name}
                      onClick={() => applyTemplate(template)}
                      className="text-left p-3 border border-gray-300 dark:border-[#30363D] rounded-lg hover:border-[#FF1493] dark:hover:border-[#FF1493] hover:bg-[#FF1493]/5 dark:hover:bg-[#FF1493]/10 transition-colors"
                    >
                      <div className="font-medium text-gray-900 dark:text-white">{template.name}</div>
                      <div className="text-xs text-gray-600 dark:text-gray-400 mt-1">{template.description}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Artist Folder Template */}
            <div className="card p-4">
              <label className="block font-medium text-gray-900 dark:text-white mb-2">
                Artist Folder
              </label>
              <input
                type="text"
                value={currentFormData.artist_folder_template}
                onChange={(e) => setFormData({ ...formData, artist_folder_template: e.target.value })}
                onBlur={(e) => validateTemplate(e.target.value)}
                className="input w-full"
                placeholder="{Artist Name}"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Example: Pink Floyd
              </p>
            </div>

            {/* Album Folder Template */}
            <div className="card p-4">
              <label className="block font-medium text-gray-900 dark:text-white mb-2">
                Album Folder
              </label>
              <input
                type="text"
                value={currentFormData.album_folder_template}
                onChange={(e) => setFormData({ ...formData, album_folder_template: e.target.value })}
                onBlur={(e) => validateTemplate(e.target.value)}
                className="input w-full"
                placeholder="{Album Title} ({Release Year})"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Example: Dark Side of the Moon (1973)
              </p>
            </div>

            {/* Track File Template */}
            <div className="card p-4">
              <label className="block font-medium text-gray-900 dark:text-white mb-2">
                Track File
              </label>
              <input
                type="text"
                value={currentFormData.track_file_template}
                onChange={(e) => setFormData({ ...formData, track_file_template: e.target.value })}
                onBlur={(e) => validateTemplate(e.target.value)}
                className="input w-full"
                placeholder="{Artist Name} - {Album Title} - {track:00} - {Track Title}"
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Example: Pink Floyd - Dark Side of the Moon - 01 - Speak to Me.flac
              </p>
            </div>

            {/* Tokens Reference */}
            <div className="card p-4 bg-blue-50 dark:bg-blue-900/20">
              <div className="flex items-start">
                <FiHelpCircle className="w-5 h-5 text-blue-600 dark:text-blue-400 mr-2 flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="font-medium text-blue-900 dark:text-blue-100 mb-2">Available Tokens</h4>
                  <div className="text-sm text-blue-800 dark:text-blue-200 space-y-1">
                    <div><code className="px-1 bg-blue-100 dark:bg-blue-800 rounded">{'{Artist Name}'}</code>, <code className="px-1 bg-blue-100 dark:bg-blue-800 rounded">{'{Album Title}'}</code>, <code className="px-1 bg-blue-100 dark:bg-blue-800 rounded">{'{Track Title}'}</code></div>
                    <div><code className="px-1 bg-blue-100 dark:bg-blue-800 rounded">{'{track:00}'}</code> (zero-padded), <code className="px-1 bg-blue-100 dark:bg-blue-800 rounded">{'{disc:0}'}</code>, <code className="px-1 bg-blue-100 dark:bg-blue-800 rounded">{'{Release Year}'}</code></div>
                    <div><code className="px-1 bg-blue-100 dark:bg-blue-800 rounded">{'{Quality Title}'}</code>, <code className="px-1 bg-blue-100 dark:bg-blue-800 rounded">{'{Album Type}'}</code></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* File Organization Section */}
        {activeSection === 'organization' && (
          <div className="space-y-6">
            {/* Music Library Path */}
            <div className="card p-4">
              <label className="block font-medium text-gray-900 dark:text-white mb-2">
                Music Library Path
              </label>
              <div className="flex space-x-2">
                <input
                  type="text"
                  value={currentFormData.music_library_path}
                  onChange={(e) => setFormData({ ...formData, music_library_path: e.target.value })}
                  className="input flex-1"
                  placeholder="/music"
                />
                <button
                  onClick={() => setMusicLibraryBrowserOpen(true)}
                  className="btn btn-secondary"
                  type="button"
                >
                  <FiFolder className="w-4 h-4" />
                </button>
              </div>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Root directory for organized music files
              </p>
            </div>

            {/* File Operations */}
            <div className="card p-4 space-y-4">
              <h3 className="font-semibold text-gray-900 dark:text-white">File Operations</h3>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.rename_tracks}
                  onChange={(e) => setFormData({ ...formData, rename_tracks: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Rename tracks after import</span>
              </label>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.replace_existing_files}
                  onChange={(e) => setFormData({ ...formData, replace_existing_files: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Replace existing files (allow upgrades)</span>
              </label>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.use_hardlinks}
                  onChange={(e) => setFormData({ ...formData, use_hardlinks: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Use hardlinks (saves disk space)</span>
              </label>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.delete_empty_folders}
                  onChange={(e) => setFormData({ ...formData, delete_empty_folders: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Delete empty folders after cleanup</span>
              </label>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.create_folders_on_monitor}
                  onChange={(e) => setFormData({ ...formData, create_folders_on_monitor: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Create empty folders when artist/album is monitored or searched</span>
              </label>
            </div>

            {/* Recycle Bin */}
            <div className="card p-4 space-y-4">
              <h3 className="font-semibold text-gray-900 dark:text-white">Recycle Bin</h3>

              <div>
                <label className="block font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Recycle Bin Path (leave empty to permanently delete)
                </label>
                <input
                  type="text"
                  value={currentFormData.recycle_bin_path || ''}
                  onChange={(e) => setFormData({ ...formData, recycle_bin_path: e.target.value || null })}
                  className="input w-full"
                  placeholder="/docker/studio54/recycle-bin"
                />
              </div>

              <div>
                <label className="block font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Cleanup after (days)
                </label>
                <input
                  type="number"
                  value={currentFormData.recycle_bin_cleanup_days}
                  onChange={(e) => setFormData({ ...formData, recycle_bin_cleanup_days: parseInt(e.target.value) })}
                  className="input w-32"
                  min="1"
                  max="365"
                />
              </div>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.auto_cleanup_recycle_bin}
                  onChange={(e) => setFormData({ ...formData, auto_cleanup_recycle_bin: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Auto-cleanup old files</span>
              </label>
            </div>
          </div>
        )}

        {/* Quality & Import Section */}
        {activeSection === 'quality' && (
          <div className="space-y-6">
            {/* Album Type Filters */}
            <AlbumTypeFilterSettings />

            {/* Quality Preferences */}
            <div className="card p-4 space-y-4">
              <h3 className="font-semibold text-gray-900 dark:text-white">Quality Preferences</h3>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.upgrade_allowed}
                  onChange={(e) => setFormData({ ...formData, upgrade_allowed: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Allow quality upgrades</span>
              </label>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.prefer_lossless}
                  onChange={(e) => setFormData({ ...formData, prefer_lossless: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Prefer lossless formats (FLAC, ALAC)</span>
              </label>

              <div>
                <label className="block font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Minimum Quality Score (0-500)
                </label>
                <input
                  type="number"
                  value={currentFormData.minimum_quality_score}
                  onChange={(e) => setFormData({ ...formData, minimum_quality_score: parseInt(e.target.value) })}
                  className="input w-32"
                  min="0"
                  max="500"
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  128 = MP3 128kbps, 320 = MP3 320kbps, 400 = FLAC, 500 = FLAC 24-bit
                </p>
              </div>
            </div>

            {/* Import Settings */}
            <div className="card p-4 space-y-4">
              <h3 className="font-semibold text-gray-900 dark:text-white">Import Settings</h3>

              <div>
                <label className="block font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Minimum File Size (MB)
                </label>
                <input
                  type="number"
                  value={currentFormData.minimum_file_size_mb}
                  onChange={(e) => setFormData({ ...formData, minimum_file_size_mb: parseInt(e.target.value) })}
                  className="input w-32"
                  min="0"
                />
              </div>

              <div>
                <label className="block font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Minimum Free Space (MB)
                </label>
                <input
                  type="number"
                  value={currentFormData.minimum_free_space_mb}
                  onChange={(e) => setFormData({ ...formData, minimum_free_space_mb: parseInt(e.target.value) })}
                  className="input w-32"
                  min="0"
                />
              </div>

              <div>
                <label className="block font-medium text-gray-700 dark:text-gray-300 mb-2">
                  SABnzbd Download Directory (optional)
                </label>
                <div className="flex space-x-2">
                  <input
                    type="text"
                    value={currentFormData.sabnzbd_download_path || ''}
                    onChange={(e) => setFormData({ ...formData, sabnzbd_download_path: e.target.value || null })}
                    className="input flex-1"
                    placeholder="/docker/sabnzbd/downloads/complete"
                  />
                  <button
                    onClick={() => setSabnzbdBrowserOpen(true)}
                    className="btn btn-secondary"
                    type="button"
                  >
                    <FiFolder className="w-4 h-4" />
                  </button>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Override SABnzbd's reported download path (useful for Docker path mapping)
                </p>
              </div>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.skip_free_space_check}
                  onChange={(e) => setFormData({ ...formData, skip_free_space_check: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Skip free space check</span>
              </label>

              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={currentFormData.import_extra_files}
                  onChange={(e) => setFormData({ ...formData, import_extra_files: e.target.checked })}
                  className="checkbox"
                />
                <span className="ml-2 text-gray-900 dark:text-white">Import extra files (covers, lyrics, etc.)</span>
              </label>

              {currentFormData.import_extra_files && (
                <div>
                  <label className="block font-medium text-gray-700 dark:text-gray-300 mb-2">
                    Extra File Extensions (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={currentFormData.extra_file_extensions}
                    onChange={(e) => setFormData({ ...formData, extra_file_extensions: e.target.value })}
                    className="input w-full"
                    placeholder="jpg,png,jpeg,lrc,txt,pdf,log,cue"
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Root Folders Section */}
        {activeSection === 'root-folders' && (
          <RootFoldersSettings />
        )}
      </div>

      {/* Directory Browser Modals */}
      <DirectoryBrowser
        isOpen={musicLibraryBrowserOpen}
        onClose={() => setMusicLibraryBrowserOpen(false)}
        onSelect={(path) => {
          setFormData({ ...formData, music_library_path: path })
          setMusicLibraryBrowserOpen(false)
        }}
        initialPath={currentFormData.music_library_path || '/music'}
        title="Select Music Library Path"
      />

      <DirectoryBrowser
        isOpen={sabnzbdBrowserOpen}
        onClose={() => setSabnzbdBrowserOpen(false)}
        onSelect={(path) => {
          setFormData({ ...formData, sabnzbd_download_path: path })
          setSabnzbdBrowserOpen(false)
        }}
        initialPath={currentFormData.sabnzbd_download_path || '/mnt'}
        title="Select SABnzbd Download Directory"
      />
    </div>
  )
}
