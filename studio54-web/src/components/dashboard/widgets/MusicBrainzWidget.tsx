import { useQuery } from '@tanstack/react-query'
import { FiDatabase } from 'react-icons/fi'
import { systemApi } from '../../../api/client'

interface StatisticsData {
  library: {
    total_files: number
    musicbrainz_coverage: {
      tracks_tagged: number
      albums_tagged: number
      files_linked: number
      coverage_percent: number
    }
  }
}

export default function MusicBrainzWidget({ libraryType }: { widgetId: string; isEditMode: boolean; libraryType?: 'music' | 'audiobook' }) {
  const { data: stats } = useQuery<StatisticsData>({
    queryKey: ['statistics', libraryType],
    queryFn: () => systemApi.getStatistics(libraryType),
    refetchInterval: 60000,
  })

  const coverage = stats?.library.musicbrainz_coverage
  const totalFiles = stats?.library.total_files || 0

  return (
    <div className="h-full p-4 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">
        <FiDatabase className="inline w-5 h-5 mr-2 -mt-0.5" />
        MusicBrainz Coverage
      </h2>
      {coverage ? (
        <div className="flex-1 space-y-3 overflow-y-auto">
          <div>
            <div className="flex justify-between text-sm mb-1">
              <span className="text-gray-600 dark:text-gray-400">Track MBID Coverage</span>
              <span className="font-medium text-gray-900 dark:text-white">{coverage.coverage_percent}%</span>
            </div>
            <div className="h-3 bg-gray-200 dark:bg-[#0D1117] rounded-full overflow-hidden">
              <div className="h-full bg-[#FF1493]/50 rounded-full transition-all duration-500" style={{ width: `${coverage.coverage_percent}%` }} />
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {coverage.tracks_tagged.toLocaleString()} of {totalFiles.toLocaleString()} files tagged
            </p>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-gray-50 dark:bg-[#161B22] rounded-lg p-2">
              <p className="text-xl font-semibold text-gray-900 dark:text-white">{coverage.tracks_tagged.toLocaleString()}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400">Tracks Tagged</p>
            </div>
            <div className="bg-gray-50 dark:bg-[#161B22] rounded-lg p-2">
              <p className="text-xl font-semibold text-gray-900 dark:text-white">{coverage.files_linked.toLocaleString()}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400">Files Linked</p>
            </div>
            <div className="bg-gray-50 dark:bg-[#161B22] rounded-lg p-2">
              <p className="text-xl font-semibold text-gray-900 dark:text-white">{coverage.albums_tagged.toLocaleString()}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400">Albums Tagged</p>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-gray-500 dark:text-gray-400">Loading coverage data...</p>
      )}
    </div>
  )
}
