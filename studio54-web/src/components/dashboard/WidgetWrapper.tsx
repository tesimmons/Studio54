import { FiX, FiMove } from 'react-icons/fi'
import type { WidgetDefinition } from '../../types'

interface WidgetWrapperProps {
  widget: WidgetDefinition
  widgetId: string
  isEditMode: boolean
  onHide: (id: string) => void
  children: React.ReactNode
}

export default function WidgetWrapper({ widget, widgetId, isEditMode, onHide, children }: WidgetWrapperProps) {
  // Section headers render without card chrome
  if (widget.category === 'section') {
    return (
      <div className={`h-full ${isEditMode ? 'border border-dashed border-gray-300 dark:border-[#30363D] rounded-lg' : ''}`}>
        {isEditMode && (
          <div className="drag-handle flex items-center justify-between px-3 py-0.5 cursor-grab active:cursor-grabbing select-none">
            <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <FiMove className="w-3.5 h-3.5" />
              <span className="font-medium">{widget.label}</span>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); onHide(widgetId) }}
              className="p-0.5 text-gray-400 hover:text-red-400 transition-colors rounded"
              title="Hide widget"
            >
              <FiX className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
        {children}
      </div>
    )
  }

  return (
    <div className={`h-full flex flex-col bg-white dark:bg-[#161B22] rounded-lg shadow-md border dark:border-[#30363D] ${isEditMode ? 'overflow-visible' : 'overflow-hidden'}`}>
      {isEditMode && (
        <div className="drag-handle flex items-center justify-between px-3 py-1.5 bg-gray-50 dark:bg-[#0D1117] border-b border-gray-200 dark:border-[#30363D] cursor-grab active:cursor-grabbing select-none">
          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            <FiMove className="w-3.5 h-3.5" />
            <span className="font-medium">{widget.label}</span>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); onHide(widgetId) }}
            className="p-0.5 text-gray-400 hover:text-red-400 transition-colors rounded"
            title="Hide widget"
          >
            <FiX className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-hidden">
        {children}
      </div>
    </div>
  )
}
