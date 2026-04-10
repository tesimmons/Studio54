import { useSearchParams } from 'react-router-dom'
import { useCallback, useRef, useEffect } from 'react'

// Shared pending updates across all hook instances within a component tree.
// We batch all changes from the same synchronous event handler into one
// setSearchParams call via queueMicrotask.
const pendingUpdates = new Map<string, { value: string; defaultValue: string }>()
let flushFn: (() => void) | null = null
let flushScheduled = false

function scheduleFlush() {
  if (flushScheduled) return
  flushScheduled = true
  queueMicrotask(() => {
    flushScheduled = false
    if (flushFn && pendingUpdates.size > 0) {
      flushFn()
    }
    pendingUpdates.clear()
  })
}

export function useSearchParamState(
  key: string,
  defaultValue: string
): [string, (value: string) => void] {
  const [searchParams, setSearchParams] = useSearchParams()
  const value = searchParams.get(key) || defaultValue

  // Keep flushFn pointed at the latest setSearchParams
  const setSearchParamsRef = useRef(setSearchParams)
  setSearchParamsRef.current = setSearchParams

  useEffect(() => {
    flushFn = () => {
      setSearchParamsRef.current(prev => {
        const next = new URLSearchParams(prev)
        for (const [k, entry] of pendingUpdates) {
          if (entry.value === entry.defaultValue) {
            next.delete(k)
          } else {
            next.set(k, entry.value)
          }
        }
        return next
      }, { replace: true })
    }
  })

  const setValue = useCallback((newValue: string) => {
    pendingUpdates.set(key, { value: newValue, defaultValue })
    scheduleFlush()
  }, [key, defaultValue])

  return [value, setValue]
}
