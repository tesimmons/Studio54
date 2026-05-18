import { useRef, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { adminApi } from '../../../api/client'

const MAX_POINTS = 45      // 45 samples × 2 s = 90-second window
const POLL_MS    = 2000

function formatRate(bps: number): string {
  if (bps >= 1024 * 1024) return `${(bps / (1024 * 1024)).toFixed(1)} MB/s`
  if (bps >= 1024)        return `${(bps / 1024).toFixed(0)} KB/s`
  return `${Math.round(bps)} B/s`
}

// ---------------------------------------------------------------------------
// SVG Task Manager-style sparkline
// ---------------------------------------------------------------------------
interface Series { values: number[]; color: string; fillOpacity?: number }

function TaskManagerGraph({
  series,
  yMax,
  label,
  rightLabel,
  yFmt,
}: {
  series: Series[]
  yMax: number
  label: string
  rightLabel: string
  yFmt: (v: number) => string
}) {
  const VW = 400
  const VH = 72
  const PL = 28  // left  (y-axis labels)
  const PR = 2
  const PT = 2
  const PB = 14  // bottom (time axis)
  const iW = VW - PL - PR
  const iH = VH - PT - PB

  // Map a history array to an SVG path string.
  // Values are right-aligned: if fewer than MAX_POINTS, they sit at the right.
  function toPoints(values: number[]): string {
    if (values.length === 0) return ''
    return values.map((v, i) => {
      const slot = MAX_POINTS - values.length + i
      const x = PL + (slot / (MAX_POINTS - 1)) * iW
      const y = PT + iH - Math.min(v / yMax, 1) * iH
      return `${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
  }

  function toAreaPath(values: number[]): string {
    if (values.length < 2) return ''
    const linePoints = values.map((v, i) => {
      const slot = MAX_POINTS - values.length + i
      const x = PL + (slot / (MAX_POINTS - 1)) * iW
      const y = PT + iH - Math.min(v / yMax, 1) * iH
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    const firstX = (PL + ((MAX_POINTS - values.length) / (MAX_POINTS - 1)) * iW).toFixed(1)
    const lastX  = (PL + iW).toFixed(1)
    const base   = (PT + iH).toFixed(1)
    return `M ${firstX},${base} L ${linePoints.join(' L ')} L ${lastX},${base} Z`
  }

  // Y-axis: 0 / 50% / 100% of yMax
  const yTicks = [0, 0.5, 1]
  // Time-axis labels: -90s, -60s, -30s, 0
  const timeTicks = [
    { frac: 0,      label: '−90s' },
    { frac: 1 / 3,  label: '−60s' },
    { frac: 2 / 3,  label: '−30s' },
    { frac: 1,      label: '0'    },
  ]

  return (
    <div className="flex flex-col">
      {/* Header row */}
      <div className="flex items-center justify-between px-0.5 mb-0.5">
        <span className="text-[11px] font-semibold tracking-wide text-gray-300 uppercase">{label}</span>
        <span className="text-[11px] font-mono tabular-nums" style={{ color: series[0]?.color ?? '#fff' }}>
          {rightLabel}
        </span>
      </div>

      <svg
        viewBox={`0 0 ${VW} ${VH}`}
        width="100%"
        className="block"
        style={{ height: '72px' }}
      >
        {/* Plot area background */}
        <rect x={PL} y={PT} width={iW} height={iH} fill="#0b0f1a" />

        {/* Horizontal grid lines + y-axis labels */}
        {yTicks.map((f) => {
          const y = PT + (1 - f) * iH
          return (
            <g key={f}>
              <line
                x1={PL} y1={y} x2={PL + iW} y2={y}
                stroke={f === 0 || f === 1 ? '#1e2a3a' : '#141e2e'}
                strokeWidth={f === 0 || f === 1 ? 0.75 : 0.5}
                strokeDasharray={f > 0 && f < 1 ? '3 5' : undefined}
              />
              <text x={PL - 3} y={y + 3.5} textAnchor="end" fontSize={7} fill="#4b5563" fontFamily="monospace">
                {yFmt(f * yMax)}
              </text>
            </g>
          )
        })}

        {/* Vertical guide lines */}
        {[1 / 3, 2 / 3].map((f) => (
          <line key={f}
            x1={PL + f * iW} y1={PT} x2={PL + f * iW} y2={PT + iH}
            stroke="#141e2e" strokeWidth={0.5} strokeDasharray="3 5"
          />
        ))}

        {/* Area fills */}
        {series.map((s, i) => (
          <path key={`a${i}`} d={toAreaPath(s.values)} fill={s.color} fillOpacity={s.fillOpacity ?? 0.18} />
        ))}

        {/* Lines */}
        {series.map((s, i) => (
          <polyline key={`l${i}`}
            points={toPoints(s.values)}
            fill="none"
            stroke={s.color}
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {/* Border */}
        <rect x={PL} y={PT} width={iW} height={iH} fill="none" stroke="#1e2a3a" strokeWidth={0.75} />

        {/* Time-axis labels */}
        {timeTicks.map((t) => (
          <text key={t.frac}
            x={PL + t.frac * iW}
            y={VH - 2}
            textAnchor="middle"
            fontSize={7}
            fill="#374151"
            fontFamily="monospace"
          >
            {t.label}
          </text>
        ))}
      </svg>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Legend dot
// ---------------------------------------------------------------------------
function Dot({ color }: { color: string }) {
  return <span className="inline-block w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------
interface History {
  cpu:  number[]
  mem:  number[]
  down: number[]
  up:   number[]
}

export default function SystemActivityGraphWidget({
  widgetId: _widgetId,
  isEditMode: _isEditMode,
}: {
  widgetId: string
  isEditMode: boolean
}) {
  const histRef = useRef<History>({ cpu: [], mem: [], down: [], up: [] })
  const prevNetRef = useRef<{ sent: number; recv: number; t: number } | null>(null)
  const [hist, setHist] = useState<History>({ cpu: [], mem: [], down: [], up: [] })

  const { data: stats, isError } = useQuery({
    queryKey: ['system-stats'],
    queryFn: () => adminApi.getSystemStats(),
    refetchInterval: POLL_MS,
    staleTime: POLL_MS - 200,
  })

  useEffect(() => {
    if (!stats) return
    const now = Date.now()

    // Network rate from cumulative counters
    let down = 0
    let up   = 0
    if (stats.network) {
      const cur = { sent: stats.network.bytes_sent, recv: stats.network.bytes_recv, t: now }
      if (prevNetRef.current) {
        const dt = (now - prevNetRef.current.t) / 1000
        if (dt > 0) {
          down = Math.max(0, (cur.recv - prevNetRef.current.recv) / dt)
          up   = Math.max(0, (cur.sent - prevNetRef.current.sent) / dt)
        }
      }
      prevNetRef.current = cur
    }

    const h = histRef.current
    h.cpu  = [...h.cpu.slice(-(MAX_POINTS - 1)),  stats.cpu_percent]
    h.mem  = [...h.mem.slice(-(MAX_POINTS - 1)),  stats.memory.percent]
    h.down = [...h.down.slice(-(MAX_POINTS - 1)), down]
    h.up   = [...h.up.slice(-(MAX_POINTS - 1)),   up]
    setHist({ ...h })
  }, [stats])

  if (isError) {
    return (
      <div className="h-full p-4 flex items-center justify-center">
        <p className="text-xs text-gray-500">System stats unavailable (director role required)</p>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="h-full p-4 flex items-center justify-center">
        <p className="text-xs text-gray-500 animate-pulse">Loading…</p>
      </div>
    )
  }

  // Network Y-axis: scale to peak in current window, minimum 512 KB/s
  const netPeak = Math.max(...hist.down, ...hist.up, 512 * 1024)
  // Round up to a clean boundary for nicer axis labels
  const netMax  = Math.pow(2, Math.ceil(Math.log2(netPeak + 1)))

  const cpuNow  = hist.cpu.length  > 0 ? hist.cpu[hist.cpu.length - 1]   : stats.cpu_percent
  const memNow  = hist.mem.length  > 0 ? hist.mem[hist.mem.length - 1]   : stats.memory.percent
  const downNow = hist.down.length > 0 ? hist.down[hist.down.length - 1] : 0
  const upNow   = hist.up.length   > 0 ? hist.up[hist.up.length - 1]     : 0

  return (
    <div className="h-full flex flex-col bg-[#0b0f1a] rounded-lg overflow-hidden">
      {/* Widget header */}
      <div className="flex items-center justify-between px-3 pt-2.5 pb-1 border-b border-[#1e2a3a]">
        <span className="text-[12px] font-semibold text-gray-200 tracking-wide">System Activity</span>
        <span className="text-[10px] text-gray-500 font-mono">90 s window</span>
      </div>

      {/* Graphs */}
      <div className="flex flex-col gap-2 p-3 flex-1 min-h-0 justify-between">
        {/* CPU */}
        <TaskManagerGraph
          series={[{ values: hist.cpu, color: '#22c55e' }]}
          yMax={100}
          label="CPU"
          rightLabel={`${cpuNow.toFixed(1)}%`}
          yFmt={(v) => `${Math.round(v)}%`}
        />

        {/* Memory */}
        <TaskManagerGraph
          series={[{ values: hist.mem, color: '#818cf8' }]}
          yMax={100}
          label={`Memory  ${(stats.memory.used_bytes / 1073741824).toFixed(1)} / ${(stats.memory.total_bytes / 1073741824).toFixed(1)} GB`}
          rightLabel={`${memNow.toFixed(1)}%`}
          yFmt={(v) => `${Math.round(v)}%`}
        />

        {/* Network */}
        <TaskManagerGraph
          series={[
            { values: hist.down, color: '#38bdf8', fillOpacity: 0.14 },
            { values: hist.up,   color: '#fb923c', fillOpacity: 0.10 },
          ]}
          yMax={netMax}
          label="Network"
          rightLabel={`↓ ${formatRate(downNow)}  ↑ ${formatRate(upNow)}`}
          yFmt={formatRate}
        />

        {/* Network legend */}
        <div className="flex items-center gap-3 px-0.5">
          <span className="flex items-center gap-1.5 text-[10px] text-gray-500">
            <Dot color="#38bdf8" /> Download
          </span>
          <span className="flex items-center gap-1.5 text-[10px] text-gray-500">
            <Dot color="#fb923c" /> Upload
          </span>
        </div>
      </div>
    </div>
  )
}
