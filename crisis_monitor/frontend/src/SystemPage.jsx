/**
 * SystemPage.jsx — /system
 * Crisis Monitor — Pipeline & Agent Health Dashboard
 *
 * Route: aggiungere in main.jsx o App.jsx:
 *   import SystemPage from './SystemPage'
 *   // se usi react-router:
 *   <Route path="/system" element={<SystemPage />} />
 *   // oppure link diretto: window.location.href = '/system'
 */

import { useState, useEffect, useCallback } from "react"
import { createClient } from "@supabase/supabase-js"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts"

// ── Supabase (stesse variabili d'ambiente dell'app principale) ────────────────
const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_KEY
)

// ── Costanti ──────────────────────────────────────────────────────────────────
const AGENTS = [
  { key: "scanner",    label: "Agent 00",  name: "Scanner",     desc: "Web Search → new crises",       ioLabel: ["queries", "crises found"], color: "#8b5cf6" },
  { key: "collector",  label: "Agent 01",  name: "Collector",   desc: "GNews → raw_articles",          ioLabel: ["API calls", "articles"],   color: "#4a90d9" },
  { key: "classifier", label: "Agent 02",  name: "Classifier",  desc: "raw → classified_events",       ioLabel: ["articles", "events"],      color: "#e8960a" },
  { key: "matcher",    label: "Agent 03",  name: "Matcher",     desc: "events → crises",               ioLabel: ["events", "crises"],        color: "#7c3aed" },
  { key: "connector",  label: "Agent 04",  name: "Connector",   desc: "crises → connections",          ioLabel: ["crises", "connections"],   color: "#0891b2" },
  { key: "analyst",    label: "Agent 05",  name: "Analyst",     desc: "deep analysis",                 ioLabel: ["crises", "analyses"],      color: "#c0533a" },
  { key: "verifier",   label: "Agent 06",  name: "Verifier",    desc: "monthly verification",          ioLabel: ["crises", "verified"],      color: "#16a34a" },
  { key: "supervisor", label: "Agent 07",  name: "Supervisor",  desc: "system audit",                  ioLabel: ["runs", "findings"],        color: "#b8720a" },
]

const STATUS_COLOR = {
  success: "#7fa87a",
  error:   "#c0533a",
  skipped: "#a0926a",
}

const DAYS = 14 // chart window (days)

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtMs(ms) {
  if (!ms) return "—"
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms/1000).toFixed(1)}s`
  return `${Math.floor(ms/60000)}m ${Math.floor((ms%60000)/1000)}s`
}

function fmtCost(c) {
  if (!c) return "$0.00"
  return `$${Number(c).toFixed(4)}`
}

function fmtDate(str) {
  if (!str) return "—"
  const d = new Date(str)
  return d.toLocaleString("it-IT", { month:"short", day:"numeric",
    hour:"2-digit", minute:"2-digit" })
}

function timeAgo(str) {
  if (!str) return "—"
  const diff = Date.now() - new Date(str).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 60)  return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24)  return `${h}h ago`
  return `${Math.floor(h/24)}d ago`
}

function last(arr) { return arr?.[arr.length - 1] }

// ── Hook: load all system data ────────────────────────────────────────────────
function useSystemData() {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const since = new Date(Date.now() - DAYS * 24 * 3600 * 1000).toISOString()

      const [runsRes, supervisorRes, validationRes] = await Promise.all([
        supabase
          .from("cm_agent_runs")
          .select("*")
          .gte("run_at", since)
          .order("run_at", { ascending: true }),
        supabase
          .from("cm_supervisor_log")
          .select("*")
          .gte("run_at", since)
          .order("run_at", { ascending: true }),
        supabase
          .from("validation_errors")
          .select("validator, severity, resolved, created_at")
          .gte("created_at", since),
      ])

      const runs           = runsRes.data      || []
      const supervisorLogs = supervisorRes.data || []
      const supervisor     = supervisorLogs.length ? supervisorLogs[supervisorLogs.length - 1] : null
      const valErrors      = validationRes.data || []

      // pipeline_stats from latest supervisor log
      const latestPipelineStats = supervisor?.pipeline_stats || {}

      // Per-agent stats: runs from cm_agent_runs + data from cm_supervisor_log
      const agentStats = {}
      for (const ag of AGENTS) {
        const agRuns    = runs.filter(r => r.agent === ag.key)
        const lastRun   = agRuns.length ? agRuns[agRuns.length - 1] : null
        const totalRuns = agRuns.length

        const supData    = latestPipelineStats[ag.key] || null
        const supMetrics = supData?.metrics || {}

        // Score series: one point per supervisor audit (for chart)
        // FIX: score=null when <3 runs (insufficient_data) → filtered out
        const scoreSeries = supervisorLogs.map((log, idx) => ({
          date:  log.run_at?.slice(0, 10) || ("audit-" + idx),
          score: log.pipeline_stats?.[ag.key]?.score ?? null,
          verdict: log.pipeline_stats?.[ag.key]?.verdict ?? null,
        })).filter(p => p.score !== null)

        // Error trend series — FIX: null = N/A, non 0
        const errorTrendSeries = supervisorLogs.map((log, idx) => ({
          date:  log.run_at?.slice(0, 10) || ("audit-" + idx),
          value: log.pipeline_stats?.[ag.key]?.metrics?.error_trend ?? null,
        }))

        agentStats[ag.key] = {
          totalRuns,
          lastRun,
          score:        supData?.score         ?? null,
          verdict:      supData?.verdict       ?? null,
          comment:      supData?.comment       ?? null,
          successRate:  supMetrics.success_rate    ?? null,
          errorTrend:   supMetrics.error_trend     ?? null,
          totalCost:    supMetrics.total_cost_usd  ?? null,
          scoreSeries,
          errorTrendSeries,
        }
      }

      // Daily timeline for charts
      const days = []
      for (let i = DAYS - 1; i >= 0; i--) {
        const d   = new Date(Date.now() - i * 24 * 3600 * 1000)
        const key = d.toISOString().slice(0, 10)
        const dayRuns = runs.filter(r => r.run_at.startsWith(key))
        days.push({
          date:    key,
          label:   d.toLocaleDateString("it-IT", { month:"short", day:"numeric" }),
          runs:    dayRuns.length,
          errors:  dayRuns.filter(r => r.status === "error").length,
          cost:    dayRuns.reduce((s, r) => s + Number(r.cost_usd || 0), 0),
          tokens:  dayRuns.reduce((s, r) => s + (r.input_tokens || 0) + (r.output_tokens || 0), 0),
        })
      }

      // Totali globali
      const totals = {
        runs:    runs.length,
        errors:  runs.filter(r => r.status === "error").length,
        cost:    runs.reduce((s, r) => s + Number(r.cost_usd || 0), 0),
        tokens:  runs.reduce((s, r) => s + (r.input_tokens || 0) + (r.output_tokens || 0), 0),
        valErrors: valErrors.filter(e => !e.resolved).length,
        hardFails: valErrors.filter(e => e.severity === "hard_fail" && !e.resolved).length,
      }

      setData({ agentStats, days, totals, supervisor, supervisorLogs, runs })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  return { data, loading, error, reload: load }
}

// ── Sparkline SVG ─────────────────────────────────────────────────────────────
function Sparkline({ values, color = "#c8a96e", height = 32, width = 120 }) {
  if (!values?.length) return null
  const max = Math.max(...values, 1)
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width
    const y = height - (v / max) * height
    return `${x},${y}`
  }).join(" ")

  return (
    <svg width={width} height={height} style={{ overflow: "visible" }}>
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity="0.85"
      />
      {/* Last point dot */}
      {values.length > 1 && (() => {
        const lx = width
        const ly = height - (values[values.length-1] / max) * height
        return <circle cx={lx} cy={ly} r="2.5" fill={color} />
      })()}
    </svg>
  )
}

// ── Bar chart ─────────────────────────────────────────────────────────────────
function TrendBarChart({ days, field, color = "#c8a96e", height = 60 }) {
  const values = days.map(d => d[field])
  const max    = Math.max(...values, 1)
  const w      = 100 / days.length

  return (
    <svg width="100%" height={height} style={{ overflow: "visible" }}>
      {days.map((d, i) => {
        const barH = (d[field] / max) * (height - 4)
        const x    = i * w
        return (
          <g key={d.date}>
            <rect
              x={`${x + 0.4}%`}
              y={height - barH - 2}
              width={`${w - 0.8}%`}
              height={barH || 1}
              fill={color}
              opacity={0.75}
              rx="1"
            />
          </g>
        )
      })}
    </svg>
  )
}

// ── Agent Card — inline chart + full stats, always visible ───────────────────
function AgentCard({ agent, stats }) {
  const last       = stats.lastRun
  const statusColor = last ? STATUS_COLOR[last.status] : "#b0a090"
  const hasData    = stats.totalRuns > 0

  // Build 14-day run + error arrays (one value per day, padded with 0)
  const { runValues, errValues } = (() => {
    const runs = {}
    const errs = {}
    for (let i = DAYS - 1; i >= 0; i--) {
      const k = new Date(Date.now() - i * 86400000).toISOString().slice(0, 10)
      runs[k] = 0
      errs[k] = 0
    }
    stats.runs.forEach(r => {
      const k = r.run_at.slice(0, 10)
      if (k in runs) {
        runs[k]++
        if (r.status === "error") errs[k]++
      }
    })
    return { runValues: Object.values(runs), errValues: Object.values(errs) }
  })()

  const successRate = stats.totalRuns > 0
    ? Math.round((stats.successRuns / stats.totalRuns) * 100)
    : null

  return (
    <div className="sys-agent-card" style={{ "--status-col": statusColor }}>
      {/* Header row */}
      <div className="sys-agent-header">
        <div className="sys-agent-label">{agent.label}</div>
        <div className={`sys-agent-status ${last?.status || "never"}`}>
          <span className="sys-status-dot" />
          {last?.status || "no data"}
        </div>
      </div>

      {/* Name + desc */}
      <div className="sys-agent-name">{agent.name}</div>
      <div className="sys-agent-desc">{agent.desc}</div>

      {/* Stats row — always shown */}
      <div className="sys-agent-stats">
        <div className="sys-stat-box">
          <div className="sys-stat-val">{hasData ? stats.totalRuns : "—"}</div>
          <div className="sys-stat-lbl">Runs</div>
        </div>
        <div className="sys-stat-box">
          <div className="sys-stat-val" style={{ color: stats.errorRuns > 0 ? "#c0533a" : "inherit" }}>
            {hasData ? stats.errorRuns : "—"}
          </div>
          <div className="sys-stat-lbl">Errors</div>
        </div>
        <div className="sys-stat-box">
          <div className="sys-stat-val" style={{ color: successRate !== null && successRate < 80 ? "#c8a96e" : "inherit" }}>
            {successRate !== null ? `${successRate}%` : "—"}
          </div>
          <div className="sys-stat-lbl">Success</div>
        </div>
        <div className="sys-stat-box">
          <div className="sys-stat-val">{hasData ? fmtMs(stats.avgDuration) : "—"}</div>
          <div className="sys-stat-lbl">Avg time</div>
        </div>
        <div className="sys-stat-box">
          <div className="sys-stat-val">{hasData ? fmtCost(stats.totalCost) : "—"}</div>
          <div className="sys-stat-lbl">Cost</div>
        </div>
        <div className="sys-stat-box">
          <div className="sys-stat-val">{hasData && stats.lastOutput > 0 ? stats.lastOutput : "—"}</div>
          <div className="sys-stat-lbl">{agent.ioLabel ? agent.ioLabel[1] : "Output"}</div>
        </div>
      </div>

      {/* Dual inline chart: runs (bar) + errors (line overlay) */}
      <div className="sys-agent-chart">
        <div className="sys-chart-label-row">
          <span>Activity — last {DAYS} days</span>
          <span className="sys-chart-legend">
            <span className="sys-legend-item"><span className="sys-legend-dot" style={{ background: statusColor }} />executions</span>
            {stats.errorRuns > 0 && <span className="sys-legend-item"><span className="sys-legend-dot" style={{ background: "#c0533a" }} />failed</span>}
          </span>
        </div>
        <InlineBarChart runValues={runValues} errValues={errValues} statusColor={statusColor} />
      </div>

      {/* Last run timestamp */}
      <div className="sys-agent-footer">
        <span>Last run: <strong>{last ? timeAgo(last.run_at) : "never"}</strong></span>
        {last?.error_msg && (
          <div className="sys-agent-error">{last.error_msg}</div>
        )}
      </div>
    </div>
  )
}

// ── InlineBarChart — runs as bars, errors as red dots ────────────────────────
function InlineBarChart({ runValues, errValues, statusColor }) {
  const maxRun = Math.max(...runValues, 1)
  const h = 48
  const w = 100 / runValues.length

  return (
    <svg width="100%" height={h + 4} style={{ display: "block" }}>
      {runValues.map((v, i) => {
        const barH = Math.max((v / maxRun) * h, v > 0 ? 3 : 0)
        const x    = i * w
        const hasErr = errValues[i] > 0
        return (
          <g key={i}>
            <rect
              x={`${x + 0.3}%`} y={h - barH} width={`${w - 0.6}%`} height={barH}
              fill={hasErr ? "#c0533a" : statusColor}
              opacity={hasErr ? 0.9 : 0.65}
              rx="1.5"
            />
          </g>
        )
      })}
    </svg>
  )
}

// ── MiniBarChart — small bar chart for a single metric ──────────────────────
function MiniBarChart({ data, dataKey, color, label, unit }) {
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div className="mini-chart-label">{label}</div>
      <div style={{ height: 56 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
            <XAxis dataKey="date" hide />
            <YAxis hide />
            <Tooltip
              contentStyle={{
                background: "#2a2118", border: "none", borderRadius: 5,
                fontFamily: "'Space Mono', monospace", fontSize: 9, color: "#f5f0e8",
                padding: "6px 10px",
              }}
              labelStyle={{ color: "#c8a96e", fontWeight: 700, fontSize: 8 }}
              formatter={(v) => [`${unit === "$" ? "$" : ""}${typeof v === "number" ? (unit === "$" ? v.toFixed(4) : v.toFixed(0)) : v}`, label]}
              cursor={{ fill: "rgba(0,0,0,0.04)" }}
            />
            <Bar dataKey={dataKey} radius={[2, 2, 0, 0]} maxBarSize={12}>
              {data.map((d, i) => (
                <Cell
                  key={i}
                  fill={d.errors > 0 && dataKey === "runs" ? "#c0533a" : color}
                  opacity={d[dataKey] > 0 ? 0.85 : 0.06}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mini-chart-footer">
        <span>14d ago</span>
        <span className="mini-chart-total">
          {unit === "$" ? "$" : ""}{data.reduce((s, d) => s + d[dataKey], 0).toFixed(unit === "$" ? 2 : 0)}
        </span>
        <span>today</span>
      </div>
    </div>
  )
}

// ── ScoreGauge — circular score 0-100 ────────────────────────────────────────
// ── ScoreLineChart — score nel tempo con zone good/mid/bad ───────────────────
function ScoreLineChart({ series, color }) {
  const h = 100        // SVG height
  const w = 200        // viewBox width
  const padL = 44      // left padding for labels
  const padR = 8
  const padT = 8
  const padB = 8
  const chartW = w - padL - padR
  const chartH = h - padT - padB

  // Fixed thresholds 0-100
  const GOOD = 70
  const BAD  = 40

  // y coordinate for thresholds (scale 0-100 → chartH)
  const yFor = v => padT + chartH - ((v / 100) * chartH)
  const yGood = yFor(GOOD)
  const yBad  = yFor(BAD)

  // Smooth curve via cubic bezier
  const smoothPath = (pts) => {
    if (pts.length === 1) return `M ${pts[0].x},${pts[0].y}`
    let d = `M ${pts[0].x},${pts[0].y}`
    for (let i = 0; i < pts.length - 1; i++) {
      const cp1x = pts[i].x + (pts[i+1].x - pts[i].x) * 0.4
      const cp1y = pts[i].y
      const cp2x = pts[i+1].x - (pts[i+1].x - pts[i].x) * 0.4
      const cp2y = pts[i+1].y
      d += ` C ${cp1x},${cp1y} ${cp2x},${cp2y} ${pts[i+1].x},${pts[i+1].y}`
    }
    return d
  }

  if (!series || series.length === 0) {
    return (
      <div className="sys-score-line">
        <div className="sys-score-line-header">
          <span className="sys-score-line-label">HEALTH SCORE</span>
          <span className="sys-score-line-current" style={{ color: "#b0a090" }}>—</span>
        </div>
        <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`}>
          {/* Zone backgrounds */}
          <rect x={padL} y={padT} width={chartW} height={yGood - padT} fill="rgba(0,0,0,0.03)" />
          <rect x={padL} y={yGood} width={chartW} height={yBad - yGood} fill="rgba(0,0,0,0.05)" />
          <rect x={padL} y={yBad} width={chartW} height={h - padB - yBad} fill="rgba(0,0,0,0.07)" />
          {/* Threshold lines solide */}
          <line x1={0} y1={yGood} x2={w} y2={yGood} stroke="rgba(0,0,0,0.18)" strokeWidth="1" />
          <line x1={0} y1={yBad}  x2={w} y2={yBad}  stroke="rgba(0,0,0,0.18)" strokeWidth="1" />
          {/* Labels */}
          <text x={padL - 4} y={yGood - 5} textAnchor="end" fill="rgba(0,0,0,0.35)" style={{fontSize: 7, fontFamily: "var(--font-mono)", fontWeight: 600}}>optimal</text>
          <text x={padL - 4} y={yBad + 10} textAnchor="end" fill="rgba(0,0,0,0.35)" style={{fontSize: 7, fontFamily: "var(--font-mono)", fontWeight: 600}}>critical</text>
          <text x={padL - 4} y={(yGood + yBad) / 2 - 2} textAnchor="end" fill="rgba(0,0,0,0.35)" style={{fontSize: 7, fontFamily: "var(--font-mono)", fontWeight: 600}}>fair</text>
          {/* No data */}
          <text x={padL + chartW/2} y={h/2} textAnchor="middle" dominantBaseline="middle" fill="rgba(255,255,255,0.2)" style={{fontSize: 9, fontFamily: "var(--font-mono)"}}>no audit yet</text>
        </svg>
      </div>
    )
  }

  const scores = series.map(s => s.score)
  const lastScore = scores[scores.length - 1]
  const currentColor = lastScore >= GOOD ? "#7fa87a" : lastScore >= BAD ? "#c8a96e" : "#c0533a"

  const pts = scores.map((v, i) => ({
    x: padL + (series.length === 1 ? chartW / 2 : (i / (series.length - 1)) * chartW),
    y: yFor(Math.max(0, Math.min(100, v))),
    v,
    verdict: series[i].verdict,
  }))

  const linePath = smoothPath(pts)
  const areaPath = pts.length > 1
    ? linePath + ` L ${pts[pts.length-1].x},${h - padB} L ${pts[0].x},${h - padB} Z`
    : ""

  const verdictDotColor = (v) => ({ improving: "#7fa87a", stable: "#c8a96e", degrading: "#c0533a", insufficient_data: "#b0a090" }[v] || currentColor)

  return (
    <div className="sys-score-line">
      <div className="sys-score-line-header">
        <span className="sys-score-line-label">HEALTH SCORE</span>
        <span className="sys-score-line-current" style={{ color: currentColor }}>{lastScore}</span>
      </div>
      <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        {/* Zone backgrounds */}
        <rect x={padL} y={padT} width={chartW} height={yGood - padT} fill="rgba(0,0,0,0.03)" />
        <rect x={padL} y={yGood} width={chartW} height={yBad - yGood} fill="rgba(0,0,0,0.05)" />
        <rect x={padL} y={yBad} width={chartW} height={h - padB - yBad} fill="rgba(0,0,0,0.07)" />

        {/* Threshold lines — solide come nel disegno */}
        <line x1={0} y1={yGood} x2={w} y2={yGood} stroke="rgba(0,0,0,0.18)" strokeWidth="1" />
        <line x1={0} y1={yBad}  x2={w} y2={yBad}  stroke="rgba(0,0,0,0.18)" strokeWidth="1" />

        {/* Zone labels left of line */}
        <text x={padL - 4} y={yGood - 5} textAnchor="end" dominantBaseline="auto" fill="rgba(0,0,0,0.35)" style={{fontSize: 7, fontFamily: "var(--font-mono)", fontWeight: 600}}>optimal</text>
        <text x={padL - 4} y={yBad + 10} textAnchor="end" dominantBaseline="auto" fill="rgba(0,0,0,0.35)" style={{fontSize: 7, fontFamily: "var(--font-mono)", fontWeight: 600}}>critical</text>
        <text x={padL - 4} y={(yGood + yBad) / 2 - 2} textAnchor="end" dominantBaseline="auto" fill="rgba(0,0,0,0.35)" style={{fontSize: 7, fontFamily: "var(--font-mono)", fontWeight: 600}}>fair</text>

        {/* Area fill — 2+ points only */}
        {areaPath && <path d={areaPath} fill={currentColor} opacity="0.07" />}

        {/* Line — 2+ points only */}
        {pts.length > 1 && (
          <path d={linePath} fill="none" stroke={currentColor} strokeWidth="2.5"
            strokeLinejoin="round" strokeLinecap="round" />
        )}

        {/* Dots su tutti i punti */}
        {pts.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={pts.length === 1 ? 5 : 3.5}
            fill={currentColor} stroke="white" strokeWidth="1.5" />
        ))}

        {/* Single point: dashed horizontal line to indicate the level */}
        {pts.length === 1 && (
          <line x1={padL} y1={pts[0].y} x2={padL + chartW} y2={pts[0].y}
            stroke={currentColor} strokeWidth="1" strokeDasharray="4,4" opacity="0.35" />
        )}
      </svg>
      <div className="sys-score-line-footer">
        <span>{series[0]?.date || ""}</span>
        <span>{series[series.length - 1]?.date || ""}</span>
      </div>
    </div>
  )
}

// ── AgentSection — card compatta: score trend + runs + err trend + note ───────
function AgentSection({ agent, stats }) {
  const score   = stats?.score ?? null
  const verdict = stats?.verdict ?? null
  const et      = stats?.errorTrend ?? null
  const hasSupData = score !== null
  const isInsufficient = verdict === "insufficient_data"

  const scoreColor = score === null ? "#b0a090"
    : score >= 70 ? "#7fa87a"
    : score >= 40 ? "#c8a96e"
    : "#c0533a"

  const etColor = et === null ? "#b0a090"
    : et > 0.05 ? "#c0533a"
    : et < -0.05 ? "#7fa87a"
    : "#c8a96e"

  return (
    <div className="sys-agent-section" style={{ "--agent-color": agent.color }}>

      {/* Top: badge + nome */}
      <div className="sys-card-top">
        <span className="sys-as-badge" style={{ background: agent.color }}>{agent.label}</span>
        <span className="sys-as-name">{agent.name}</span>
        {isInsufficient && (
          <span className="sys-as-insufficient" title="Less than 3 runs — score and trend unreliable">⚠ LOW DATA</span>
        )}
      </div>

      {/* Score line chart */}
      <ScoreLineChart series={stats?.scoreSeries || []} color={scoreColor} />

      {/* Stats: RUNS + ERR TREND */}
      <div className="sys-card-stats-row">
        <div className="sys-stat-pill">
          <span className="sys-stat-pill-val">{stats?.totalRuns ?? "—"}</span>
          <span className="sys-stat-pill-lbl">RUNS</span>
        </div>
        <div className="sys-stat-pill">
          <span className="sys-stat-pill-val" style={{ color: etColor }}>
            {et !== null ? (et > 0 ? "+" + et.toFixed(2) : et.toFixed(2)) : "N/A"}
          </span>
          <span className="sys-stat-pill-lbl">ERR TREND</span>
        </div>
      </div>

      {/* Supervisor note */}
      {stats?.comment && (
        <div className="sys-as-comment">
          <div className="sys-as-comment-label">SUPERVISOR NOTE</div>
          <div className="sys-as-comment-text">{stats.comment}</div>
        </div>
      )}
      {!stats?.comment && !hasSupData && !isInsufficient && (
        <div className="sys-as-no-sup">No supervisor audit yet.</div>
      )}
    </div>
  )
}

// ── SupervisorCard — horizontal bar: health + summary + agent verdicts ────
function SupervisorCard({ supervisor, supervisorLogs, stats }) {
  if (!supervisor) {
    return (
      <div className="sys-sup-bar sys-sup-bar--empty">
        <span className="sys-as-badge" style={{ background: "#b0a090" }}>07</span>
        <span className="sys-sup-bar-name">Supervisor</span>
        <span className="sys-sup-bar-msg">No audit yet — run <code>python run.py supervise</code></span>
      </div>
    )
  }

  const health   = supervisor.overall_health || "unknown"
  const hColor   = { stable: "#7fa87a", degrading: "#c8a96e", critical: "#c0533a", unknown: "#b0a090" }[health]
  const summary  = supervisor.summary || ""
  const ps       = supervisor.pipeline_stats || {}
  const agentOrder = ["scanner", "collector", "classifier", "matcher", "connector", "analyst", "verifier"]
  const trendIcon  = { improving: "↑", stable: "→", degrading: "↓", insufficient_data: "?" }
  const trendColor = { improving: "#7fa87a", stable: "#8a7a60", degrading: "#c0533a", insufficient_data: "#b0a090" }

  return (
    <div className="sys-sup-bar" style={{ borderLeftColor: hColor }}>

      {/* Left: badge + health + summary */}
      <div className="sys-sup-bar-left">
        <div className="sys-sup-bar-identity">
          <span className="sys-as-badge" style={{ background: hColor }}>07</span>
          <span className="sys-sup-bar-name">Supervisor</span>
          <span className="sys-sup-health-chip" style={{ color: hColor, background: hColor + "18", borderColor: hColor + "50" }}>
            {health.toUpperCase()}
          </span>
          {stats?.lastRun && (
            <span className="sys-sup-bar-ago">{timeAgo(stats.lastRun.run_at)}</span>
          )}
        </div>
        {summary && (
          <div className="sys-sup-bar-summary">{summary}</div>
        )}
      </div>

      {/* Divider */}
      <div className="sys-sup-bar-divider" />

      {/* Right: agent verdicts in a row */}
      <div className="sys-sup-bar-verdicts">
        {agentOrder.map(agent => {
          const agPs = ps[agent]
          if (!agPs) return null
          const verdict = agPs.verdict || "unknown"
          const color   = trendColor[verdict] || "#b0a090"
          const icon    = trendIcon[verdict]  || "·"
          const score   = agPs.score != null ? agPs.score : null
          return (
            <div key={agent} className="sys-sup-bar-agent">
              <span className="sys-sup-bar-agent-name">{agent}</span>
              <span className="sys-sup-bar-agent-score" style={{ color }}>
                {score !== null ? score : "—"}
              </span>
              <span className="sys-sup-bar-agent-icon" style={{ color }}>{icon}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Supervisor panel (legacy, kept for reference) ─────────────────────────────
// ── Supervisor panel ──────────────────────────────────────────────────────────
function SupervisorPanel({ supervisor }) {
  if (!supervisor) return (
    <div className="sys-supervisor-empty">
      No supervisor report available. Run <code>python run.py supervise</code>
    </div>
  )

  const stats = supervisor.pipeline_stats || {}
  const issues = [
    ...(supervisor.match_issues         || []).map(i => ({ ...i, cat: "match" })),
    ...(supervisor.country_issues        || []).map(i => ({ ...i, cat: "country" })),
    ...(supervisor.anomalies             || []).map(i => ({ ...i, cat: "anomaly" })),
    ...(supervisor.resolution_candidates || []).map(i => ({ ...i, cat: "resolution" })),
  ]

  const metrics = [
    {
      label: "Match Issues",
      value: (supervisor.match_issues || []).length,
      good: v => v === 0,
      warn: v => v <= 3,
    },
    {
      label: "Country Issues",
      value: (supervisor.country_issues || []).length,
      good: v => v === 0,
      warn: v => v <= 2,
    },
    {
      label: "Data Anomalies",
      value: (supervisor.anomalies || []).length,
      good: v => v === 0,
      warn: v => v <= 2,
    },
    {
      label: "Early Resolution",
      value: (supervisor.resolution_candidates || []).length,
      good: v => v === 0,
      warn: v => v <= 3,
    },
    {
      label: "Classification Rate",
      value: stats.classification_rate != null ? `${(stats.classification_rate * 100).toFixed(0)}%` : "—",
      good: () => (stats.classification_rate || 0) >= 0.8,
      warn: () => (stats.classification_rate || 0) >= 0.5,
    },
    {
      label: "Match Rate",
      value: stats.match_rate != null ? `${(stats.match_rate * 100).toFixed(0)}%` : "—",
      good: () => (stats.match_rate || 0) >= 0.7,
      warn: () => (stats.match_rate || 0) >= 0.4,
    },
    {
      label: "Orphan Events",
      value: stats.orphan_events ?? "—",
      good: v => v === 0,
      warn: v => v <= 5,
    },
    {
      label: "Articles (7d)",
      value: stats.articles_last_7d ?? "—",
      good: v => v > 20,
      warn: v => v > 5,
    },
  ]

  return (
    <div className="sys-supervisor">
      <div className="sys-supervisor-header">
        <div className="sys-supervisor-date">Last audit: {fmtDate(supervisor.run_at)}</div>
        <div className="sys-supervisor-counts">
          <span style={{ color: "#c0533a" }}>{issues.filter(i => i.cat === "match" || i.cat === "anomaly").length} critical</span>
          <span style={{ color: "#a0926a" }}>{issues.filter(i => i.cat === "country" || i.cat === "resolution").length} warnings</span>
        </div>
      </div>

      {/* Metrics grid */}
      <div className="sys-metrics-grid">
        {metrics.map(m => {
          const isGood = m.good(m.value)
          const isWarn = !isGood && m.warn(m.value)
          const color  = isGood ? "#7fa87a" : isWarn ? "#c8a96e" : "#c0533a"
          return (
            <div key={m.label} className="sys-metric" style={{ "--mc": color }}>
              <div className="sys-metric-val" style={{ color }}>{m.value}</div>
              <div className="sys-metric-label">{m.label}</div>
              <div className="sys-metric-bar">
                <div className="sys-metric-bar-fill" style={{ background: color }} />
              </div>
            </div>
          )
        })}
      </div>

      {issues.length > 0 && (
        <div className="sys-issues-list">
          <div className="sys-section-label">ISSUES DETECTED</div>
          {issues.slice(0, 10).map((iss, i) => (
            <div key={i} className={`sys-issue sys-issue--${iss.cat}`}>
              <span className="sys-issue-cat">{iss.cat}</span>
              <span className="sys-issue-name">{iss.crisis_name || iss.name || "?"}</span>
              <span className="sys-issue-desc">
                {iss.issue || iss.description || iss.reason || ""}
              </span>
            </div>
          ))}
          {issues.length > 10 && (
            <div className="sys-issues-more">+{issues.length - 10} more</div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Totals strip ──────────────────────────────────────────────────────────────
function TotalsStrip({ totals }) {
  return (
    <div className="sys-totals">
      {[
        { label: `Pipeline runs (${DAYS}d)`,  val: totals.runs },
        { label: "Execution errors",           val: totals.errors,    warn: totals.errors > 0 },
        { label: "LLM cost (USD)",             val: fmtCost(totals.cost) },
        { label: "Data quality issues",        val: totals.valErrors, warn: totals.valErrors > 0 },
        { label: "Hard validation fails",      val: totals.hardFails, warn: totals.hardFails > 0 },
      ].map(({ label, val, warn }) => (
        <div key={label} className="sys-total-item">
          <div className="sys-total-val" style={warn && val > 0 ? { color: "#c0533a" } : {}}>
            {val}
          </div>
          <div className="sys-total-label">{label}</div>
        </div>
      ))}
    </div>
  )
}

// ── Charts section ────────────────────────────────────────────────────────────
function ChartsSection({ days }) {
  const [active, setActive] = useState("runs")
  const tabs = [
    { key: "runs",   label: "Runs/day",    color: "#c8a96e" },
    { key: "errors", label: "Errors",      color: "#c0533a" },
    { key: "cost",   label: "Cost ($)",    color: "#7fa87a" },
    { key: "tokens", label: "Tokens",     color: "#8ab4c8" },
  ]
  const tab = tabs.find(t => t.key === active)

  return (
    <div className="sys-charts">
      <div className="sys-chart-tabs">
        {tabs.map(t => (
          <button
            key={t.key}
            className={`sys-chart-tab ${active === t.key ? "active" : ""}`}
            onClick={() => setActive(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="sys-chart-wrap">
        <TrendBarChart days={days} field={tab.key} color={tab.color} height={80} />
        <div className="sys-chart-labels">
          {days.filter((_, i) => i % 2 === 0).map(d => (
            <span key={d.date} className="sys-chart-label">{d.label}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function SystemPage() {
  const { data, loading, error, reload } = useSystemData()
  const [reloading, setReloading] = useState(false)
  const [tab, setTab] = useState("monitor")  // "monitor" | "schema"

  // FIX scroll: html/body/#root have overflow:hidden for the map.
  // Force overflow:auto for the duration of SystemPage.
  useEffect(() => {
    const root = document.getElementById("root")
    const html = document.documentElement
    const body = document.body
    const prevHtml = html.style.overflow
    const prevBody = body.style.overflow
    const prevRoot = root ? root.style.overflow : ""
    html.style.overflow  = "auto"
    body.style.overflow  = "auto"
    if (root) root.style.overflow = "auto"
    return () => {
      html.style.overflow  = prevHtml
      body.style.overflow  = prevBody
      if (root) root.style.overflow = prevRoot
    }
  }, [])

  const handleReload = async () => {
    setReloading(true)
    await reload()
    setReloading(false)
  }

  return (
    <div className="sys-root">
      {/* Header */}
      <div className="sys-topbar">
        <div className="sys-topbar-left">
          <a href="#" className="sys-back" onClick={e => { e.preventDefault(); window.location.hash = "" }}>← MAP</a>
          <div>
            <div className="sys-topbar-title">
              <span className="sys-logo-dot" />
              SYSTEM MONITOR
            </div>
            <div className="sys-topbar-sub">Pipeline health · Last {DAYS} days</div>
          </div>
        </div>

        <div className="sys-topbar-center">
          <button
            className={`sys-maintab ${tab === "monitor" ? "active" : ""}`}
            onClick={() => setTab("monitor")}
          >
            <span className="sys-maintab-icon">◉</span>
            <span className="sys-maintab-label">MONITOR</span>
          </button>
          <div className="sys-maintab-divider" />
          <button
            className={`sys-maintab ${tab === "schema" ? "active" : ""}`}
            onClick={() => setTab("schema")}
          >
            <span className="sys-maintab-icon">⬡</span>
            <span className="sys-maintab-label">ARCHITECTURE</span>
          </button>
        </div>

        <div className="sys-topbar-right">
          <button
            className={`sys-reload-btn ${reloading ? "spinning" : ""}`}
            onClick={handleReload}
            disabled={reloading || tab !== "monitor"}
            style={{ opacity: tab !== "monitor" ? 0.3 : 1 }}
          >↻ Refresh</button>
        </div>
      </div>

      {tab === "schema" && <SchemaTab />}

      <div className="sys-body" style={{ display: tab === "monitor" ? undefined : "none" }}>
        {loading && (
          <div className="sys-loading">
            <div className="sys-loading-dot" />
            Loading data...
          </div>
        )}

        {error && (
          <div className="sys-error">
            Error loading data: {error}
            <br />
            <small>Make sure the <code>cm_agent_runs</code> table exists in the DB.</small>
          </div>
        )}

        {data && (
          <>
            {/* Supervisor — replaces trend chart, above agents */}
            <section className="sys-section">
              <div className="sys-section-title">SUPERVISOR REPORT</div>
              <SupervisorCard supervisor={data.supervisor} supervisorLogs={data.supervisorLogs} stats={data.agentStats["supervisor"]} />
            </section>

            {/* Agents — griglia 3 colonne */}
            <section className="sys-section">
              <div className="sys-section-title">AGENT PERFORMANCE — LAST {DAYS} DAYS</div>
              <div className="sys-agents-grid">
                {AGENTS.filter(ag => ag.key !== "supervisor").map(ag => (
                  <AgentSection
                    key={ag.key}
                    agent={ag}
                    stats={data.agentStats[ag.key]}
                  />
                ))}
              </div>
            </section>
          </>
        )}
      </div>

      <style>{`
        /* ── Root ── */
        .sys-root {
          min-height: 100vh;
          background: #f5f0e8;
          font-family: 'DM Sans', sans-serif;
          color: #2a2118;
        }

        /* ── Topbar ── */
        .sys-topbar {
          display: grid;
          grid-template-columns: 1fr auto 1fr;
          align-items: center;
          padding: 0 28px;
          height: 56px;
          background: #ede7da;
          border-bottom: 1px solid #d4c9b5;
          position: sticky;
          top: 0;
          z-index: 100;
        }
        .sys-topbar-left {
          display: flex;
          align-items: center;
          gap: 20px;
        }
        .sys-back {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          letter-spacing: 0.12em;
          color: #8a7a60;
          text-decoration: none;
          padding: 4px 8px;
          border: 1px solid #c8b89a;
          border-radius: 3px;
          transition: all 0.15s;
        }
        .sys-back:hover { color: #2a2118; border-color: #8a7a60; }
        .sys-logo-dot {
          width: 7px; height: 7px;
          border-radius: 50%;
          background: #c8a96e;
          display: inline-block;
          margin-right: 8px;
          box-shadow: 0 0 6px #c8a96e88;
        }
        .sys-topbar-title {
          font-family: 'Space Mono', monospace;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.18em;
          color: #2a2118;
        }
        .sys-topbar-sub {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          color: #8a7a60;
          letter-spacing: 0.08em;
        }
        .sys-reload-btn {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          letter-spacing: 0.1em;
          background: none;
          border: 1px solid #c8b89a;
          color: #8a7a60;
          padding: 5px 12px;
          border-radius: 3px;
          cursor: pointer;
          transition: all 0.15s;
        }
        .sys-reload-btn:hover { color: #2a2118; border-color: #8a7a60; }
        .sys-reload-btn.spinning { animation: sys-spin 0.8s linear infinite; }
        @keyframes sys-spin { to { transform: rotate(360deg); } }

        /* ── Body ── */
        .sys-body {
          max-width: 1200px;
          margin: 0 auto;
          padding: 28px 24px 60px;
        }

        /* ── Loading / Error ── */
        .sys-loading {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 60px 0;
          color: #8a7a60;
          font-family: 'Space Mono', monospace;
          font-size: 11px;
        }
        .sys-loading-dot {
          width: 8px; height: 8px;
          border-radius: 50%;
          background: #c8a96e;
          animation: sys-pulse 1s ease-in-out infinite;
        }
        @keyframes sys-pulse {
          0%, 100% { opacity: 0.3; transform: scale(0.8); }
          50%       { opacity: 1;   transform: scale(1.1); }
        }
        .sys-error {
          padding: 20px;
          background: #f5e8e4;
          border: 1px solid #c0533a44;
          border-radius: 6px;
          color: #c0533a;
          font-size: 12px;
        }

        /* ── Totals strip ── */
        .sys-totals {
          display: flex;
          gap: 0;
          background: #ede7da;
          border: 1px solid #d4c9b5;
          border-radius: 6px;
          overflow: hidden;
          margin-bottom: 28px;
        }
        .sys-total-item {
          flex: 1;
          padding: 16px 20px;
          border-right: 1px solid #d4c9b5;
          text-align: center;
        }
        .sys-total-item:last-child { border-right: none; }
        .sys-total-val {
          font-family: 'Space Mono', monospace;
          font-size: 20px;
          font-weight: 700;
          color: #2a2118;
          line-height: 1.2;
        }
        .sys-total-label {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #8a7a60;
          letter-spacing: 0.1em;
          margin-top: 4px;
          text-transform: uppercase;
        }

        /* ── Sections ── */
        .sys-section {
          margin-bottom: 32px;
        }
        .sys-section-title {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          letter-spacing: 0.2em;
          color: #8a7a60;
          margin-bottom: 14px;
          padding-bottom: 6px;
          border-bottom: 1px solid #d4c9b5;
        }
        .sys-section-label {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          letter-spacing: 0.15em;
          color: #8a7a60;
          margin-bottom: 10px;
        }

        /* ── Charts ── */
        .sys-charts {
          background: #ede7da;
          border: 1px solid #d4c9b5;
          border-radius: 6px;
          padding: 16px 20px;
        }
        .sys-chart-tabs {
          display: flex;
          gap: 6px;
          margin-bottom: 16px;
        }
        .sys-chart-tab {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          letter-spacing: 0.1em;
          padding: 4px 10px;
          border-radius: 3px;
          border: 1px solid #d4c9b5;
          background: none;
          color: #8a7a60;
          cursor: pointer;
          transition: all 0.15s;
        }
        .sys-chart-tab.active,
        .sys-chart-tab:hover {
          background: #f5f0e8;
          color: #2a2118;
          border-color: #8a7a60;
        }
        .sys-chart-wrap {
          position: relative;
        }
        .sys-chart-labels {
          display: flex;
          justify-content: space-between;
          margin-top: 6px;
        }
        .sys-chart-label {
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          color: #a09080;
        }

        /* ── Agents grid ── */
        .sys-agents-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
          gap: 14px;
        }
        @media (min-width: 1200px) {
          .sys-agents-grid {
            grid-template-columns: repeat(4, 1fr);
          }
        }

        /* ── Agent sections (new per-agent timeline layout) ── */
        .sys-agents-list {
          display: flex;
          flex-direction: column;
          gap: 14px;
        }
        .sys-agent-section {
          background: #ede7da;
          border: 1px solid #d4c9b5;
          border-left: 4px solid var(--agent-color, #d4c9b5);
          border-radius: 8px;
          padding: 16px 20px;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        .sys-agent-section:hover {
          box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .sys-as-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
          flex-wrap: wrap;
          gap: 8px;
          padding-bottom: 10px;
          border-bottom: 1px solid #d4c9b5;
        }
        .sys-as-left {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .sys-as-badge {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #fff;
          padding: 2px 6px;
          border-radius: 3px;
          font-weight: 700;
          letter-spacing: 0.05em;
        }
        .sys-as-name {
          font-size: 15px;
          font-weight: 700;
          color: #2a2118;
        }
        .sys-as-insufficient {
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          letter-spacing: 0.08em;
          color: #b8860b;
          background: rgba(184, 134, 11, 0.1);
          border: 1px solid rgba(184, 134, 11, 0.3);
          padding: 2px 6px;
          border-radius: 3px;
          font-weight: 600;
          margin-left: auto;
        }
        .sys-as-desc {
          font-size: 10px;
          color: #8a7a60;
        }
        .sys-as-stats {
          display: flex;
          gap: 18px;
          align-items: center;
          flex-wrap: wrap;
        }
        .sys-as-stat {
          text-align: center;
          min-width: 44px;
        }
        .sys-as-stat-val {
          font-family: 'Space Mono', monospace;
          font-size: 13px;
          font-weight: 700;
          color: #2a2118;
          line-height: 1;
        }
        .sys-as-stat-lbl {
          font-family: 'Space Mono', monospace;
          font-size: 6px;
          color: #8a7a60;
          letter-spacing: 0.1em;
          margin-top: 2px;
        }
        .sys-as-charts {
          display: flex;
          gap: 16px;
          padding-top: 4px;
        }
        .mini-chart-label {
          font-family: 'Space Mono', monospace;
          font-size: 7.5px;
          color: #6a5a48;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin-bottom: 4px;
          font-weight: 600;
        }
        .mini-chart-footer {
          display: flex;
          justify-content: space-between;
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          color: #a09080;
          margin-top: 3px;
          padding: 0 2px;
        }
        .mini-chart-total {
          color: #4a3f30;
          font-weight: 700;
        }
        @media (max-width: 700px) {
          .sys-as-header { flex-direction: column; align-items: flex-start; }
          .sys-as-charts { flex-direction: column; gap: 8px; }
        }
        .sys-agent-card {
          background: #ede7da;
          border: 1px solid #d4c9b5;
          border-top: 2px solid var(--status-col, #d4c9b5);
          border-radius: 6px;
          padding: 14px 16px;
          transition: box-shadow 0.15s;
        }
        .sys-agent-card:hover {
          box-shadow: 0 4px 16px rgba(0,0,0,0.08);
        }
        .sys-agent-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 6px;
        }
        .sys-agent-label {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #8a7a60;
          letter-spacing: 0.1em;
        }
        .sys-agent-status {
          display: flex;
          align-items: center;
          gap: 5px;
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #8a7a60;
        }
        .sys-agent-status.success { color: #7fa87a; }
        .sys-agent-status.error   { color: #c0533a; }
        .sys-agent-status.skipped { color: #a0926a; }
        .sys-status-dot {
          width: 5px; height: 5px;
          border-radius: 50%;
          background: currentColor;
          flex-shrink: 0;
        }
        .sys-agent-name {
          font-size: 14px;
          font-weight: 700;
          color: #2a2118;
          margin-bottom: 2px;
        }
        .sys-agent-desc {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #a09080;
          margin-bottom: 12px;
        }
        /* ── Agent stats grid (6 boxes) ── */
        .sys-agent-stats {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 1px;
          background: #d4c9b5;
          border: 1px solid #d4c9b5;
          border-radius: 5px;
          overflow: hidden;
          margin-bottom: 10px;
        }
        .sys-stat-box {
          background: #f5f0e8;
          padding: 8px 10px;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .sys-stat-val {
          font-family: 'Space Mono', monospace;
          font-size: 13px;
          font-weight: 700;
          color: #2a2118;
          line-height: 1;
        }
        .sys-stat-lbl {
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          color: #a09080;
          letter-spacing: 0.08em;
          text-transform: uppercase;
        }
        /* ── Inline bar chart ── */
        .sys-agent-chart {
          margin-bottom: 8px;
        }
        .sys-chart-label-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          color: #a09080;
          letter-spacing: 0.06em;
          margin-bottom: 4px;
        }
        .sys-chart-legend {
          display: flex;
          gap: 8px;
          align-items: center;
        }
        .sys-legend-item {
          display: flex;
          align-items: center;
          gap: 3px;
          font-size: 7px;
          color: #a09080;
        }
        .sys-legend-dot {
          width: 6px;
          height: 6px;
          border-radius: 1px;
          display: inline-block;
          opacity: 0.7;
        }
        /* ── Footer ── */
        .sys-agent-footer {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #a09080;
        }
        .sys-agent-footer strong {
          color: #6a5a48;
        }
        .sys-agent-error {
          margin-top: 6px;
          padding: 5px 8px;
          background: #f5e8e4;
          border-radius: 3px;
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #c0533a;
          word-break: break-all;
        }
        .sys-agent-nodata {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          color: #a09080;
          padding: 12px 0;
          text-align: center;
        }
        /* ── Supervisor card extras ── */
        .sys-supervisor-card {
          grid-column: 1 / -1;
        }
        .sys-sup-empty {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          color: #a09080;
          padding: 14px 0;
          line-height: 1.7;
        }
        .sys-sup-empty code {
          background: #f5f0e8;
          padding: 1px 5px;
          border-radius: 3px;
          border: 1px solid #d4c9b5;
        }
        .sys-sup-issues {
          margin-top: 4px;
          border-top: 1px solid #d4c9b5;
          padding-top: 8px;
        }
        .sys-sup-issue {
          display: grid;
          grid-template-columns: 72px 1fr;
          gap: 6px 10px;
          padding: 4px 0;
          border-bottom: 1px solid #e8e0d2;
          font-size: 10px;
          align-items: baseline;
        }
        .sys-sup-cat {
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: #8a7a60;
        }
        .sys-sup-issue--match .sys-sup-cat    { color: #c0533a; }
        .sys-sup-issue--anomaly .sys-sup-cat  { color: #c0533a; }
        .sys-sup-issue--country .sys-sup-cat  { color: #a0926a; }
        .sys-sup-issue--resolution .sys-sup-cat { color: #7fa87a; }
        .sys-sup-name {
          font-weight: 600;
          color: #2a2118;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sys-sup-desc {
          grid-column: 2;
          color: #6a5a48;
          font-size: 9px;
        }
        .sys-sup-more {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #8a7a60;
          padding-top: 6px;
        }
        .sys-sup-ok {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          color: #7fa87a;
          padding: 10px 0 4px;
        }
        .sys-sup-summary {
          font-size: 10px;
          color: #4a3f30;
          line-height: 1.6;
          margin: 8px 0;
          padding: 8px 10px;
          border-left: 3px solid #d4c9b5;
          background: rgba(0,0,0,0.02);
          border-radius: 0 4px 4px 0;
        }
        .sys-sup-verdicts {
          margin-top: 8px;
          border-top: 1px solid #d4c9b5;
          padding-top: 8px;
        }
        .sys-sup-section-label {
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          color: #8a7a60;
          letter-spacing: 0.12em;
          text-transform: uppercase;
          margin-bottom: 6px;
        }
        .sys-sup-verdict-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
          gap: 4px 12px;
        }
        .sys-sup-verdict-item {
          display: flex;
          align-items: baseline;
          gap: 5px;
          padding: 3px 0;
          font-size: 10px;
          border-bottom: 1px solid #e8e0d2;
        }
        .sys-sup-verdict-icon {
          font-size: 12px;
          font-weight: 700;
          flex-shrink: 0;
          width: 14px;
          text-align: center;
        }
        .sys-sup-verdict-name {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          font-weight: 600;
          color: #2a2118;
          min-width: 70px;
        }
        .sys-sup-verdict-score {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          font-weight: 700;
          min-width: 20px;
        }
        .sys-sup-verdict-note {
          font-size: 9px;
          color: #6a5a48;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .sys-sup-health-badge {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          font-weight: 700;
          letter-spacing: 0.1em;
          padding: 2px 8px;
          border-radius: 3px;
          border: 1px solid;
        }

        .sys-supervisor {
          background: #ede7da;
          border: 1px solid #d4c9b5;
          border-radius: 6px;
          padding: 20px 24px;
        }
        .sys-supervisor-empty {
          padding: 20px;
          font-family: 'Space Mono', monospace;
          font-size: 10px;
          color: #a09080;
          background: #ede7da;
          border: 1px solid #d4c9b5;
          border-radius: 6px;
        }
        .sys-supervisor-empty code {
          background: #f5f0e8;
          padding: 1px 5px;
          border-radius: 3px;
          border: 1px solid #d4c9b5;
        }
        .sys-supervisor-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 16px;
        }
        .sys-supervisor-date {
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          color: #8a7a60;
        }
        .sys-supervisor-counts {
          display: flex;
          gap: 14px;
          font-family: 'Space Mono', monospace;
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.06em;
        }
        .sys-metrics-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 1px;
          background: #d4c9b5;
          border: 1px solid #d4c9b5;
          border-radius: 6px;
          overflow: hidden;
          margin-bottom: 20px;
        }
        .sys-metric {
          background: #f5f0e8;
          padding: 14px 16px;
          position: relative;
        }
        .sys-metric-val {
          font-family: 'Space Mono', monospace;
          font-size: 22px;
          font-weight: 700;
          line-height: 1;
          margin-bottom: 4px;
        }
        .sys-metric-label {
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          color: #8a7a60;
          letter-spacing: 0.1em;
          text-transform: uppercase;
        }
        .sys-metric-bar {
          position: absolute;
          bottom: 0; left: 0; right: 0;
          height: 2px;
          background: #d4c9b5;
        }
        .sys-metric-bar-fill {
          height: 100%;
          width: 100%;
          opacity: 0.6;
        }
        .sys-issues-list {
          margin-bottom: 16px;
        }
        .sys-issue {
          display: grid;
          grid-template-columns: 70px 160px 1fr;
          gap: 8px;
          align-items: baseline;
          padding: 5px 0;
          border-bottom: 1px solid #d4c9b5;
          font-size: 11px;
        }
        .sys-issue-cat {
          font-family: 'Space Mono', monospace;
          font-size: 7px;
          letter-spacing: 0.08em;
          color: #8a7a60;
          text-transform: uppercase;
        }
        .sys-issue--match .sys-issue-cat    { color: #c0533a; }
        .sys-issue--anomaly .sys-issue-cat  { color: #c0533a; }
        .sys-issue--country .sys-issue-cat  { color: #a0926a; }
        .sys-issue--resolution .sys-issue-cat { color: #7fa87a; }
        .sys-issue-name {
          font-weight: 600;
          color: #2a2118;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sys-issue-desc {
          color: #6a5a48;
          font-size: 10px;
        }
        .sys-issues-more {
          font-family: 'Space Mono', monospace;
          font-size: 8px;
          color: #8a7a60;
          padding-top: 6px;
        }
        .sys-recs { margin-top: 12px; }
        .sys-rec {
          font-size: 11px;
          color: #4a3c2c;
          padding: 4px 0;
          line-height: 1.5;
        }

        /* ── Topbar layout ── */
        .sys-topbar {
          display: grid !important;
          grid-template-columns: 1fr auto 1fr !important;
          align-items: center !important;
        }
        .sys-topbar-center {
          display: flex;
          align-items: center;
          gap: 0;
          background: #e0d8cb;
          border: 1px solid #c8b89a;
          border-radius: 6px;
          padding: 3px;
        }
        .sys-topbar-right {
          display: flex;
          justify-content: flex-end;
        }
        .sys-maintab {
          display: flex;
          align-items: center;
          gap: 7px;
          padding: 7px 20px;
          background: transparent;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.18s;
          font-family: 'Space Mono', monospace;
          color: #8a7a60;
        }
        .sys-maintab:hover {
          background: #ede7da;
          color: #2a2118;
        }
        .sys-maintab.active {
          background: #f5f0e8;
          color: #2a2118;
          box-shadow: 0 1px 4px rgba(0,0,0,0.10);
        }
        .sys-maintab-icon {
          font-size: 14px;
          line-height: 1;
        }
        .sys-maintab-label {
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.18em;
        }
        .sys-maintab-divider {
          width: 1px;
          height: 20px;
          background: #c8b89a;
          margin: 0 2px;
        }

        /* ── Schema split layout ── */
        .schema-split {
          display: grid;
          grid-template-columns: 1fr 340px;
          gap: 24px;
          align-items: start;
        }
        .schema-split-left {
          min-width: 0;
        }
        .schema-split-right {
          position: sticky;
          top: 72px;
        }
        .schema-detail-placeholder {
          background: #ede7da;
          border: 1px dashed #c8b89a;
          border-radius: 8px;
          padding: 40px 24px;
          text-align: center;
        }
        .schema-placeholder-icon {
          font-size: 32px;
          color: #c8b89a;
          margin-bottom: 14px;
          opacity: 0.6;
        }
        .schema-placeholder-title {
          font-family: 'Space Mono', monospace;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.12em;
          color: #8a7a60;
          margin-bottom: 10px;
          text-transform: uppercase;
        }
        .schema-placeholder-sub {
          font-size: 11px;
          color: #a09080;
          line-height: 1.6;
        }
      `}</style>
    </div>
  )
}

// ── AgentSchema embedded as SchemaTab ──────────────────────────────────────

/**
 * AgentSchema.jsx — System Architecture page for Crisis Monitor
 * 
 * Interactive diagram showing all 7 agents, 3 validators,
 * data flow, and DB tables. Matches the existing design system.
 */

// ── Agent data ───────────────────────────────────────────────────────────────

const SCHEMA_AGENTS = [
  {
    id: "00", name: "Scanner", subtitle: "Web Search → New Crises",
    model: "Sonnet + Web Search", schedule: "Weekly / Bootstrap",
    desc: "Searches the web for active crises worldwide. ValidatorC filters results (temporal + Haiku LLM). SeedWriter persists to DB. Decoupled — Connector runs separately after.",
    inputs: ["Anthropic Web Search", "RAG (early warning)"],
    outputs: ["crises", "key_timeline", "crisis_events"],
    group: "discovery", color: "#8b5cf6",
  },
  {
    id: "01", name: "Collector", subtitle: "GNews API → Raw Articles",
    model: "None (Python)", schedule: "Every 6h",
    desc: "Fetches news from GNews across 5 query categories. Pure HTTP, no LLM. Deduplicates by gnews_id. ~40 articles per run.",
    inputs: ["GNews API (5 queries)"],
    outputs: ["raw_articles"],
    group: "pipeline", color: "#4a90d9",
  },
  {
    id: "02", name: "Classifier", subtitle: "Article → Structured Event",
    model: "Haiku + Sonnet audit", schedule: "Every 6h",
    desc: "Classifies raw articles into crisis events: type, severity 1-10, countries, geolocation. Batches of 15. Each batch audited by Sonnet before save.",
    inputs: ["raw_articles (status='new')"],
    outputs: ["classified_events"],
    group: "pipeline", color: "#e8960a",
  },
  {
    id: "03", name: "Matcher", subtitle: "Event → Crisis Link",
    model: "Sonnet + Sonnet audit", schedule: "Every 6h",
    desc: "Links events to existing crises or creates new ones. Independence check — country overlap alone isn't enough. Status normalized, country merge capped at 20.",
    inputs: ["classified_events (validated)", "crises (active)"],
    outputs: ["crisis_events", "crises (update/create)"],
    group: "pipeline", color: "#7c3aed",
  },
  {
    id: "04", name: "Connector", subtitle: "Country ↔ Country Links",
    model: "Haiku + Sonnet audit", schedule: "Every 6h",
    desc: "Detects geopolitical relationships: military attacks, sanctions, aid, refugee flows, alliances. Full regeneration — diffs each run. 8 relation types.",
    inputs: ["crises (active)"],
    outputs: ["connections"],
    group: "pipeline", color: "#0891b2",
  },
  {
    id: "05", name: "Analyst", subtitle: "Deep Intelligence Analysis",
    model: "Sonnet + RAG", schedule: "Daily, severity ≥ 7",
    desc: "Deep analysis: evolution scenarios, historical precedents, key actors, watch indicators. Max 3 crises/run. Only re-analyzes crises with new events. Quality audited by Sonnet (rejects score <5).",
    inputs: ["crises", "crisis_events", "connections", "key_timeline", "RAG"],
    outputs: ["analyses", "key_timeline"],
    group: "analysis", color: "#c0533a",
  },
  {
    id: "06", name: "Verifier", subtitle: "Monthly Status Check",
    model: "Sonnet + Web Search + RAG", schedule: "Monthly, max 3/day",
    desc: "Verifies crisis status via fresh web search. Detects resolutions, escalations, media gaps. Uses Fink/PCMP crisis stage frameworks. 60s delay between verifications.",
    inputs: ["crises (not verified 30d)", "Web Search", "RAG"],
    outputs: ["verification_log", "crises (status update)"],
    group: "analysis", color: "#16a34a",
  },
  {
    id: "07", name: "Supervisor", subtitle: "Pipeline Meta-Auditor",
    model: "Python + Sonnet", schedule: "After full run",
    desc: "System-level audit. Python computes metrics from 30d of agent runs, one Sonnet call finds systemic patterns: drift, correlations, cost anomalies, cold starts. Scores all 7 agents.",
    inputs: ["cm_agent_runs (30d)", "crises", "validation_errors"],
    outputs: ["cm_supervisor_log (health, scores, findings)"],
    group: "monitoring", color: "#b8720a",
  },
]

const VALIDATORS = [
  {
    id: "A", name: "Validator A", position: "After Classifier",
    desc: "Python checks: required fields, ISO-2 country codes, severity 1-10, valid crisis type. Hard fail → event blocked from Matcher.",
    type: "Python only", severity: "Hard fail → event rejected",
  },
  {
    id: "B", name: "Validator B", position: "After Matcher",
    desc: "Duplicate detection (country+type+name similarity >80%), auto-merge confirmed duplicates, orphan events, date coherence, severity peak consistency.",
    type: "Python only", severity: "Hard fail on duplicates → auto-merge",
  },
  {
    id: "C", name: "Validator C", position: "Inside Scanner",
    desc: "Two-stage filter: temporal (reject crises >90 days stale) + Haiku LLM reality check (reject historical, speculative, resolved).",
    type: "Temporal + LLM (Haiku)", severity: "Rejects non-active crises",
  },
]

const DB_TABLES = [
  { name: "raw_articles", desc: "GNews articles", agent: "01" },
  { name: "classified_events", desc: "Structured events", agent: "02/03" },
  { name: "crises", desc: "Active crises", agent: "00/03/06" },
  { name: "crisis_events", desc: "Event↔crisis links", agent: "00/03/06" },
  { name: "connections", desc: "Country relationships", agent: "04" },
  { name: "analyses", desc: "Deep analysis reports", agent: "05" },
  { name: "key_timeline", desc: "Crisis turning points", agent: "00/05" },
  { name: "verification_log", desc: "Verification results", agent: "06" },
  { name: "validation_errors", desc: "Validator issues", agent: "A/B" },
  { name: "cm_agent_runs", desc: "Agent run tracking", agent: "all" },
  { name: "cm_supervisor_log", desc: "Pipeline health audits", agent: "07" },
  { name: "cm_collection_log", desc: "Collection metadata", agent: "01" },
]

const PIPELINE_FLOW = [
  { from: "01", to: "02", label: "raw_articles" },
  { from: "02", to: "A", label: "" },
  { from: "A", to: "03", label: "passed events" },
  { from: "03", to: "B", label: "" },
  { from: "B", to: "04", label: "" },
]

// ── Component ────────────────────────────────────────────────────────────────

function SchemaTab() {
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [selectedValidator, setSelectedValidator] = useState(null)

  const agent = SCHEMA_AGENTS.find(a => a.id === selectedAgent)

  const handleSelectAgent = (id) => {
    setSelectedAgent(id === selectedAgent ? null : id)
    setSelectedValidator(null)
  }

  const handleSelectValidator = (id) => {
    setSelectedValidator(id === selectedValidator ? null : id)
    setSelectedAgent(null)
  }

  return (
    <div className="schema-page">

      {/* Header */}
      <div className="schema-header">
        <div className="schema-header-left">
          <a href="#" className="schema-back" onClick={e => { e.preventDefault(); window.location.hash = "" }}>
            ← Dashboard
          </a>
          <div className="schema-title-block">
            <div className="schema-badge"><strong>CRISIS MONITOR</strong></div>
            <h1 className="schema-title"><strong>System Architecture</strong></h1>
            <div className="schema-subtitle">8 agents · 3 validators · 3 Sonnet audits · 12 DB tables · RAG + Web Search</div>
          </div>
        </div>
      </div>

      <div className="schema-body">

        {/* ═══ AGENTS + DETAIL ═══ */}
        <div className="schema-split">
          <div className="schema-split-left">

            <div className="schema-group">
              <div className="schema-group-label" style={{ color: "#8b5cf6" }}>DISCOVERY</div>
              <div className="schema-group-sub">Independent — weekly web search for new crises</div>
              <div className="schema-cards">
                {SCHEMA_AGENTS.filter(a => a.group === "discovery").map(a => (
                  <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <SchemaAgentCard agent={a} selected={selectedAgent === a.id} onClick={handleSelectAgent} />
                    <SchemaValidatorBadge v={VALIDATORS[2]} selected={selectedValidator === "C"} onClick={handleSelectValidator} />
                  </div>
                ))}
              </div>
            </div>

            <div className="schema-group">
              <div className="schema-group-label" style={{ color: "#4a90d9" }}>ENRICHMENT PIPELINE</div>
              <div className="schema-group-sub">Every 6 hours — collect → classify → validate → match → validate → connect</div>
              <div className="schema-pipeline-flow">
                {SCHEMA_AGENTS.filter(a => a.group === "pipeline").map((a, i) => (
                  <div key={a.id} className="schema-pipeline-step">
                    <SchemaAgentCard agent={a} selected={selectedAgent === a.id} onClick={handleSelectAgent} />
                    {i < 3 && <div className="schema-arrow">→</div>}
                    {a.id === "02" && <SchemaValidatorBadge v={VALIDATORS[0]} selected={selectedValidator === "A"} onClick={handleSelectValidator} />}
                    {a.id === "03" && <SchemaValidatorBadge v={VALIDATORS[1]} selected={selectedValidator === "B"} onClick={handleSelectValidator} />}
                  </div>
                ))}
              </div>
            </div>

            <div className="schema-group">
              <div className="schema-group-label" style={{ color: "#c0533a" }}>DEEP ANALYSIS</div>
              <div className="schema-group-sub">Analyst (daily, severity ≥ 7) — Verifier (monthly, max 3/day, 60s delay)</div>
              <div className="schema-cards">
                {SCHEMA_AGENTS.filter(a => a.group === "analysis").map(a => (
                  <SchemaAgentCard key={a.id} agent={a} selected={selectedAgent === a.id} onClick={handleSelectAgent} />
                ))}
              </div>
            </div>

            <div className="schema-group">
              <div className="schema-group-label" style={{ color: "#b8720a" }}>SYSTEM MONITORING</div>
              <div className="schema-group-sub">Meta-audit — scores, trends, systemic patterns across all 7 agents</div>
              <div className="schema-cards">
                {SCHEMA_AGENTS.filter(a => a.group === "monitoring").map(a => (
                  <SchemaAgentCard key={a.id} agent={a} selected={selectedAgent === a.id} onClick={handleSelectAgent} />
                ))}
              </div>
            </div>
          </div>

          <div className="schema-split-right">
            {agent
              ? <SchemaAgentDetail agent={agent} />
              : selectedValidator
                ? (() => { const v = VALIDATORS.find(x => x.id === selectedValidator); return v ? (
                    <div className="schema-detail">
                      <div className="sd-header">
                        <span className="sd-num" style={{ color: "#5a8a6a" }}>VALIDATOR {v.id}</span>
                        <span className="sd-name">{v.name}</span>
                        <span className="sd-sub">{v.position}</span>
                      </div>
                      <p className="sd-desc">{v.desc}</p>
                      <div className="sd-io">
                        <div className="sd-io-col"><div className="sd-io-label">TYPE</div><span className="sd-io-tag input">{v.type}</span></div>
                        <div className="sd-io-col"><div className="sd-io-label">SEVERITY</div><span className="sd-io-tag output">{v.severity}</span></div>
                      </div>
                    </div>
                  ) : null })()
                : <div className="schema-detail-placeholder">
                    <div className="schema-placeholder-icon">◎</div>
                    <div className="schema-placeholder-title">Select an agent</div>
                    <div className="schema-placeholder-sub">Click any agent or validator to see full details.</div>
                  </div>
            }
          </div>
        </div>

        {/* ═══ DATA FLOW ═══ */}
        <div className="schema-flow-section">
          <div className="schema-flow-title">DATA FLOW</div>
          {[
            { phase: "BOOTSTRAP / WEEKLY SCAN", color: "#8b5cf6", steps: [
              {t:"Scanner",c:"agent"},{t:"Web Search",c:"tool"},{t:"→"},{t:"ValidatorC",c:"validator"},{t:"→"},{t:"SeedWriter",c:"agent"},{t:"→"},
              {t:"crises",c:"table"},{t:"key_timeline",c:"table"},{t:"→"},{t:"Connector",c:"agent"},{t:"→"},{t:"connections",c:"table"},
            ]},
            { phase: "ENRICHMENT (EVERY 6H)", color: "#4a90d9", steps: [
              {t:"Collector",c:"agent"},{t:"→"},{t:"raw_articles",c:"table"},{t:"→"},
              {t:"Classifier",c:"agent"},{t:"Sonnet audit",c:"tool"},{t:"→"},{t:"classified_events",c:"table"},{t:"→"},
              {t:"ValidatorA",c:"validator"},{t:"→"},{t:"Matcher",c:"agent"},{t:"Sonnet audit",c:"tool"},{t:"→"},
              {t:"crisis_events",c:"table"},{t:"crises",c:"table"},{t:"→"},
              {t:"ValidatorB",c:"validator"},{t:"→"},{t:"Connector",c:"agent"},{t:"Sonnet audit",c:"tool"},{t:"→"},{t:"connections",c:"table"},
            ]},
            { phase: "ANALYSIS (DAILY) + VERIFICATION (MONTHLY)", color: "#c0533a", steps: [
              {t:"Analyst",c:"agent"},{t:"RAG",c:"tool"},{t:"Sonnet audit",c:"tool"},{t:"→"},
              {t:"analyses",c:"table"},{t:"key_timeline",c:"table"},
              {t:"│",c:"sep"},
              {t:"Verifier",c:"agent"},{t:"Web Search",c:"tool"},{t:"RAG",c:"tool"},{t:"Sonnet audit",c:"tool"},{t:"→"},
              {t:"verification_log",c:"table"},{t:"crises",c:"table"},
            ]},
            { phase: "MONITORING (AFTER FULL RUN)", color: "#b8720a", steps: [
              {t:"Supervisor",c:"agent"},{t:"←"},
              {t:"cm_agent_runs",c:"table"},{t:"crises",c:"table"},{t:"validation_errors",c:"table"},
              {t:"→"},{t:"Sonnet patterns",c:"tool"},{t:"→"},{t:"cm_supervisor_log",c:"table"},
            ]},
          ].map(({ phase, color, steps }) => (
            <div key={phase} className="schema-flow-lane">
              <div className="schema-flow-phase" style={{ color }}>{phase}</div>
              <div className="schema-flow-steps">
                {steps.map((s, i) => <span key={i} className={`schema-fs ${s.c || ""}`}>{s.t}</span>)}
              </div>
            </div>
          ))}
        </div>

        {/* ═══ DB TABLES ═══ */}
        <div className="schema-flow-section">
          <div className="schema-flow-title">DATABASE — 12 TABLES</div>
          <div className="schema-tables-grid">
            {DB_TABLES.map(t => (
              <div key={t.name} className="schema-tbl">
                <div className="schema-tbl-name">{t.name}</div>
                <div className="schema-tbl-desc">{t.desc}</div>
                <div className="schema-tbl-agent">← {t.agent}</div>
              </div>
            ))}
          </div>
        </div>

      </div>

      <style>{`
        .schema-page { margin: 0 auto; }
        .schema-header {
          display: flex; justify-content: space-between; align-items: flex-end;
          padding: 20px 0 16px; border-bottom: 1px solid #d4c9b5; margin-bottom: 28px;
        }
        .schema-header-left { display: flex; align-items: center; gap: 20px; }
        .schema-back {
          font-family: 'Space Mono', monospace; font-size: 9px; letter-spacing: 0.12em;
          color: #8a7a60; text-decoration: none; padding: 4px 8px;
          border: 1px solid #c8b89a; border-radius: 3px;
        }
        .schema-back:hover { color: #2a2118; border-color: #8a7a60; }
        .schema-badge { font-family: 'Space Mono', monospace; font-size: 9px; letter-spacing: 0.15em; color: #a07a5a; }
        .schema-title { font-size: 22px; margin: 2px 0 0; }
        .schema-subtitle { font-family: 'Space Mono', monospace; font-size: 9px; color: #8a7a60; margin-top: 3px; }
        .schema-body { padding-bottom: 40px; }

        .schema-split { display: block; }
        .schema-split-left { min-width: 0; }
        .schema-split-right { margin-top: 16px; max-width: 500px; }

        .schema-group { margin-bottom: 28px; }
        .schema-group-label { font-family: 'Space Mono', monospace; font-size: 9px; font-weight: 700; letter-spacing: 0.15em; margin-bottom: 3px; }
        .schema-group-sub { font-size: 11px; color: #8a7a60; margin-bottom: 12px; }
        .schema-cards { display: flex; flex-wrap: wrap; gap: 10px; }

        .schema-pipeline-flow { display: flex; align-items: center; gap: 6px; overflow-x: auto; padding-bottom: 4px; }
        .schema-pipeline-step { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
        .schema-arrow { font-family: 'Space Mono', monospace; font-size: 16px; color: #b0a090; }

        .schema-agent-card {
          background: #ede7da; border: 1px solid #d4c9b5; border-radius: 6px;
          padding: 10px 14px; min-width: 155px; cursor: pointer; transition: all 0.15s;
        }
        .schema-agent-card:hover { border-color: #8a7a60; }
        .schema-agent-card.selected { border-color: var(--agent-color); box-shadow: 0 0 0 2px var(--agent-color); }
        .sac-top { display: flex; align-items: center; gap: 7px; margin-bottom: 3px; }
        .sac-num { font-family: 'Space Mono', monospace; font-size: 8px; font-weight: 700; color: white; background: var(--agent-color); padding: 2px 5px; border-radius: 3px; }
        .sac-name { font-size: 13px; font-weight: 700; }
        .sac-subtitle { font-size: 9px; color: #8a7a60; margin-bottom: 6px; }
        .sac-tags { display: flex; gap: 5px; flex-wrap: wrap; }
        .sac-model { font-family: 'Space Mono', monospace; font-size: 7px; font-weight: 700; color: white; padding: 2px 5px; border-radius: 3px; }
        .sac-schedule { font-family: 'Space Mono', monospace; font-size: 7px; color: #8a7a60; border: 1px solid #d4c9b5; padding: 1px 5px; border-radius: 3px; }

        .schema-vbadge {
          font-family: 'Space Mono', monospace; font-size: 8px; font-weight: 700;
          color: #5a8a6a; background: rgba(90,138,106,0.08); border: 1px solid rgba(90,138,106,0.25);
          border-radius: 4px; padding: 4px 8px; white-space: nowrap; cursor: pointer; transition: all 0.15s;
        }
        .schema-vbadge:hover { border-color: #5a8a6a; }
        .schema-vbadge.selected { box-shadow: 0 0 0 2px #5a8a6a; }

        .schema-detail-placeholder { background: #ede7da; border: 1px dashed #c8b89a; border-radius: 8px; padding: 40px 24px; text-align: center; }
        .schema-placeholder-icon { font-size: 28px; color: #c8b89a; margin-bottom: 12px; opacity: 0.6; }
        .schema-placeholder-title { font-family: 'Space Mono', monospace; font-size: 11px; font-weight: 700; letter-spacing: 0.12em; color: #8a7a60; margin-bottom: 10px; text-transform: uppercase; }
        .schema-placeholder-sub { font-size: 11px; color: #a09080; line-height: 1.6; }

        .schema-detail { background: #ede7da; border: 1px solid #d4c9b5; border-radius: 8px; padding: 20px; }
        .sd-header { margin-bottom: 10px; }
        .sd-num { font-family: 'Space Mono', monospace; font-size: 9px; font-weight: 700; letter-spacing: 0.1em; display: block; }
        .sd-name { font-size: 18px; font-weight: 700; display: block; margin: 3px 0 2px; }
        .sd-sub { font-size: 10px; color: #8a7a60; display: block; }
        .sd-desc { font-size: 11px; line-height: 1.6; color: #4a3a28; margin-bottom: 14px; }
        .sd-io { display: flex; gap: 16px; }
        .sd-io-col { flex: 1; }
        .sd-io-label { font-family: 'Space Mono', monospace; font-size: 7px; letter-spacing: 0.12em; color: #8a7a60; font-weight: 700; margin-bottom: 6px; }
        .sd-io-tag { display: inline-block; font-size: 9px; padding: 3px 7px; border-radius: 3px; margin: 2px 3px 2px 0; }
        .sd-io-tag.input { background: #dde5ef; color: #3a5a7a; }
        .sd-io-tag.output { background: #ddeee4; color: #3a6a4a; }

        .schema-flow-section { margin-top: 32px; border-top: 1px solid #d4c9b5; padding-top: 20px; }
        .schema-flow-title { font-family: 'Space Mono', monospace; font-size: 9px; font-weight: 700; letter-spacing: 0.12em; color: #8a7a60; margin-bottom: 14px; }
        .schema-flow-lane { background: #ede7da; border: 1px solid #d4c9b5; border-radius: 6px; padding: 12px 16px; margin-bottom: 8px; }
        .schema-flow-phase { font-family: 'Space Mono', monospace; font-size: 9px; font-weight: 700; letter-spacing: 0.1em; margin-bottom: 8px; }
        .schema-flow-steps { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
        .schema-fs { font-size: 10px; padding: 3px 8px; border-radius: 3px; background: rgba(0,0,0,0.03); color: #6a5a48; }
        .schema-fs.agent { background: #2a2118; color: #f5f0e8; font-weight: 600; }
        .schema-fs.table { font-family: 'Space Mono', monospace; font-size: 9px; color: #7a6a4a; background: #efe8d4; }
        .schema-fs.validator { color: #5a8a6a; background: rgba(90,138,106,0.08); }
        .schema-fs.tool { color: #7a6a9a; background: rgba(122,106,154,0.08); }
        .schema-fs.sep { background: none; color: #b0a090; padding: 0 6px; }

        .schema-tables-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
        .schema-tbl { background: #ede7da; border: 1px solid #d4c9b5; border-radius: 6px; padding: 10px 12px; }
        .schema-tbl-name { font-family: 'Space Mono', monospace; font-size: 10px; font-weight: 700; margin-bottom: 2px; }
        .schema-tbl-desc { font-size: 10px; color: #6a5a48; }
        .schema-tbl-agent { font-family: 'Space Mono', monospace; font-size: 7px; color: #8a7a60; margin-top: 4px; }

        @media (max-width: 900px) { .schema-pipeline-flow { overflow-x: auto; } }
      `}</style>
    </div>
  )
}

// ── Sub-components ───────────────────────────────────────────────────────────

function SchemaAgentCard({ agent, selected, onClick }) {
  const modelColor = agent.model.includes("Sonnet") ? "#7c3aed"
    : agent.model.includes("Haiku") ? "#0891b2"
    : agent.model.includes("Python") ? "#6b7280" : "#6b7280"

  return (
    <div className={`schema-agent-card ${selected ? "selected" : ""}`}
      style={{ "--agent-color": agent.color }}
      onClick={() => onClick(agent.id)}
    >
      <div className="sac-top">
        <span className="sac-num" style={{ background: agent.color }}>{agent.id}</span>
        <span className="sac-name">{agent.name}</span>
      </div>
      <div className="sac-subtitle">{agent.subtitle}</div>
      <div className="sac-tags">
        <span className="sac-model" style={{ background: modelColor }}>{agent.model}</span>
        <span className="sac-schedule">{agent.schedule}</span>
      </div>
    </div>
  )
}

function SchemaValidatorBadge({ v, selected, onClick }) {
  return (
    <div className={`schema-vbadge ${selected ? "selected" : ""}`}
      onClick={(e) => { e.stopPropagation(); onClick(v.id) }}
    >
      <span>✓</span> {v.name}
    </div>
  )
}

function SchemaAgentDetail({ agent }) {
  return (
    <div className="schema-detail">
      <div className="sd-header">
        <span className="sd-num" style={{ color: agent.color }}>AGENT {agent.id}</span>
        <span className="sd-name">{agent.name}</span>
        <span className="sd-sub">{agent.subtitle}</span>
      </div>
      <p className="sd-desc">{agent.desc}</p>
      <div className="sd-io">
        <div className="sd-io-col">
          <div className="sd-io-label">INPUT</div>
          {agent.inputs.map(i => <span key={i} className="sd-io-tag input">{i}</span>)}
        </div>
        <div className="sd-io-col">
          <div className="sd-io-label">OUTPUT</div>
          {agent.outputs.map(o => <span key={o} className="sd-io-tag output">{o}</span>)}
        </div>
      </div>
    </div>
  )
}
