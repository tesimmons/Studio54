import React, { useMemo, useCallback } from 'react'
import { ResponsiveGridLayout, useContainerWidth, verticalCompactor } from 'react-grid-layout'
import type { LayoutItem, Layout, ResponsiveLayouts } from 'react-grid-layout'
import { WIDGET_MAP } from './widgetRegistry'
import WidgetWrapper from './WidgetWrapper'
import type { DashboardLayoutItem } from '../../types'
import { useAuth } from '../../contexts/AuthContext'

interface DashboardGridProps {
  layouts: DashboardLayoutItem[]
  hiddenWidgets: string[]
  isEditMode: boolean
  onLayoutChange: (layout: LayoutItem[]) => void
  onHideWidget: (id: string) => void
}

const BREAKPOINTS = { lg: 1200, md: 996, sm: 768, xs: 480 }
const COLS = { lg: 12, md: 8, sm: 4, xs: 1 }

export default function DashboardGrid({
  layouts,
  hiddenWidgets,
  isEditMode,
  onLayoutChange,
  onHideWidget,
}: DashboardGridProps) {
  const { isDirector } = useAuth()
  const { width, containerRef, mounted } = useContainerWidth()

  const visibleWidgets = useMemo(() => {
    const hiddenSet = new Set(hiddenWidgets)
    return layouts.filter((item) => {
      if (hiddenSet.has(item.i)) return false
      const widget = WIDGET_MAP.get(item.i)
      if (!widget) return false
      if (widget.requiredRole === 'director' && !isDirector) return false
      return true
    })
  }, [layouts, hiddenWidgets, isDirector])

  const rglLayouts: ResponsiveLayouts = useMemo(() => {
    const lgLayout: LayoutItem[] = visibleWidgets.map((item) => ({
      i: item.i,
      x: item.x,
      y: item.y,
      w: item.w,
      h: item.h,
      minW: item.minW,
      minH: item.minH,
    }))

    const mdLayout: LayoutItem[] = visibleWidgets.map((item) => ({
      ...item,
      w: Math.min(item.w, 8),
      x: Math.min(item.x, 8 - Math.min(item.w, 8)),
    }))

    const smLayout: LayoutItem[] = visibleWidgets.map((item) => ({
      ...item,
      w: Math.min(item.w, 4),
      x: 0,
    }))

    return {
      lg: lgLayout,
      md: mdLayout,
      sm: smLayout,
      xs: visibleWidgets.map(item => ({ ...item, w: 1, x: 0 })),
    }
  }, [visibleWidgets])

  const handleLayoutChange = useCallback(
    (currentLayout: Layout) => {
      // Layout is readonly LayoutItem[] in RGL v2
      onLayoutChange([...currentLayout])
    },
    [onLayoutChange]
  )

  return (
    <div ref={containerRef as React.RefObject<HTMLDivElement>}>
      {mounted && (
        <ResponsiveGridLayout
          className="layout"
          width={width}
          layouts={rglLayouts}
          breakpoints={BREAKPOINTS}
          cols={COLS}
          rowHeight={50}
          dragConfig={{ enabled: isEditMode, handle: '.drag-handle' }}
          resizeConfig={{ enabled: isEditMode }}
          onLayoutChange={handleLayoutChange}
          compactor={verticalCompactor}
          margin={[16, 16] as const}
        >
          {visibleWidgets.map((item) => {
            const widget = WIDGET_MAP.get(item.i)
            if (!widget) return null
            const Component = widget.component
            return (
              <div key={item.i}>
                <WidgetWrapper
                  widget={widget}
                  widgetId={item.i}
                  isEditMode={isEditMode}
                  onHide={onHideWidget}
                >
                  <Component widgetId={item.i} isEditMode={isEditMode} libraryType={widget.libraryType} />
                </WidgetWrapper>
              </div>
            )
          })}
        </ResponsiveGridLayout>
      )}
    </div>
  )
}
