import { useQuery } from '@tanstack/react-query'
import { albumsApi } from '../api/client'
import { format, startOfMonth, endOfMonth } from 'date-fns'

function Calendar() {
  const now = new Date()
  const start = startOfMonth(now)
  const end = endOfMonth(now)

  const { data: releases, isLoading } = useQuery({
    queryKey: ['calendar', start, end],
    queryFn: () => albumsApi.getCalendar(start.toISOString(), end.toISOString()),
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Calendar</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">Upcoming album releases for monitored artists</p>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493]"></div>
        </div>
      ) : releases && releases.length > 0 ? (
        <div className="card p-6">
          <div className="space-y-4">
            {releases.map((release) => (
              <div
                key={release.id}
                className="flex items-center justify-between py-3 border-b border-gray-200 dark:border-[#30363D] last:border-0"
              >
                <div>
                  <p className="font-medium text-gray-900 dark:text-white">{release.title}</p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">{release.artist_name}</p>
                </div>
                <div className="text-right">
                  <p className="font-medium text-gray-900 dark:text-white">
                    {release.release_date && format(new Date(release.release_date), 'MMM dd, yyyy')}
                  </p>
                  <span className="badge badge-info">{release.album_type}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="card p-12 text-center">
          <p className="text-gray-500 dark:text-gray-400">No upcoming releases this month.</p>
        </div>
      )}
    </div>
  )
}

export default Calendar
