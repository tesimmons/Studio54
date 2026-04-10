import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { qualityProfilesApi } from '../api/client'
import { FiPlus, FiTrash2, FiX, FiAlertCircle } from 'react-icons/fi'
import type { QualityProfile } from '../types'

const AUDIO_FORMATS = ['FLAC', 'ALAC', 'WAV', 'MP3-320', 'MP3-V0', 'MP3-256', 'MP3-192', 'AAC-256', 'AAC-320', 'OGG-320']

const toggleFormat = (format: string, list: string[], setter: (v: string[]) => void) => {
  if (list.includes(format)) {
    setter(list.filter(f => f !== format))
  } else {
    setter([...list, format])
  }
}

export default function QualityProfilesSettings() {
  const queryClient = useQueryClient()

  const [showAddProfileModal, setShowAddProfileModal] = useState(false)
  const [profileName, setProfileName] = useState('')
  const [profileAllowedFormats, setProfileAllowedFormats] = useState<string[]>([])
  const [profilePreferredFormats, setProfilePreferredFormats] = useState<string[]>([])
  const [profileMinBitrate, setProfileMinBitrate] = useState<number | ''>('')
  const [profileMaxSizeMb, setProfileMaxSizeMb] = useState<number | ''>('')
  const [profileUpgradeEnabled, setProfileUpgradeEnabled] = useState(false)
  const [profileUpgradeUntilQuality, setProfileUpgradeUntilQuality] = useState('')
  const [profileIsDefault, setProfileIsDefault] = useState(false)

  const resetProfileForm = () => {
    setProfileName(''); setProfileAllowedFormats([]); setProfilePreferredFormats([])
    setProfileMinBitrate(''); setProfileMaxSizeMb(''); setProfileUpgradeEnabled(false)
    setProfileUpgradeUntilQuality(''); setProfileIsDefault(false)
  }

  const { data: qualityProfiles, isLoading: qualityProfilesLoading } = useQuery<QualityProfile[]>({
    queryKey: ['qualityProfiles'],
    queryFn: () => qualityProfilesApi.list(),
  })

  const addProfileMutation = useMutation({
    mutationFn: () => qualityProfilesApi.create({
      name: profileName,
      allowed_formats: profileAllowedFormats,
      preferred_formats: profilePreferredFormats,
      min_bitrate: profileMinBitrate === '' ? null : profileMinBitrate,
      max_size_mb: profileMaxSizeMb === '' ? null : profileMaxSizeMb,
      upgrade_enabled: profileUpgradeEnabled,
      upgrade_until_quality: profileUpgradeUntilQuality || null,
      is_default: profileIsDefault,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['qualityProfiles'] })
      setShowAddProfileModal(false)
      resetProfileForm()
      toast.success('Quality profile created')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to create quality profile'),
  })

  const deleteProfileMutation = useMutation({
    mutationFn: (id: string) => qualityProfilesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['qualityProfiles'] })
      toast.success('Quality profile deleted')
    },
    onError: (error: any) => toast.error(error.response?.data?.detail || 'Failed to delete quality profile'),
  })

  return (
    <>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">Quality Profiles</h2>
          <button className="btn btn-primary" onClick={() => setShowAddProfileModal(true)}>
            <FiPlus className="w-4 h-4 mr-2" />
            Add Profile
          </button>
        </div>

        {qualityProfilesLoading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
          </div>
        ) : qualityProfiles && qualityProfiles.length > 0 ? (
          <div className="space-y-3">
            {qualityProfiles.map((profile) => (
              <div key={profile.id} className="card p-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center space-x-3">
                      <h3 className="font-semibold text-gray-900 dark:text-white">{profile.name}</h3>
                      {profile.is_default && <span className="badge badge-primary">Default</span>}
                      {profile.upgrade_enabled && <span className="badge badge-success">Upgrades</span>}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {profile.allowed_formats.map((format) => (
                        <span
                          key={format}
                          className={`px-2 py-0.5 text-xs rounded-full ${
                            profile.preferred_formats.includes(format)
                              ? 'bg-[#FF1493]/10 dark:bg-[#FF1493]/15 text-[#d10f7a] dark:text-[#ff8cb8] font-medium'
                              : 'bg-gray-100 dark:bg-[#0D1117] text-gray-600 dark:text-gray-400'
                          }`}
                        >
                          {format}
                        </span>
                      ))}
                    </div>
                    <div className="mt-2 text-xs text-gray-500 dark:text-gray-400 space-x-4">
                      {profile.min_bitrate && <span>Min: {profile.min_bitrate} kbps</span>}
                      {profile.max_size_mb && <span>Max: {profile.max_size_mb} MB</span>}
                      {profile.upgrade_until_quality && <span>Upgrade to: {profile.upgrade_until_quality}</span>}
                    </div>
                  </div>
                  <button
                    onClick={() => { if (confirm(`Delete quality profile "${profile.name}"?`)) deleteProfileMutation.mutate(profile.id) }}
                    className="btn btn-sm btn-danger"
                    disabled={deleteProfileMutation.isPending}
                  >
                    <FiTrash2 className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="card p-12 text-center">
            <FiAlertCircle className="w-12 h-12 text-gray-400 mx-auto mb-3" />
            <p className="text-gray-500 dark:text-gray-400">No quality profiles found. They will be auto-created on first load.</p>
          </div>
        )}
      </div>

      {/* Add Quality Profile Modal */}
      {showAddProfileModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={() => setShowAddProfileModal(false)}>
          <div className="bg-white dark:bg-[#161B22] rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-[#30363D]">
              <h2 className="text-2xl font-bold text-gray-900 dark:text-white">Add Quality Profile</h2>
              <button onClick={() => setShowAddProfileModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"><FiX className="w-6 h-6" /></button>
            </div>
            <div className="p-6 space-y-4 overflow-y-auto max-h-[60vh]">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Name</label>
                <input type="text" className="input w-full" value={profileName} onChange={(e) => setProfileName(e.target.value)} placeholder="My Profile" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Allowed Formats (click to toggle)</label>
                <div className="flex flex-wrap gap-2">
                  {AUDIO_FORMATS.map((format) => (
                    <button
                      key={format}
                      className={`px-3 py-1 rounded-full text-sm transition-colors ${
                        profileAllowedFormats.includes(format)
                          ? 'bg-[#FF1493] text-white'
                          : 'bg-gray-200 dark:bg-[#0D1117] text-gray-600 dark:text-gray-400 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                      }`}
                      onClick={() => toggleFormat(format, profileAllowedFormats, setProfileAllowedFormats)}
                    >
                      {format}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Preferred Formats</label>
                <div className="flex flex-wrap gap-2">
                  {profileAllowedFormats.map((format) => (
                    <button
                      key={format}
                      className={`px-3 py-1 rounded-full text-sm transition-colors ${
                        profilePreferredFormats.includes(format)
                          ? 'bg-green-600 text-white'
                          : 'bg-gray-200 dark:bg-[#0D1117] text-gray-600 dark:text-gray-400 hover:bg-gray-300 dark:hover:bg-[#30363D]'
                      }`}
                      onClick={() => toggleFormat(format, profilePreferredFormats, setProfilePreferredFormats)}
                    >
                      {format}
                    </button>
                  ))}
                  {profileAllowedFormats.length === 0 && (
                    <span className="text-sm text-gray-500 dark:text-gray-400">Select allowed formats first</span>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Min Bitrate (kbps)</label>
                  <input type="number" className="input w-full" value={profileMinBitrate} onChange={(e) => setProfileMinBitrate(e.target.value === '' ? '' : parseInt(e.target.value))} placeholder="Optional" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Max Size (MB)</label>
                  <input type="number" className="input w-full" value={profileMaxSizeMb} onChange={(e) => setProfileMaxSizeMb(e.target.value === '' ? '' : parseInt(e.target.value))} placeholder="Optional" />
                </div>
              </div>
              <div className="flex items-center space-x-6">
                <div className="flex items-center">
                  <input type="checkbox" id="profile-upgrade" className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4" checked={profileUpgradeEnabled} onChange={(e) => setProfileUpgradeEnabled(e.target.checked)} />
                  <label htmlFor="profile-upgrade" className="ml-2 text-sm text-gray-700 dark:text-gray-300">Enable upgrades</label>
                </div>
                <div className="flex items-center">
                  <input type="checkbox" id="profile-default" className="rounded text-[#FF1493] focus:ring-[#FF1493] h-4 w-4" checked={profileIsDefault} onChange={(e) => setProfileIsDefault(e.target.checked)} />
                  <label htmlFor="profile-default" className="ml-2 text-sm text-gray-700 dark:text-gray-300">Set as default</label>
                </div>
              </div>
              {profileUpgradeEnabled && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Upgrade Until</label>
                  <select className="input w-full" value={profileUpgradeUntilQuality} onChange={(e) => setProfileUpgradeUntilQuality(e.target.value)}>
                    <option value="">-- Select --</option>
                    {profileAllowedFormats.map((format) => (
                      <option key={format} value={format}>{format}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            <div className="flex items-center justify-end p-6 border-t border-gray-200 dark:border-[#30363D] space-x-3">
              <button onClick={() => { setShowAddProfileModal(false); resetProfileForm() }} className="btn btn-secondary">Cancel</button>
              <button onClick={() => addProfileMutation.mutate()} className="btn btn-primary" disabled={addProfileMutation.isPending || !profileName || profileAllowedFormats.length === 0}>
                {addProfileMutation.isPending ? 'Creating...' : 'Create Profile'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
