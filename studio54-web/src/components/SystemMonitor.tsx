import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../api/client'
import { FiChevronUp, FiCpu, FiHardDrive, FiWifi } from 'react-icons/fi'

function formatBytes(bytes: number): string {
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(0)} MB`
}

function formatRate(bytesPerSec: number): string {
  if (bytesPerSec >= 1024 * 1024) return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`
  if (bytesPerSec >= 1024) return `${(bytesPerSec / 1024).toFixed(0)} KB/s`
  return `${bytesPerSec.toFixed(0)} B/s`
}

function getBarColor(percent: number): string {
  if (percent >= 85) return 'bg-red-500'
  if (percent >= 60) return 'bg-amber-500'
  return 'bg-emerald-500'
}

function getTextColor(percent: number): string {
  if (percent >= 85) return 'text-red-400'
  if (percent >= 60) return 'text-amber-400'
  return 'text-emerald-400'
}

type PopoverType = 'cpu' | 'memory' | null

interface NetSnapshot { bytes_sent: number; bytes_recv: number; time: number }

function SystemMonitor() {
  const [collapsed, setCollapsed] = useState(false)
  const [popover, setPopover] = useState<PopoverType>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const showGpu = localStorage.getItem('studio54-show-gpu') === 'true'
  const prevNet = useRef<NetSnapshot | null>(null)
  const [netRate, setNetRate] = useState({ up: 0, down: 0 })

  const { data: stats } = useQuery({
    queryKey: ['system-stats'],
    queryFn: () => adminApi.getSystemStats(),
    refetchInterval: 5000,
    staleTime: 4000,
  })

  // Compute network throughput from cumulative counters
  useEffect(() => {
    if (!stats?.network?.bytes_sent) return
    const now = Date.now()
    const cur: NetSnapshot = { bytes_sent: stats.network.bytes_sent, bytes_recv: stats.network.bytes_recv, time: now }
    if (prevNet.current) {
      const dt = (now - prevNet.current.time) / 1000
      if (dt > 0) {
        setNetRate({
          up: (cur.bytes_sent - prevNet.current.bytes_sent) / dt,
          down: (cur.bytes_recv - prevNet.current.bytes_recv) / dt,
        })
      }
    }
    prevNet.current = cur
  }, [stats?.network?.bytes_sent, stats?.network?.bytes_recv])

  // Close popover on outside click
  useEffect(() => {
    if (!popover) return
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setPopover(null)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [popover])

  if (!stats) return null

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="w-full h-1 flex bg-gray-200 dark:bg-[#0D1117] hover:h-2 transition-all cursor-pointer"
        title="Expand system monitor"
      >
        <div className={`${getBarColor(stats.cpu_percent)} transition-all`} style={{ width: `${stats.cpu_percent}%` }} />
        <div className={`${getBarColor(stats.memory.percent)} transition-all`} style={{ width: `${stats.memory.percent}%` }} />
      </button>
    )
  }

  const metrics: { key: string; label: string; percent: number; detail: string; icon: typeof FiCpu; clickable: boolean }[] = [
    {
      key: 'cpu',
      label: 'CPU',
      percent: stats.cpu_percent,
      detail: `${stats.cpu_percent.toFixed(1)}%`,
      icon: FiCpu,
      clickable: true,
    },
    {
      key: 'memory',
      label: 'Memory',
      percent: stats.memory.percent,
      detail: `${formatBytes(stats.memory.used_bytes)} / ${formatBytes(stats.memory.total_bytes)}`,
      icon: FiHardDrive,
      clickable: true,
    },
    {
      key: 'network',
      label: 'Net',
      percent: -1,
      detail: `↑ ${formatRate(netRate.up)}  ↓ ${formatRate(netRate.down)}`,
      icon: FiWifi,
      clickable: false,
    },
    {
      key: 'disk',
      label: 'Disk',
      percent: stats.disk.percent,
      detail: `${formatBytes(stats.disk.used_bytes)} / ${formatBytes(stats.disk.total_bytes)}`,
      icon: FiHardDrive,
      clickable: false,
    },
  ]

  if (showGpu && stats.gpu) {
    metrics.push({
      key: 'gpu',
      label: 'GPU',
      percent: stats.gpu.utilization_percent,
      detail: `${stats.gpu.memory_used_mb} / ${stats.gpu.memory_total_mb} MB`,
      icon: FiCpu,
      clickable: false,
    })
  }

  const handleMetricClick = (key: string) => {
    if (key === 'cpu' || key === 'memory') {
      setPopover(popover === key ? null : key)
    }
  }

  return (
    <div className="bg-gray-800 border-b border-gray-700 px-4 py-1 flex items-center gap-6 text-xs relative">
      {metrics.map((m) => (
        <div key={m.key} className="relative">
          <div
            className={`flex items-center gap-2 min-w-0 ${m.clickable ? 'cursor-pointer hover:bg-gray-700/50 rounded px-1.5 py-0.5 -mx-1.5 -my-0.5' : ''}`}
            title={m.clickable ? `Click to see top processes` : m.detail}
            onClick={() => handleMetricClick(m.key)}
          >
            <span className="text-gray-400 font-medium shrink-0">{m.label}</span>
            {m.percent >= 0 ? (
              <>
                <div className="w-20 h-1.5 bg-gray-600 rounded-full overflow-hidden shrink-0">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${getBarColor(m.percent)}`}
                    style={{ width: `${Math.min(m.percent, 100)}%` }}
                  />
                </div>
                <span className={`font-mono tabular-nums shrink-0 ${getTextColor(m.percent)}`}>
                  {m.percent.toFixed(0)}%
                </span>
              </>
            ) : (
              <span className="font-mono tabular-nums shrink-0 text-cyan-400 text-[11px]">
                {m.detail}
              </span>
            )}
          </div>

          {/* Popover for CPU */}
          {popover === 'cpu' && m.key === 'cpu' && stats.top_cpu_processes && (
            <div
              ref={popoverRef}
              className="absolute top-full left-0 mt-2 w-72 bg-gray-900 border border-gray-600 rounded-lg shadow-xl z-50 overflow-hidden"
            >
              <div className="px-3 py-2 border-b border-gray-700 flex items-center justify-between">
                <span className="font-semibold text-gray-200">Top CPU Processes</span>
                <span className="text-gray-500">PID</span>
              </div>
              <div className="divide-y divide-gray-800">
                {stats.top_cpu_processes.map((proc) => (
                  <div key={proc.pid} className="px-3 py-1.5 flex items-center gap-2">
                    <div className="flex-1 min-w-0">
                      <span className="text-gray-300 truncate block">{proc.name}</span>
                    </div>
                    <span className={`font-mono tabular-nums shrink-0 ${getTextColor(proc.cpu_percent)}`}>
                      {proc.cpu_percent.toFixed(1)}%
                    </span>
                    <span className="text-gray-600 font-mono text-[10px] w-12 text-right shrink-0">{proc.pid}</span>
                  </div>
                ))}
                {stats.top_cpu_processes.length === 0 && (
                  <div className="px-3 py-2 text-gray-500">No process data</div>
                )}
              </div>
            </div>
          )}

          {/* Popover for Memory */}
          {popover === 'memory' && m.key === 'memory' && stats.top_memory_processes && (
            <div
              ref={popoverRef}
              className="absolute top-full left-0 mt-2 w-80 bg-gray-900 border border-gray-600 rounded-lg shadow-xl z-50 overflow-hidden"
            >
              <div className="px-3 py-2 border-b border-gray-700 flex items-center justify-between">
                <span className="font-semibold text-gray-200">Top Memory Processes</span>
                <span className="text-gray-500">PID</span>
              </div>
              <div className="divide-y divide-gray-800">
                {stats.top_memory_processes.map((proc) => (
                  <div key={proc.pid} className="px-3 py-1.5 flex items-center gap-2">
                    <div className="flex-1 min-w-0">
                      <span className="text-gray-300 truncate block">{proc.name}</span>
                    </div>
                    <span className="text-gray-400 font-mono text-[10px] shrink-0">{proc.memory_mb.toFixed(0)} MB</span>
                    <span className={`font-mono tabular-nums shrink-0 w-12 text-right ${getTextColor(proc.memory_percent)}`}>
                      {proc.memory_percent.toFixed(1)}%
                    </span>
                    <span className="text-gray-600 font-mono text-[10px] w-12 text-right shrink-0">{proc.pid}</span>
                  </div>
                ))}
                {stats.top_memory_processes.length === 0 && (
                  <div className="px-3 py-2 text-gray-500">No process data</div>
                )}
              </div>
            </div>
          )}
        </div>
      ))}

      <button
        onClick={() => setCollapsed(true)}
        className="ml-auto text-gray-500 hover:text-gray-300 transition-colors"
        title="Collapse system monitor"
      >
        <FiChevronUp className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

export default SystemMonitor
