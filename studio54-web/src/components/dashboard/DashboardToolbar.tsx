import { useState } from 'react'
import { FiEdit2, FiSave, FiX, FiPlus } from 'react-icons/fi'
import { WIDGET_MAP, CATEGORY_LABELS } from './widgetRegistry'
import type { WidgetCategory } from '../../types'
import { useAuth } from '../../contexts/AuthContext'

interface DashboardToolbarProps {
  isEditMode: boolean
  hiddenWidgets: string[]
  onEnterEdit: () => void
  onCancel: () => void
  onSave: () => void
  onAddWidget: (id: string) => void
  isSaving: boolean
}

export default function DashboardToolbar({
  isEditMode,
  hiddenWidgets,
  onEnterEdit,
  onCancel,
  onSave,
  onAddWidget,
  isSaving,
}: DashboardToolbarProps) {
  const [showPicker, setShowPicker] = useState(false)
  const { isDirector } = useAuth()

  // Group hidden widgets by category
  const hiddenByCategory = hiddenWidgets.reduce<Record<WidgetCategory, string[]>>((acc, id) => {
    const widget = WIDGET_MAP.get(id)
    if (widget) {
      if (widget.requiredRole === 'director' && !isDirector) return acc
      if (!acc[widget.category]) acc[widget.category] = []
      acc[widget.category].push(id)
    }
    return acc
  }, {} as Record<WidgetCategory, string[]>)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl md:text-3xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">
            {isEditMode ? 'Drag, resize, and arrange your widgets' : 'Library overview, statistics, and system status'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isEditMode ? (
            <>
              <button
                onClick={() => setShowPicker(!showPicker)}
                className="btn btn-secondary flex items-center gap-1.5 text-sm"
                disabled={hiddenWidgets.length === 0}
              >
                <FiPlus className="w-4 h-4" />
                Add Widget{hiddenWidgets.length > 0 && ` (${hiddenWidgets.length})`}
              </button>
              <button onClick={onCancel} className="btn btn-secondary flex items-center gap-1.5 text-sm">
                <FiX className="w-4 h-4" />
                Cancel
              </button>
              <button onClick={onSave} disabled={isSaving} className="btn btn-primary flex items-center gap-1.5 text-sm">
                <FiSave className="w-4 h-4" />
                {isSaving ? 'Saving...' : 'Save'}
              </button>
            </>
          ) : (
            <button onClick={onEnterEdit} className="btn btn-secondary flex items-center gap-1.5 text-sm">
              <FiEdit2 className="w-4 h-4" />
              Customize
            </button>
          )}
        </div>
      </div>

      {/* Widget Picker Panel */}
      {isEditMode && showPicker && hiddenWidgets.length > 0 && (
        <div className="card p-4">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Hidden Widgets</h3>
          <div className="space-y-3">
            {(Object.entries(hiddenByCategory) as [WidgetCategory, string[]][]).map(([category, ids]) => (
              <div key={category}>
                <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 uppercase tracking-wider">{CATEGORY_LABELS[category]}</p>
                <div className="flex flex-wrap gap-2">
                  {ids.map((id) => {
                    const w = WIDGET_MAP.get(id)!
                    return (
                      <button
                        key={id}
                        onClick={() => {
                          onAddWidget(id)
                          if (hiddenWidgets.length <= 1) setShowPicker(false)
                        }}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gray-100 dark:bg-[#0D1117] text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-200 dark:hover:bg-[#30363D] transition-colors border border-gray-200 dark:border-[#30363D]"
                      >
                        <FiPlus className="w-3.5 h-3.5" />
                        {w.label}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
