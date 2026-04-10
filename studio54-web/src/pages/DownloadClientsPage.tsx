import { useState } from 'react'
import { Toaster } from 'react-hot-toast'
import DownloadClientsSettings from '../components/DownloadClientsSettings'
import IndexersSettings from '../components/IndexersSettings'
import QualityProfilesSettings from '../components/QualityProfilesSettings'

type Tab = 'download-clients' | 'indexers' | 'quality-profiles'

export default function DownloadClientsPage() {
  const [activeTab, setActiveTab] = useState<Tab>('download-clients')

  return (
    <div className="space-y-6">
      <Toaster position="top-right" />

      <div>
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Download Clients</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">Configure download clients, indexers, and quality profiles</p>
      </div>

      <div className="border-b border-gray-200 dark:border-[#30363D] overflow-x-auto">
        <nav className="-mb-px flex flex-nowrap space-x-8">
          {([
            { key: 'download-clients' as Tab, label: 'Download Clients' },
            { key: 'indexers' as Tab, label: 'Indexers' },
            { key: 'quality-profiles' as Tab, label: 'Quality Profiles' },
          ]).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap ${
                activeTab === key
                  ? 'border-[#FF1493] text-[#FF1493]'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </div>

      <div>
        {activeTab === 'download-clients' && <DownloadClientsSettings />}
        {activeTab === 'indexers' && <IndexersSettings />}
        {activeTab === 'quality-profiles' && <QualityProfilesSettings />}
      </div>
    </div>
  )
}
