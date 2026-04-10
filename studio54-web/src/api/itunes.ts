// iTunes Search API helper for 30-second song previews
// Written by Halon

interface ItunesResult {
  preview_url: string
  itunes_track_name: string
  itunes_artist_name: string
  artwork_url: string
}

// Simple in-memory cache
const cache = new Map<string, ItunesResult | null>()

function normalizeForComparison(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, '')
}

function similarity(a: string, b: string): number {
  const na = normalizeForComparison(a)
  const nb = normalizeForComparison(b)
  if (na === nb) return 1
  if (na.includes(nb) || nb.includes(na)) return 0.8
  // Simple character overlap ratio
  const longer = na.length > nb.length ? na : nb
  const shorter = na.length > nb.length ? nb : na
  if (longer.length === 0) return 0
  let matches = 0
  const longerChars = longer.split('')
  const shorterChars = shorter.split('')
  for (const c of shorterChars) {
    const idx = longerChars.indexOf(c)
    if (idx >= 0) {
      matches++
      longerChars.splice(idx, 1)
    }
  }
  return matches / longer.length
}

export async function searchPreview(
  artist: string,
  track: string
): Promise<ItunesResult | null> {
  const cacheKey = `${artist}::${track}`
  if (cache.has(cacheKey)) {
    return cache.get(cacheKey)!
  }

  try {
    const term = encodeURIComponent(`${artist} ${track}`)
    const response = await fetch(
      `https://itunes.apple.com/search?term=${term}&entity=song&limit=5`
    )
    if (!response.ok) return null

    const data = await response.json()
    if (!data.results || data.results.length === 0) {
      cache.set(cacheKey, null)
      return null
    }

    // Find best match by comparing track name similarity
    let bestMatch = data.results[0]
    let bestScore = 0

    for (const result of data.results) {
      const trackScore = similarity(track, result.trackName || '')
      const artistScore = similarity(artist, result.artistName || '')
      const combinedScore = trackScore * 0.7 + artistScore * 0.3
      if (combinedScore > bestScore) {
        bestScore = combinedScore
        bestMatch = result
      }
    }

    // Require minimum match quality
    if (bestScore < 0.3) {
      cache.set(cacheKey, null)
      return null
    }

    const result: ItunesResult = {
      preview_url: bestMatch.previewUrl,
      itunes_track_name: bestMatch.trackName,
      itunes_artist_name: bestMatch.artistName,
      artwork_url: bestMatch.artworkUrl100 || bestMatch.artworkUrl60 || '',
    }

    cache.set(cacheKey, result)
    return result
  } catch {
    cache.set(cacheKey, null)
    return null
  }
}

export { type ItunesResult }

const topTracksCache = new Map<string, ItunesResult[]>()

/**
 * Search iTunes for an artist's top tracks (for preview playback).
 * Returns deduplicated results by normalized track name.
 */
export async function searchArtistTopTracks(
  artistName: string,
  limit = 2
): Promise<ItunesResult[]> {
  const cacheKey = `top::${artistName}::${limit}`
  if (topTracksCache.has(cacheKey)) {
    return topTracksCache.get(cacheKey)!
  }

  try {
    const term = encodeURIComponent(artistName)
    const response = await fetch(
      `https://itunes.apple.com/search?term=${term}&entity=song&limit=15`
    )
    if (!response.ok) return []

    const data = await response.json()
    if (!data.results || data.results.length === 0) {
      topTracksCache.set(cacheKey, [])
      return []
    }

    // Filter to results matching artist name, deduplicate by track name
    const seen = new Set<string>()
    const results: ItunesResult[] = []

    for (const r of data.results) {
      if (!r.previewUrl) continue
      const artistScore = similarity(artistName, r.artistName || '')
      if (artistScore < 0.5) continue

      const normalizedTrack = normalizeForComparison(r.trackName || '')
      if (seen.has(normalizedTrack)) continue
      seen.add(normalizedTrack)

      results.push({
        preview_url: r.previewUrl,
        itunes_track_name: r.trackName,
        itunes_artist_name: r.artistName,
        artwork_url: r.artworkUrl100 || r.artworkUrl60 || '',
      })

      if (results.length >= limit) break
    }

    topTracksCache.set(cacheKey, results)
    return results
  } catch {
    topTracksCache.set(cacheKey, [])
    return []
  }
}
