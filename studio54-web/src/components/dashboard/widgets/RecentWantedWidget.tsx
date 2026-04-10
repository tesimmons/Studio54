import { useQuery } from '@tanstack/react-query'
import { albumsApi } from '../../../api/client'

export default function RecentWantedWidget() {
  const { data: wantedAlbums } = useQuery({
    queryKey: ['wantedAlbums'],
    queryFn: () => albumsApi.getWanted(10),
    refetchInterval: 60000,
  })

  return (
    <div className="h-full p-4 flex flex-col">
      <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">Recent Wanted Albums</h2>
      {wantedAlbums && wantedAlbums.length > 0 ? (
        <div className="flex-1 overflow-y-auto space-y-0 scrollbar-dark">
          {wantedAlbums.map((album) => (
            <div
              key={album.id}
              className="flex items-center justify-between py-2 border-b border-gray-200 dark:border-[#30363D] last:border-0"
            >
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-900 dark:text-white truncate">{album.title}</p>
                <p className="text-sm text-gray-500 dark:text-gray-400 truncate">{album.artist_name}</p>
              </div>
              <div className="text-right flex-shrink-0 ml-3">
                <span className="badge badge-warning">{album.status}</span>
                {album.release_date && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                    {new Date(album.release_date).getFullYear()}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-gray-500 dark:text-gray-400">No wanted albums</p>
      )}
    </div>
  )
}
