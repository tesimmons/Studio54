import { WIDGET_MAP } from '../widgetRegistry'

export default function SectionHeaderWidget({ widgetId }: { widgetId: string; isEditMode: boolean }) {
  const widget = WIDGET_MAP.get(widgetId)
  const label = widget?.label || 'Section'

  return (
    <div className="h-full flex items-end px-1 pb-1">
      <h2 className="text-xl font-bold text-gray-900 dark:text-white tracking-wide uppercase">
        {label}
      </h2>
    </div>
  )
}
