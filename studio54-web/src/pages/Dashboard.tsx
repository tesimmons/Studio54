import { useState, useEffect, useCallback, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { LayoutItem } from 'react-grid-layout'
import toast from 'react-hot-toast'
import { authApi } from '../api/client'
import { DEFAULT_LAYOUT, WIDGET_MAP } from '../components/dashboard/widgetRegistry'
import DashboardToolbar from '../components/dashboard/DashboardToolbar'
import DashboardGrid from '../components/dashboard/DashboardGrid'
import type { DashboardLayoutItem, DashboardPreferences } from '../types'

const CURRENT_SCHEMA_VERSION = 1

function Dashboard() {
  const queryClient = useQueryClient()
  const [isEditMode, setIsEditMode] = useState(false)
  const [layouts, setLayouts] = useState<DashboardLayoutItem[]>(DEFAULT_LAYOUT)
  const [hiddenWidgets, setHiddenWidgets] = useState<string[]>([])
  const snapshotRef = useRef<{ layouts: DashboardLayoutItem[]; hidden: string[] } | null>(null)

  // Fetch user preferences
  const { data: prefs, isLoading } = useQuery({
    queryKey: ['userPreferences'],
    queryFn: authApi.getPreferences,
  })

  // Apply saved preferences on load, merging in any new DEFAULT_LAYOUT widgets
  useEffect(() => {
    if (prefs?.dashboard) {
      const dash = prefs.dashboard as DashboardPreferences
      if (dash.layouts?.lg && dash.layouts.lg.length > 0) {
        // Always apply current minW/minH from registry (they may have changed)
        const savedLayouts = dash.layouts.lg.map(item => {
          const widget = WIDGET_MAP.get(item.i)
          return widget ? { ...item, minW: widget.minSize.w, minH: widget.minSize.h } : item
        })
        // Merge in any new widgets from DEFAULT_LAYOUT that are missing from saved
        const savedIds = new Set(savedLayouts.map(item => item.i))
        const newWidgets = DEFAULT_LAYOUT.filter(item => !savedIds.has(item.i))
        setLayouts([...savedLayouts, ...newWidgets])
      }
      if (dash.hiddenWidgets) {
        setHiddenWidgets(dash.hiddenWidgets)
      }
    }
  }, [prefs])

  // Save preferences mutation
  const saveMutation = useMutation({
    mutationFn: (dashboard: DashboardPreferences) =>
      authApi.updatePreferences({ dashboard }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['userPreferences'] })
      toast.success('Dashboard layout saved')
      setIsEditMode(false)
    },
    onError: () => {
      toast.error('Failed to save layout')
    },
  })

  const handleEnterEdit = useCallback(() => {
    snapshotRef.current = { layouts: [...layouts], hidden: [...hiddenWidgets] }
    setIsEditMode(true)
  }, [layouts, hiddenWidgets])

  const handleCancel = useCallback(() => {
    if (snapshotRef.current) {
      setLayouts(snapshotRef.current.layouts)
      setHiddenWidgets(snapshotRef.current.hidden)
    }
    setIsEditMode(false)
  }, [])

  const handleSave = useCallback(() => {
    saveMutation.mutate({
      version: CURRENT_SCHEMA_VERSION,
      layouts: { lg: layouts },
      hiddenWidgets,
    })
  }, [layouts, hiddenWidgets, saveMutation])

  const handleLayoutChange = useCallback((newLayout: LayoutItem[]) => {
    if (!isEditMode) return
    setLayouts(
      newLayout.map((l) => {
        const existing = WIDGET_MAP.get(l.i)
        return {
          i: l.i,
          x: l.x,
          y: l.y,
          w: l.w,
          h: l.h,
          minW: existing?.minSize.w,
          minH: existing?.minSize.h,
        }
      })
    )
  }, [isEditMode])

  const handleHideWidget = useCallback((id: string) => {
    setHiddenWidgets((prev) => [...prev, id])
  }, [])

  const handleAddWidget = useCallback((id: string) => {
    setHiddenWidgets((prev) => prev.filter((w) => w !== id))
    // Add widget back at the bottom of the grid with default size
    const widget = WIDGET_MAP.get(id)
    if (widget) {
      const defaultItem = DEFAULT_LAYOUT.find((l) => l.i === id)
      const newItem: DashboardLayoutItem = {
        i: id,
        x: 0,
        y: Infinity, // RGL will compact it to the bottom
        w: defaultItem?.w || widget.defaultSize.w,
        h: defaultItem?.h || widget.defaultSize.h,
        minW: widget.minSize.w,
        minH: widget.minSize.h,
      }
      setLayouts((prev) => [...prev.filter((l) => l.i !== id), newItem])
    }
  }, [])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#FF1493] mx-auto" />
          <p className="mt-4 text-gray-600 dark:text-gray-400">Loading dashboard...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <DashboardToolbar
        isEditMode={isEditMode}
        hiddenWidgets={hiddenWidgets}
        onEnterEdit={handleEnterEdit}
        onCancel={handleCancel}
        onSave={handleSave}
        onAddWidget={handleAddWidget}
        isSaving={saveMutation.isPending}
      />
      <DashboardGrid
        layouts={layouts}
        hiddenWidgets={hiddenWidgets}
        isEditMode={isEditMode}
        onLayoutChange={handleLayoutChange}
        onHideWidget={handleHideWidget}
      />
    </div>
  )
}

export default Dashboard
