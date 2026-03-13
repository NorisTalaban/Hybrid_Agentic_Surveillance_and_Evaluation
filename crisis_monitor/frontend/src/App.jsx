/**
 * App.jsx — Crisis Monitor frontend (all-in-one)
 *
 * Contains (in order):
 *   [1] Imports
 *   [2] Supabase client
 *   [3] Utility functions & constants
 *   [4] Hooks: useSupabase, useCrisisDetail
 *   [5] Components: CrisisMap, ConnectionLines, KeyTimeline,
 *                   SeverityBadge, StatusBar, TopBar, CrisisPanel
 *   [6] App (root, default export)
 */

// ─────────────────────────────────────────────────────────────────────────────
// [1] IMPORTS
// ─────────────────────────────────────────────────────────────────────────────

import { useState, useEffect, useRef, useCallback } from "react"
import { createClient } from "@supabase/supabase-js"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import SystemPage from "./SystemPage"

// ── Simple hash router hook ──────────────────────────────────────────────────
function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash.replace("#", "") || "")
  useEffect(() => {
    const handler = () => setHash(window.location.hash.replace("#", "") || "")
    window.addEventListener("hashchange", handler)
    return () => window.removeEventListener("hashchange", handler)
  }, [])
  return hash
}

// ─────────────────────────────────────────────────────────────────────────────
// [2] SUPABASE CLIENT
// ─────────────────────────────────────────────────────────────────────────────

const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_KEY
)

// ─────────────────────────────────────────────────────────────────────────────
// [3] UTILITY FUNCTIONS & CONSTANTS
// ─────────────────────────────────────────────────────────────────────────────

export const TYPE_LABELS = {
  conflict:  "Armed Conflict",
  disaster:  "Natural Disaster",
  economic:  "Economic Crisis",
  political: "Political Crisis",
  health:    "Health Emergency",
}

export const STATUS_LABELS = {
  active:         "Active",
  escalating:     "Escalating",
  de_escalating:  "De-escalating",
  stable:         "Stable",
  resolved:       "Resolved",
}

export function severityColor(severity) {
  if (severity >= 9) return "#ef4444"
  if (severity >= 7) return "#f87171"
  if (severity >= 5) return "#fb923c"
  if (severity >= 3) return "#facc15"
  return "#4ade80"
}

export function severitySize(severity) {
  return Math.round(12 + severity * 3.2)
}

export function connectionColor(type) {
  const colors = {
    military_attack:  "#ef4444",
    sanction:         "#f97316",
    trade_cut:        "#eab308",
    aid:              "#22c55e",
    alliance:         "#3b82f6",
    disruption:       "#a855f7",
    refugee_flow:     "#06b6d4",
    diplomatic_break: "#6b7280",
  }
  return colors[type] || "#9ca3af"
}

// Static country coordinates — used for connection lines to ensure correct positions
// regardless of which crisis a country appears in
const COUNTRY_COORDS = {"AF":[33.93911,67.709953],"AL":[41.153332,20.168331],"DZ":[28.033886,1.659626],"AD":[42.506285,1.521801],"AO":[-11.202692,17.873887],"AG":[17.060816,-61.796428],"AR":[-38.416097,-63.616672],"AM":[40.069099,45.038189],"AU":[-25.274398,133.775136],"AT":[47.516231,14.550072],"AX":[60.178524,19.91556],"AZ":[40.143105,47.576927],"BS":[25.03428,-77.39628],"BH":[25.930414,50.637772],"BD":[23.684994,90.356331],"BB":[13.193887,-59.543198],"BY":[53.709807,27.953389],"BE":[50.503887,4.469936],"BZ":[17.189877,-88.49765],"BJ":[9.30769,2.315834],"BT":[27.514162,90.433601],"BO":[-16.290154,-63.588653],"BA":[43.915886,17.679076],"BW":[-22.328474,24.684866],"BQ":[12.20189,-68.262383],"BR":[-14.235004,-51.92528],"BN":[4.535277,114.727669],"BG":[42.733883,25.48583],"BF":[12.364566,-1.561593],"BI":[-3.373056,29.918886],"CV":[16.002082,-24.013197],"KH":[12.565679,104.990963],"CM":[3.848033,11.502075],"CA":[56.130366,-106.346771],"CF":[6.611111,20.939444],"TD":[15.454166,18.732207],"CL":[-35.675147,-71.542969],"CN":[35.86166,104.195397],"CO":[4.570868,-74.297333],"KM":[-11.875001,43.872219],"CG":[-0.228021,15.827659],"CD":[-4.038333,21.758664],"CR":[9.748917,-83.753428],"HR":[45.1,15.2],"CU":[21.521757,-77.781167],"CY":[35.126413,33.429859],"CZ":[49.817492,15.472962],"DK":[56.26392,9.501785],"DJ":[11.825138,42.590275],"DM":[15.414999,-61.370976],"DO":[18.735693,-70.162651],"EC":[-1.831239,-78.183406],"EG":[26.820553,30.802498],"EH":[24.215527,-12.885834],"SV":[13.794185,-88.89653],"GQ":[1.650801,10.267895],"ER":[15.179384,39.782334],"EE":[58.595272,25.013607],"SZ":[-26.522503,31.465866],"ET":[9.145,40.489673],"FJ":[-16.578193,179.414413],"FI":[61.92411,25.748151],"FR":[46.227638,2.213749],"GA":[-0.803689,11.609444],"GM":[13.443182,-15.310139],"GE":[42.315407,43.356892],"DE":[51.165691,10.451526],"GG":[49.465691,-2.585278],"GH":[7.946527,-1.023194],"GR":[39.074208,21.824312],"GD":[12.262776,-61.604171],"GT":[15.783471,-90.230759],"GN":[9.945587,-9.696645],"GW":[11.803749,-15.180413],"GY":[4.860416,-58.93018],"HT":[18.971187,-72.285215],"HK":[22.396428,114.109497],"HN":[15.199999,-86.241905],"HU":[47.162494,19.503304],"IS":[64.963051,-19.020835],"IM":[54.236107,-4.548056],"IN":[20.593684,78.96288],"ID":[-0.789275,113.921327],"IR":[32.427908,53.688046],"IQ":[33.223191,43.679291],"IE":[53.41291,-8.24389],"IL":[31.046051,34.851612],"IT":[41.87194,12.56738],"JM":[18.109581,-77.297508],"JP":[36.204824,138.252924],"JE":[49.214439,-2.13125],"JO":[30.585164,36.238414],"KZ":[48.019573,66.923684],"KE":[-0.023559,37.906193],"KI":[-3.370417,-168.734039],"KP":[40.339852,127.510093],"KR":[35.907757,127.766922],"KW":[29.31166,47.481766],"KG":[41.20438,74.766098],"LA":[19.85627,102.495496],"LV":[56.879635,24.603189],"LB":[33.854721,35.862285],"LS":[-29.609988,28.233608],"LR":[6.428055,-9.429499],"LY":[26.3351,17.228331],"LI":[47.166,9.555373],"LT":[55.169438,23.881275],"LU":[49.815273,6.129583],"MO":[22.198745,113.543873],"MG":[-18.766947,46.869107],"MW":[-13.254308,34.301525],"MY":[4.210484,101.975766],"MV":[3.202778,73.22068],"ML":[17.570692,-3.996166],"MT":[35.937496,14.375416],"MH":[7.131474,171.184478],"MR":[21.00789,-10.940835],"MU":[-20.348404,57.552152],"MX":[23.634501,-102.552784],"FM":[7.425554,150.550812],"MD":[47.411631,28.369885],"MC":[43.750298,7.412841],"MN":[46.862496,103.846656],"ME":[42.708678,19.37439],"MA":[31.791702,-7.09262],"MZ":[-18.665695,35.529562],"MM":[21.913965,95.956223],"NA":[-22.95764,18.49041],"NR":[-0.522778,166.931503],"NP":[28.394857,84.124008],"NL":[52.132633,5.291266],"NZ":[-40.900557,174.885971],"NI":[12.865416,-85.207229],"NE":[17.607789,8.081666],"NG":[9.081999,8.675277],"MK":[41.608635,21.745275],"NO":[60.472024,8.468946],"OM":[21.512583,55.923255],"PK":[30.375321,69.345116],"PW":[7.51498,134.58252],"PS":[31.952162,35.233154],"PA":[8.537981,-80.782127],"PG":[-6.314993,143.95555],"PY":[-23.442503,-58.443832],"PE":[-9.189967,-75.015152],"PH":[12.879721,121.774017],"PL":[51.919438,19.145136],"PT":[39.399872,-8.224454],"QA":[25.354826,51.183884],"RO":[45.943161,24.96676],"RU":[61.52401,105.318756],"RW":[-1.940278,29.873888],"KN":[17.357822,-62.782998],"LC":[13.909444,-60.978893],"VC":[12.984305,-61.287228],"WS":[-13.759029,-172.104629],"SM":[43.94236,12.457777],"ST":[0.18636,6.613081],"SA":[23.885942,45.079162],"SN":[14.497401,-14.452362],"RS":[44.016521,21.005859],"SC":[-4.679574,55.491977],"SL":[8.460555,-11.779889],"SG":[1.352083,103.819836],"SK":[48.669026,19.699024],"SI":[46.151241,14.995463],"SB":[-9.64571,160.156194],"SO":[5.152149,46.199616],"ZA":[-30.559482,22.937506],"SS":[4.85165,31.571251],"ES":[40.463667,-3.74922],"LK":[7.873054,80.771797],"SD":[12.862807,30.217636],"SR":[3.919305,-56.027783],"SE":[60.128161,18.643501],"CH":[46.818188,8.227512],"SY":[34.802075,38.996815],"TW":[23.69781,120.960515],"TJ":[38.861034,71.276093],"TZ":[-6.369028,34.888822],"TH":[15.870032,100.992541],"TL":[-8.874217,125.727539],"TG":[8.619543,0.824782],"TO":[-21.178986,-175.198242],"TT":[10.691803,-61.222503],"TN":[33.886917,9.537499],"TR":[38.963745,35.243322],"TM":[38.969719,59.556278],"TV":[-7.109535,177.64933],"UG":[1.373333,32.290275],"UA":[48.379433,31.16558],"AE":[23.424076,53.847818],"GB":[55.378051,-3.435973],"US":[37.09024,-95.712891],"UY":[-32.522779,-55.765835],"UZ":[41.377491,64.585262],"VU":[-15.376706,166.959158],"VE":[6.42375,-66.58973],"VN":[14.058324,108.277199],"YE":[15.552727,48.516388],"ZM":[-13.133897,27.849332],"ZW":[-19.015438,29.154857],"XK":[42.602636,20.902977],"CI":[7.539989,-5.54708],"SX":[18.0425,-63.0548],"CW":[12.1696,-68.99]}

export function formatDate(str) {
  if (!str) return "—"
  try {
    return new Date(str).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
  } catch {
    return "—"
  }
}

export function formatDateShort(str) {
  if (!str) return "—"
  try {
    return new Date(str).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
  } catch {
    return "—"
  }
}

/** Strip HTML/XML tags (e.g. <cite index="...">...</cite>) from DB text */
export function cleanText(str) {
  if (!str) return ""
  return str.replace(/<[^>]*>/g, "").trim()
}

// ─────────────────────────────────────────────────────────────────────────────
// [4] HOOKS
// ─────────────────────────────────────────────────────────────────────────────

function useSupabase() {
  const [crises,      setCrises]      = useState([])
  const [connections, setConnections] = useState([])
  const [loading,     setLoading]     = useState(true)

  const fetchAll = useCallback(async () => {
    try {
      const [crisesRes, connRes] = await Promise.all([
        supabase
          .from("crises")
          .select("*")
          .neq("status", "resolved")
          .not("lat", "is", null)
          .order("severity", { ascending: false }),
        supabase
          .from("connections")
          .select("*")
          .eq("active", true),
      ])
      if (crisesRes.data)  setCrises(crisesRes.data)
      if (connRes.data)    setConnections(connRes.data)
    } catch (e) {
      console.error("Fetch error:", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()

    const crisisChannel = supabase
      .channel("crises-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "crises" }, fetchAll)
      .subscribe()

    const connChannel = supabase
      .channel("connections-realtime")
      .on("postgres_changes", { event: "*", schema: "public", table: "connections" }, fetchAll)
      .subscribe()

    return () => {
      supabase.removeChannel(crisisChannel)
      supabase.removeChannel(connChannel)
    }
  }, [fetchAll])

  return { crises, connections, loading }
}

function useCrisisDetail(crisisId) {
  const [timeline,    setTimeline]    = useState([])
  const [analysis,    setAnalysis]    = useState(null)
  const [connections, setConnections] = useState([])
  const [loading,     setLoading]     = useState(true)

  useEffect(() => {
    if (!crisisId) {
      setTimeline([])
      setAnalysis(null)
      setConnections([])
      setLoading(false)
      return
    }

    // Reset state on crisis change to avoid showing stale data
    setTimeline([])
    setAnalysis(null)
    setConnections([])
    setLoading(true)

    Promise.all([
      supabase
        .from("key_timeline")
        .select("*")
        .eq("crisis_id", crisisId)
        .order("order_index", { ascending: true }),
      supabase
        .from("analyses")
        .select("*")
        .eq("crisis_id", crisisId)
        .order("created_at", { ascending: false })
        .limit(1),
      supabase
        .from("connections")
        .select("*")
        .eq("crisis_id", crisisId)
        .eq("active", true)
        .order("strength", { ascending: false }),
    ]).then(([tlRes, anRes, connRes]) => {
      setTimeline(tlRes.data   || [])
      setAnalysis((anRes.data  || [])[0] || null)
      setConnections(connRes.data || [])
      setLoading(false)
    }).catch(err => {
      console.error("useCrisisDetail error:", err)
      setLoading(false)
    })
  }, [crisisId])

  return { timeline, analysis, connections, loading }
}

// ─────────────────────────────────────────────────────────────────────────────
// [5] COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

// Leaflet default icon fix
delete L.Icon.Default.prototype._getIconUrl
L.Icon.Default.mergeOptions({ iconUrl: "", shadowUrl: "" })

// ── CrisisMap ────────────────────────────────────────────────────────────────

function CrisisMap({ crises, connections, selectedCrisis, onSelectCrisis, showAllConnections }) {
  const mapRef        = useRef(null)
  const leafletRef    = useRef(null)
  const markersRef    = useRef({})
  const linesRef      = useRef([])
  const tileRef       = useRef(null)

  const TILE_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"

  // Init map
  useEffect(() => {
    if (leafletRef.current) return
    const map = L.map(mapRef.current, {
      center: [20, 10],
      zoom: 3,
      zoomControl: false,
      attributionControl: false,
      minZoom: 2,
      maxZoom: 10,
      worldCopyJump: false,
      maxBounds: [[-90, -220], [90, 220]],
      maxBoundsViscosity: 0.7,
    })
    tileRef.current = L.tileLayer(TILE_URL, { maxZoom: 18, noWrap: true }).addTo(map)
    leafletRef.current = map
    return () => { map.remove(); leafletRef.current = null }
  }, [])

  // Update markers
  useEffect(() => {
    const map = leafletRef.current
    if (!map) return

    const currentIds = new Set(crises.map(c => c.id))
    Object.keys(markersRef.current).forEach(id => {
      if (!currentIds.has(id)) {
        markersRef.current[id].remove()
        delete markersRef.current[id]
      }
    })

    // Compute coordinate jitter for overlapping markers.
    // Applies actual lat/lng offsets (not pixel anchors) so markers physically separate on the map.
    // Groups crises with identical or near-identical coordinates and spreads them in a golden-angle spiral.
    const THRESH = 0.5 // degrees — treat as same location if within ~55km
    const JITTER_DEG = 2.2 // degrees of spread per step
    const jitterMap = {}

    const groups = {}
    crises.forEach(crisis => {
      if (!crisis.lat || !crisis.lng) return
      const key = `${Math.round(crisis.lat / THRESH) * THRESH},${Math.round(crisis.lng / THRESH) * THRESH}`
      if (!groups[key]) groups[key] = []
      groups[key].push(crisis.id)
    })

    Object.values(groups).forEach(ids => {
      if (ids.length === 1) { jitterMap[ids[0]] = { dlat: 0, dlng: 0 }; return }
      ids.forEach((id, i) => {
        if (i === 0) { jitterMap[id] = { dlat: 0, dlng: 0 }; return }
        const angle = (i * 137.508) % 360
        const radius = JITTER_DEG * (0.6 + i * 0.35)
        jitterMap[id] = {
          dlat: Math.sin(angle * Math.PI / 180) * radius * 0.6,
          dlng: Math.cos(angle * Math.PI / 180) * radius,
        }
      })
    })

    crises.forEach(crisis => {
      if (!crisis.lat || !crisis.lng) return
      const isSelected = selectedCrisis?.id === crisis.id
      const color = severityColor(crisis.severity)
      const size  = severitySize(crisis.severity)
      const jitter = jitterMap[crisis.id] || { dlat: 0, dlng: 0 }
      const displayLat = crisis.lat + jitter.dlat
      const displayLng = crisis.lng + jitter.dlng

      const icon = L.divIcon({
        className: "",
        html: `
          <div class="crisis-marker" style="width:${size}px;height:${size}px">
            <div class="marker-ring ${isSelected ? "selected" : ""}"
                 style="width:${size}px;height:${size}px;color:${color}">
              ${crisis.severity >= 5
                ? `<span class="marker-sev" style="color:${color}">${crisis.severity}</span>`
                : `<div class="marker-dot" style="background:${color}"></div>`
              }
            </div>
          </div>`,
        iconSize:   [size, size],
        iconAnchor: [size / 2, size / 2],
      })

      if (markersRef.current[crisis.id]) {
        markersRef.current[crisis.id].setIcon(icon)
        markersRef.current[crisis.id].setLatLng([displayLat, displayLng])
      } else {
        const marker = L.marker([displayLat, displayLng], { icon })
          .addTo(map)
          .on("click", () => onSelectCrisis(crisis))

        marker.bindTooltip(
          `<div class="tt-name">${crisis.name}</div>
           <div class="tt-row"><span>Type</span><span>${crisis.type}</span></div>
           <div class="tt-row"><span>Severity</span>
             <span style="color:${color}">${crisis.severity}/10</span></div>
           <div class="tt-row"><span>Status</span><span>${crisis.status}</span></div>
           ${crisis.media_gap ? `<div style="color:var(--amber);font-size:10px;margin-top:4px">⚠ Underreported</div>` : ""}`,
          { className: "crisis-tooltip", direction: "top", offset: [0, -size / 2 - 4], opacity: 1 }
        )
        markersRef.current[crisis.id] = marker
      }
    })
  }, [crises, selectedCrisis])

  // Draw connection lines — selected crisis only, or ALL when toggle is on
  useEffect(() => {
    const map = leafletRef.current
    if (!map) return

    linesRef.current.forEach(l => l.remove())
    linesRef.current = []

    // Determine which connections to show
    let visible = []
    if (showAllConnections) {
      // Show all connections for currently visible (filtered) crises
      const visibleCrisisIds = new Set(crises.map(c => c.id))
      visible = connections.filter(c => visibleCrisisIds.has(c.crisis_id))
    } else if (selectedCrisis) {
      visible = connections.filter(c => c.crisis_id === selectedCrisis.id)
    }

    if (!visible.length) return

    const isAllMode = showAllConnections && !selectedCrisis

    visible.forEach(conn => {
      const from = COUNTRY_COORDS[conn.from_country]
      const to   = COUNTRY_COORDS[conn.to_country]
      if (!from || !to) return

      const color  = connectionColor(conn.relation_type)
      const weight = isAllMode
        ? Math.max(1.5, Math.min(2.5, (conn.strength || 5) / 4))
        : Math.max(2, Math.min(3.5, (conn.strength || 5) / 3))
      const lineOpacity = isAllMode ? 0.5 : 0.8

      const tooltipHtml =
        `<div style="font-family:var(--font-mono);font-size:10px;color:var(--text);max-width:340px;padding:2px 4px;word-wrap:break-word;overflow-wrap:break-word">
           <div style="margin-bottom:3px">
             <strong style="color:var(--text-bright);font-size:11px">${conn.from_country} → ${conn.to_country}</strong>
           </div>
           <span style="color:${color}">${(conn.relation_type || "").replace(/_/g, " ")}</span>
           <span style="opacity:0.5;margin-left:6px">str ${conn.strength || "?"}/10</span>
           ${conn.description ? `<div style="opacity:0.8;font-size:10px;margin-top:5px;line-height:1.5">${conn.description}</div>` : ""}
         </div>`

      // Invisible fat polyline for generous hover area (20px wide)
      const hitLine = L.polyline([from, to], {
        color: "transparent",
        weight: 20,
        opacity: 0,
        interactive: true,
      }).addTo(map)
        .bindTooltip(tooltipHtml, { className: "crisis-tooltip", sticky: true, opacity: 1 })
      linesRef.current.push(hitLine)

      // Visible line on top (thinner, styled)
      const visLine = L.polyline([from, to], {
        color, weight, opacity: lineOpacity,
        lineCap: "round",
        lineJoin: "round",
        dashArray: isAllMode ? "6 4" : null,
        interactive: false,
      }).addTo(map)
      linesRef.current.push(visLine)

      // Arrowhead at 70% toward destination (skip in "all" mode to reduce clutter)
      if (!isAllMode) {
        const t = 0.70
        const arrowLat = from[0] + (to[0] - from[0]) * t
        const arrowLng = from[1] + (to[1] - from[1]) * t
        const angleDeg = Math.atan2(to[0] - from[0], to[1] - from[1]) * (180 / Math.PI)

        const arrowIcon = L.divIcon({
          className: "",
          html: `<div style="
            width:0;height:0;
            border-left:6px solid transparent;
            border-right:6px solid transparent;
            border-bottom:10px solid ${color};
            transform:rotate(${-angleDeg + 180}deg);
            opacity:0.85;
            filter:drop-shadow(0 0 3px ${color});
            pointer-events:none;
          "></div>`,
          iconSize:   [12, 12],
          iconAnchor: [6, 6],
        })
        const arrowMarker = L.marker([arrowLat, arrowLng], { icon: arrowIcon, interactive: false }).addTo(map)
        linesRef.current.push(arrowMarker)
      }
    })
  }, [connections, crises, selectedCrisis, showAllConnections])

  // Country labels — show labels for countries involved in the selected crisis
  const labelsRef = useRef([])
  useEffect(() => {
    const map = leafletRef.current
    if (!map) return

    labelsRef.current.forEach(l => l.remove())
    labelsRef.current = []

    if (!selectedCrisis) return

    // Gather all country codes involved: crisis countries + connection endpoints
    const involvedCodes = new Set(selectedCrisis.countries || [])
    connections
      .filter(c => c.crisis_id === selectedCrisis.id)
      .forEach(c => {
        involvedCodes.add(c.from_country)
        involvedCodes.add(c.to_country)
      })

    involvedCodes.forEach(code => {
      const coords = COUNTRY_COORDS[code]
      if (!coords) return

      const labelIcon = L.divIcon({
        className: "",
        html: `<div class="country-label-map">${code}</div>`,
        iconSize:   [40, 18],
        iconAnchor: [20, -8],
      })
      const m = L.marker(coords, { icon: labelIcon, interactive: false, zIndexOffset: -100 }).addTo(map)
      labelsRef.current.push(m)
    })
  }, [selectedCrisis, connections])

  // Secondary markers for connection countries without a crisis marker
  const secondaryRef = useRef([])
  useEffect(() => {
    const map = leafletRef.current
    if (!map) return

    secondaryRef.current.forEach(m => m.remove())
    secondaryRef.current = []

    if (!selectedCrisis) return

    const coveredCountries = new Set()
    crises.forEach(c => {
      if (c.lat && c.lng && c.countries) {
        c.countries.forEach(code => coveredCountries.add(code))
      }
    })

    const relevantConns = connections.filter(c => c.crisis_id === selectedCrisis.id)
    const extraCountries = new Set()
    relevantConns.forEach(conn => {
      if (!coveredCountries.has(conn.from_country)) extraCountries.add(conn.from_country)
      if (!coveredCountries.has(conn.to_country))   extraCountries.add(conn.to_country)
    })

    extraCountries.forEach(code => {
      const coords = COUNTRY_COORDS[code]
      if (!coords) return
      const icon = L.divIcon({
        className: "",
        html: `<div style="
          width:10px;height:10px;border-radius:50%;
          border:1.5px solid #7a8699;
          background:rgba(255,255,255,0.7);
          backdrop-filter:blur(2px);
        "></div>`,
        iconSize:   [10, 10],
        iconAnchor: [5, 5],
      })
      const m = L.marker(coords, { icon, interactive: false }).addTo(map)
      secondaryRef.current.push(m)
    })
  }, [connections, crises, selectedCrisis])

  // Pan to selected
  useEffect(() => {
    const map = leafletRef.current
    if (!map || !selectedCrisis?.lat) return
    map.panTo([selectedCrisis.lat, selectedCrisis.lng], { animate: true, duration: 0.5 })
  }, [selectedCrisis])

  return <div ref={mapRef} className="map-container" />
}

// ── ConnectionLines ───────────────────────────────────────────────────────────

function ConnectionLines({ connections }) {
  return (
    <div className="connection-list">
      {connections.map((conn, i) => {
        const color  = connectionColor(conn.relation_type)
        const filled = Math.round((conn.strength || 5) / 2)
        return (
          <div key={conn.id || i} className="connection-item">
            <div className="conn-countries">
              <span className="conn-code">{conn.from_country}</span>
              <span className="conn-arrow" style={{ color }}>
                {conn.direction === "bidirectional" ? "⇄" : "→"}
              </span>
              <span className="conn-code">{conn.to_country}</span>
            </div>
            <span className="conn-type" style={{ color }}>
              {conn.relation_type.replace(/_/g, " ")}
            </span>
            <div className="conn-strength">
              {Array.from({ length: 5 }, (_, j) => (
                <div key={j}
                  className={`conn-bar ${j < filled ? "filled" : ""}`}
                  style={j < filled ? { background: color } : undefined}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── KeyTimeline ───────────────────────────────────────────────────────────────

function KeyTimeline({ entries }) {
  return (
    <div className="timeline">
      {entries.map((entry, i) => (
        <div key={entry.id || i} className="timeline-entry">
          <div className="timeline-date">{formatDateShort(entry.event_date)}</div>
          <div className="timeline-content">
            <div className="timeline-title">{entry.title}</div>
            <div className="timeline-sig">{entry.significance}</div>
            {entry.severity_impact && (
              <div className="timeline-impact">{entry.severity_impact}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── SeverityBadge ─────────────────────────────────────────────────────────────

function SeverityBadge({ severity, peak }) {
  const color = severityColor(severity)
  return (
    <span className="sev-badge" style={{ color, borderColor: `${color}55` }}>
      <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
        <circle cx="4" cy="4" r="3" fill={color} opacity="0.8" />
      </svg>
      SEV {severity}
      {peak && peak > severity && (
        <span style={{ fontSize: 9, opacity: 0.6, marginLeft: 2 }}>(peak {peak})</span>
      )}
    </span>
  )
}

// ── StatusBar ─────────────────────────────────────────────────────────────────

function StatusBar({ crises }) {
  const [time, setTime] = useState(new Date())

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const critical = crises.filter(c => c.severity >= 8)
  const severe   = crises.filter(c => c.severity >= 5 && c.severity < 8)

  return (
    <div className="statusbar">
      {critical.length > 0 && (
        <div className="statusbar-item">
          <div className="statusbar-dot" style={{ background: "var(--red)", animation: "blink 1s infinite" }} />
          <span style={{ color: "var(--red)" }}>{critical.length} critical</span>
        </div>
      )}
      {severe.length > 0 && (
        <div className="statusbar-item">
          <div className="statusbar-dot" style={{ background: "var(--orange)" }} />
          <span>{severe.length} severe</span>
        </div>
      )}
      <div className="statusbar-item">
        <div className="statusbar-dot" style={{ background: "var(--green)" }} />
        <span>Realtime</span>
      </div>
      <div className="statusbar-item"><span>v2.1</span></div>
      <div className="statusbar-clock">{time.toUTCString().slice(0, -4)} UTC</div>
    </div>
  )
}

// ── TopBar ────────────────────────────────────────────────────────────────────

const TYPES = ["all", "conflict", "disaster", "economic", "political", "health"]


function TopBar({ crises, filter, onFilterChange, loading }) {
  const active     = crises.filter(c => c.status === "active" || c.status === "escalating")
  const escalating = crises.filter(c => c.status === "escalating")
  const mediaGap   = crises.filter(c => c.media_gap)
  const avgSev     = crises.length
    ? (crises.reduce((s, c) => s + c.severity, 0) / crises.length).toFixed(1)
    : "—"

  return (
    <div className="topbar">
      {/* ── Row 1: Logo + Stats | [SEV + System btn] center ── */}
      <div className="topbar-row topbar-row-main">
        <div className="topbar-left">
          <div className="topbar-logo">
            <div className="logo-mark" />
            <div>
              <div className="logo-text">Crisis Monitor</div>
              <div className="logo-sub">Global Intelligence</div>
            </div>
          </div>

          <div className="topbar-divider" />

          <div className="topbar-stats">
            <div className="stat-item">
              <span className="stat-value hot">{active.length}</span>
              <span className="stat-label">Active</span>
            </div>
            <div className="stat-item">
              <span className="stat-value" style={{ color: "var(--red)" }}>{escalating.length}</span>
              <span className="stat-label">Escalating</span>
            </div>
            <div className="stat-item">
              <span className="stat-value">{avgSev}</span>
              <span className="stat-label">Avg Sev</span>
            </div>
            {mediaGap.length > 0 && (
              <div className="stat-item">
                <span className="stat-value" style={{ color: "var(--amber)" }}>{mediaGap.length}</span>
                <span className="stat-label">Underreported</span>
              </div>
            )}
          </div>
        </div>

        <div className="topbar-center">
          <div className="filter-sev">
            <span>SEV≥</span>
            <input
              type="range" min="1" max="9"
              value={filter.minSeverity}
              onChange={e => onFilterChange({ ...filter, minSeverity: +e.target.value })}
            />
            <span style={{ color: "var(--amber)", minWidth: 12 }}>{filter.minSeverity}</span>
          </div>
          <button
            className={`conn-toggle ${filter.showConnections ? "active" : ""}`}
            onClick={() => onFilterChange({ ...filter, showConnections: !filter.showConnections })}
            title="Show all connections on map"
          >
            <span className="conn-toggle-icon">⤬</span>
            <span className="conn-toggle-label">CONN</span>
          </button>
          <a href="#system" className="system-health-btn" style={{ textDecoration: "none" }}>
            <span className="system-health-icon">◈</span>
            <span className="system-health-label">System Agents &amp; Health</span>
          </a>
        </div>

        {/* Spacer to balance the left side */}
        <div className="topbar-right">
          {loading && <div className="loading-dot" />}
        </div>
      </div>

      {/* ── Row 2: Type filters (centered) ── */}
      <div className="topbar-row topbar-row-filters">
        {TYPES.map(t => (
          <button
            key={t}
            className={`filter-btn ${filter.type === t ? "active" : ""}`}
            onClick={() => onFilterChange({ ...filter, type: t })}
          >
            {t === "all" ? "All" : t}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── CrisisPanel ───────────────────────────────────────────────────────────────

const TABS = ["overview", "timeline", "analysis", "connections"]

function CrisisPanel({ crisis, onClose }) {
  const [tab, setTab] = useState("overview")
  const { timeline, analysis, connections, loading } = useCrisisDetail(crisis.id)
  const statusClass = `status-${crisis.status}`

  // Reset tab when switching to a different crisis
  useEffect(() => {
    setTab("overview")
  }, [crisis.id])

  return (
    <div className="crisis-panel">
      <div className="panel-header">
        <button className="panel-close" onClick={onClose}>×</button>
        <div className="panel-type">{TYPE_LABELS[crisis.type] || crisis.type}</div>
        <div className="panel-name">{crisis.name}</div>

        <div className="panel-meta">
          <SeverityBadge severity={crisis.severity} peak={crisis.severity_peak} />
          <span className={`status-badge ${statusClass}`}>
            {STATUS_LABELS[crisis.status] || crisis.status}
          </span>
          {crisis.media_gap && (
            <span className="media-gap-badge"><span>⚠</span> Underreported</span>
          )}
        </div>

        <div style={{ display: "flex", gap: 0, marginTop: 12, borderBottom: "1px solid var(--border)",
                      marginLeft: -20, paddingLeft: 20, marginRight: -20 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: "none", border: "none",
              borderBottom: tab === t ? "2px solid var(--amber)" : "2px solid transparent",
              color: tab === t ? "var(--text-bright)" : "var(--text-dim)",
              fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.12em",
              textTransform: "uppercase", padding: "6px 14px 8px",
              cursor: "pointer", transition: "all 0.15s", marginBottom: -1,
            }}>
              {t}
            </button>
          ))}
        </div>
      </div>

      <div className="panel-body">
        {tab === "overview"     && <OverviewTab     crisis={crisis} />}
        {tab === "timeline"     && <TimelineTab     timeline={timeline} loading={loading} />}
        {tab === "analysis"     && <AnalysisTab     analysis={analysis} loading={loading} crisis={crisis} />}
        {tab === "connections"  && <ConnectionsTab  connections={connections} loading={loading} />}
      </div>
    </div>
  )
}

function OverviewTab({ crisis }) {
  return (
    <>
      <div className="panel-section">
        <div className="section-label">Summary</div>
        <p className="summary-text">{cleanText(crisis.summary) || "No summary available."}</p>
      </div>
      <div className="panel-section">
        <div className="section-label">Countries Involved</div>
        <div className="countries-list">
          {(crisis.countries || []).map(code => (
            <span key={code} className="country-tag">{code}</span>
          ))}
        </div>
      </div>
      <div className="panel-section">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
          <DataField label="First detected" value={formatDate(crisis.first_event_at)} />
          <DataField label="Last event"     value={formatDate(crisis.last_event_at)} />
          <DataField label="Event count"    value={crisis.event_count || 0} />
          <DataField label="Source"         value={crisis.source} />
          <DataField label="Last verified"  value={formatDate(crisis.last_verified) || "Pending"} />
          <DataField label="Severity peak"  value={`${crisis.severity_peak}/10`} />
        </div>
      </div>
    </>
  )
}

function DataField({ label, value }) {
  return (
    <div>
      <div style={{ fontSize: 9, letterSpacing: "0.15em", textTransform: "uppercase",
                    color: "var(--text-dim)", marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 12, color: "var(--text-bright)", fontFamily: "var(--font-mono)" }}>{value}</div>
    </div>
  )
}

function TimelineTab({ timeline, loading }) {
  if (loading) return <Loader />
  if (!timeline.length) return <Empty text="No timeline entries yet." />
  return (
    <div className="panel-section">
      <KeyTimeline entries={timeline} />
    </div>
  )
}

function AnalysisTab({ analysis, loading, crisis }) {
  if (loading) return <Loader />
  if (!analysis) {
    const sev = crisis?.severity || 0
    const needed = 7 - sev
    return (
      <div style={{ padding: "28px 20px" }}>
        <div style={{
          background: "var(--bg-elevated)",
          border: "1px solid var(--border)",
          borderRadius: 6,
          padding: "20px",
          textAlign: "center",
        }}>
          <div style={{ fontSize: 28, marginBottom: 12, opacity: 0.4 }}>🔍</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-bright)", marginBottom: 8 }}>
            Deep Analysis Unavailable
          </div>
          <div style={{ fontSize: 11, color: "var(--text)", lineHeight: 1.6, marginBottom: 14 }}>
            Deep intelligence analysis is triggered automatically when a crisis reaches
            severity <span style={{ color: "var(--amber)", fontFamily: "var(--font-mono)" }}>7/10</span> or above.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10,
                          fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>
              <span>Current severity</span>
              <span style={{ color: severityColor(sev) }}>{sev}/10</span>
            </div>
            <div style={{
              height: 4, background: "var(--border)", borderRadius: 2, overflow: "hidden",
            }}>
              <div style={{
                height: "100%",
                width: `${(sev / 10) * 100}%`,
                background: severityColor(sev),
                borderRadius: 2,
                transition: "width 0.4s ease",
              }} />
            </div>
            {needed > 0 && (
              <div style={{ fontSize: 10, color: "var(--text-dim)", textAlign: "right",
                            fontFamily: "var(--font-mono)" }}>
                +{needed} point{needed !== 1 ? "s" : ""} needed to unlock
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }
  return (
    <>
      <div className="panel-section">
        <div className="section-label">Intelligence Assessment</div>
        <p className="analysis-text">{cleanText(analysis.analysis_text)}</p>
      </div>
      {analysis.evolutions?.length > 0 && (
        <div className="panel-section">
          <div className="section-label">Possible Evolutions</div>
          <div className="evolutions">
            {analysis.evolutions.map((ev, i) => (
              <div key={i} className="evolution-item">
                <div className="evolution-header">
                  <span className="evolution-scenario">{ev.scenario}</span>
                  <span className={`evolution-prob prob-${ev.probability}`}>{ev.probability}</span>
                </div>
                <p className="evolution-desc">{ev.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      {analysis.key_actors?.length > 0 && (
        <div className="panel-section">
          <div className="section-label">Key Actors</div>
          <div className="countries-list">
            {analysis.key_actors.map((a, i) => (
              <span key={i} className="country-tag">{a}</span>
            ))}
          </div>
        </div>
      )}
      {analysis.watch_list?.length > 0 && (
        <div className="panel-section">
          <div className="section-label">Watch Indicators</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {analysis.watch_list.map((item, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "flex-start",
                                    fontSize: 11, color: "var(--text)" }}>
                <span style={{ color: "var(--amber)", flexShrink: 0 }}>◆</span>
                {item}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function ConnectionsTab({ connections, loading }) {
  if (loading) return <Loader />
  if (!connections.length) return <Empty text="No active connections detected." />
  return (
    <div className="panel-section">
      <div className="section-label">Active Relationships ({connections.length})</div>
      <ConnectionLines connections={connections} />
    </div>
  )
}

function Loader() {
  return (
    <div style={{ padding: "40px 20px", display: "flex", justifyContent: "center" }}>
      <div className="loading-dot" />
    </div>
  )
}

function Empty({ text }) {
  return (
    <div style={{ padding: "32px 20px", color: "var(--text-dim)", fontSize: 11, textAlign: "center" }}>
      {text}
    </div>
  )
}


// ─────────────────────────────────────────────────────────────────────────────
// HOOK: useNewsFeed — raw_articles joined with classified_events
// ─────────────────────────────────────────────────────────────────────────────

function useNewsFeed() {
  const [items,     setItems]     = useState([])
  const [loading,   setLoading]   = useState(true)
  const [refreshKey, setRefreshKey] = useState(0)

  const doFetch = useCallback(async () => {
    setLoading(true)
    try {
      // Step 1: find the most recent collected_at (= last run batch timestamp)
      const latestRes = await supabase
        .from("raw_articles")
        .select("collected_at")
        .order("collected_at", { ascending: false })
        .limit(1)

      if (!latestRes.data?.length) { setItems([]); return }

      // Step 2: load all articles from that same run batch (same minute window ±10min)
      const latestTs  = new Date(latestRes.data[0].collected_at)
      const batchFrom = new Date(latestTs.getTime() - 10 * 60 * 1000).toISOString()

      const [rawRes, evtRes, crisesRes] = await Promise.all([
        supabase
          .from("raw_articles")
          .select("id, title, url, source_name, published_at, collected_at")
          .gte("collected_at", batchFrom)
          .in("status", ["classified", "new"])
          .order("published_at", { ascending: false })
          .limit(100),
        supabase
          .from("classified_events")
          .select("article_id, summary, severity, crisis_id, event_type")
          .gte("classified_at", batchFrom),
        supabase
          .from("crises")
          .select("id, name, type")
          .neq("status", "resolved"),
      ])

      const articles  = rawRes.data    || []
      const events    = evtRes.data    || []
      const crises    = crisesRes.data || []

      const evtMap    = Object.fromEntries(events.map(e => [e.article_id, e]))
      const crisisMap = Object.fromEntries(crises.map(c => [c.id, c]))

      const merged = articles
        .map(a => {
          const evt    = evtMap[a.id]
          const crisis = evt?.crisis_id ? crisisMap[evt.crisis_id] : null
          return {
            id:         a.id,
            title:      a.title,
            url:        a.url,
            source:     a.source_name,
            published:  a.published_at || a.collected_at,
            summary:    evt?.summary    || null,
            severity:   evt?.severity   || null,
            eventType:  evt?.event_type || null,
            crisisName: crisis?.name    || null,
            crisisType: crisis?.type    || null,
          }
        })
        .filter(a => a.title)

      setItems(merged)
    } catch (e) {
      console.error("NewsFeed error:", e)
    } finally {
      setLoading(false)
    }
  }, [refreshKey])

  useEffect(() => {
    doFetch()
    const ch = supabase
      .channel("news-feed-realtime")
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "raw_articles" },
          () => setRefreshKey(k => k + 1))
      .subscribe()
    return () => supabase.removeChannel(ch)
  }, [doFetch])

  return { items, loading, refresh: () => setRefreshKey(k => k + 1) }
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENT: NewsFeed
// ─────────────────────────────────────────────────────────────────────────────

function timeAgo(str) {
  if (!str) return "—"
  const diff = Date.now() - new Date(str).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 60)  return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24)  return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function NewsFeed({ crises, onSelectCrisis }) {
  const { items, loading, refresh } = useNewsFeed()
  const [refreshing, setRefreshing] = useState(false)
  const crisisMap = Object.fromEntries(crises.map(c => [c.name, c]))

  const handleRefresh = () => {
    setRefreshing(true)
    refresh()
    setTimeout(() => setRefreshing(false), 1200)
  }

  return (
    <div className="news-feed">
      <div className="news-feed-header">
        <span className="news-feed-title">NEWS FEED</span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="news-feed-count">{items.length}</span>
          <button
            className={`news-refresh-btn ${refreshing ? "spinning" : ""}`}
            onClick={handleRefresh}
            title="Refresh feed"
          >↻</button>
        </div>
      </div>
      <div className="news-feed-body">
        {loading && <Loader />}
        {!loading && items.length === 0 && (
          <div className="news-empty">No articles found.<br/>Run the pipeline to collect news.</div>
        )}
        {items.map((item, idx) => (
          <div
            key={item.id}
            className={`news-item ${item.severity ? "news-item--classified" : ""}`}
            onClick={() => {
              if (item.crisisName && crisisMap[item.crisisName]) {
                onSelectCrisis(crisisMap[item.crisisName])
              }
            }}
            style={{ cursor: item.crisisName ? "pointer" : "default" }}
          >
            <div className="news-item-top">
              <span className="news-index">{idx + 1}</span>
              {item.severity && (
                <span className="news-sev" style={{ color: severityColor(item.severity), borderColor: `${severityColor(item.severity)}44` }}>
                  {item.severity}
                </span>
              )}
              <span className="news-time">{timeAgo(item.published)}</span>
              {item.source && <span className="news-source">{item.source}</span>}
            </div>
            <div className="news-title">{item.title}</div>
            {item.summary && (
              <div className="news-summary">{item.summary}</div>
            )}
            {item.crisisName && (
              <div className="news-crisis-tag">
                <span className={`news-crisis-dot type-${item.crisisType}`} />
                {item.crisisName}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENT: TensionThermometer
// ─────────────────────────────────────────────────────────────────────────────

function computeTensionIndex(crises, connections) {
  if (!crises.length) return { score: 0, level: "CALM", factors: {} }

  const total        = crises.length
  const avgSeverity  = crises.reduce((s, c) => s + (c.severity || 0), 0) / total
  const escalating   = crises.filter(c => c.status === "escalating").length
  const militaryConn = connections.filter(c => c.relation_type === "military_attack" && c.active).length

  // Weighted formula (0–10)
  const score = Math.min(10,
    avgSeverity                             * 0.40 +
    (escalating / Math.max(total, 1)) * 10  * 0.30 +
    Math.min(militaryConn / 10, 1)   * 10  * 0.20 +
    Math.min(total / 50, 1)          * 10  * 0.10
  )

  const level =
    score >= 7.5 ? "CRITICAL" :
    score >= 5.5 ? "HIGH"     :
    score >= 3.0 ? "ELEVATED" : "CALM"

  return { score: +score.toFixed(1), level, factors: { avgSeverity: +avgSeverity.toFixed(1), escalating, militaryConn, total } }
}

const TENSION_LEVELS = {
  CALM:     { color: "#167833", bg: "rgba(22,120,51,0.12)",   border: "rgba(22,120,51,0.35)",   icon: "◌" },
  ELEVATED: { color: "#b8720a", bg: "rgba(184,114,10,0.12)",  border: "rgba(184,114,10,0.35)",  icon: "◍" },
  HIGH:     { color: "#b55218", bg: "rgba(181,82,24,0.12)",   border: "rgba(181,82,24,0.35)",   icon: "●" },
  CRITICAL: { color: "#b52828", bg: "rgba(181,40,40,0.12)",   border: "rgba(181,40,40,0.35)",   icon: "⬤" },
}

function TensionThermometer({ crises, connections, onSelectCrisis }) {
  const { score, level, factors } = computeTensionIndex(crises, connections)
  const lv        = TENSION_LEVELS[level] || TENSION_LEVELS.CALM
  const pct       = score / 10
  const TUBE_H    = 100 // compact tube height px

  const fillColor =
    score >= 7.5 ? "#b52828" :
    score >= 5.5 ? "#b55218" :
    score >= 3.0 ? "#b8720a" : "#167833"

  // Top crisis by severity for the CTA button
  const topCrisis = crises.length
    ? [...crises].sort((a, b) => b.severity - a.severity)[0]
    : null

  return (
    <div className="crisis-panel thermo-panel">

      {/* ── Header ── */}
      <div className="thermo-panel-header">
        <span className="thermo-panel-badge">GLOBAL</span>
        <span className="thermo-panel-title">Tension Index</span>
      </div>

      <div className="thermo-panel-body">

        {/* ── Compact thermometer row ── */}
        <div className="thermo-visual thermo-visual--compact">

          {/* Tube + bulb */}
          <div className="thermo-column">
            <div className="thermo-tube" style={{ height: TUBE_H }}>
              {[2, 4, 6, 8].map(m => (
                <div key={m} className="thermo-tick" style={{ bottom: `${m * 10}%` }} />
              ))}
              <div
                className={`thermo-fill-bar ${level === "CRITICAL" ? "thermo-fill--critical" : ""}`}
                style={{ height: `${pct * 100}%`, background: fillColor }}
              />
            </div>
            <div className="thermo-bulb" style={{ borderColor: fillColor, background: lv.bg }}>
              <span className="thermo-bulb-val" style={{ color: fillColor }}>{score}</span>
            </div>
          </div>

          {/* Score + level badge */}
          <div className="thermo-readout thermo-readout--compact">
            <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
              <div className="thermo-score thermo-score--compact" style={{ color: fillColor }}>{score}</div>
              <div className="thermo-score-sub">/ 10</div>
            </div>
            <div
              className="thermo-level-badge"
              style={{ color: lv.color, background: lv.bg, borderColor: lv.border }}
            >
              {lv.icon} {level}
            </div>

            {/* Mini legend inline */}
            <div className="thermo-legend thermo-legend--compact">
              {Object.entries(TENSION_LEVELS).map(([lbl, cfg]) => (
                <div key={lbl} className={`thermo-legend-item ${lbl === level ? "thermo-legend-item--active" : ""}`}>
                  <div className="thermo-legend-dot" style={{ background: cfg.color }} />
                  <span className="thermo-legend-lbl" style={lbl === level ? { color: cfg.color, fontWeight: 700 } : {}}>
                    {lbl}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Divider ── */}
        <div className="thermo-divider" />

        {/* ── Factor breakdown ── */}
        <div className="thermo-factors">
          <div className="thermo-factors-label">Contributing Factors</div>

          <div className="thermo-factor-row">
            <span className="thermo-factor-name">Avg Severity</span>
            <div className="thermo-factor-bar-wrap">
              <div className="thermo-factor-bar">
                <div className="thermo-factor-fill" style={{ width: `${(factors.avgSeverity / 10) * 100}%`, background: fillColor }} />
              </div>
            </div>
            <span className="thermo-factor-val" style={{ color: fillColor }}>{factors.avgSeverity}/10</span>
          </div>

          <div className="thermo-factor-row">
            <span className="thermo-factor-name">Escalating</span>
            <div className="thermo-factor-bar-wrap">
              <div className="thermo-factor-bar">
                <div className="thermo-factor-fill" style={{ width: `${Math.min((factors.escalating / Math.max(factors.total, 1)) * 100, 100)}%`, background: "#b52828" }} />
              </div>
            </div>
            <span className="thermo-factor-val" style={{ color: "var(--red)" }}>{factors.escalating} / {factors.total}</span>
          </div>

          <div className="thermo-factor-row">
            <span className="thermo-factor-name">Military Links</span>
            <div className="thermo-factor-bar-wrap">
              <div className="thermo-factor-bar">
                <div className="thermo-factor-fill" style={{ width: `${Math.min((factors.militaryConn / 10) * 100, 100)}%`, background: "#b55218" }} />
              </div>
            </div>
            <span className="thermo-factor-val" style={{ color: "var(--orange)" }}>{factors.militaryConn}</span>
          </div>

          <div className="thermo-factor-row">
            <span className="thermo-factor-name">Active Crises</span>
            <div className="thermo-factor-bar-wrap">
              <div className="thermo-factor-bar">
                <div className="thermo-factor-fill" style={{ width: `${Math.min((factors.total / 50) * 100, 100)}%`, background: "var(--text-dim)" }} />
              </div>
            </div>
            <span className="thermo-factor-val">{factors.total}</span>
          </div>
        </div>

        {/* ── Spacer pushes CTA to bottom ── */}
        <div style={{ flex: 1 }} />

        {/* ── CTA button ── */}
        <div className="thermo-cta-wrap">
          <div className="thermo-cta-label">Select a crisis to inspect</div>
          <button
            className="thermo-cta-btn"
            onClick={() => topCrisis && onSelectCrisis && onSelectCrisis(topCrisis)}
            disabled={!topCrisis}
          >
            <span className="thermo-cta-icon">◎</span>
            <span className="thermo-cta-text">
              {topCrisis ? `View highest severity — ${topCrisis.name}` : "Click a marker on the map"}
            </span>
            {topCrisis && (
              <span
                className="thermo-cta-sev"
                style={{ color: severityColor(topCrisis.severity) }}
              >
                {topCrisis.severity}/10
              </span>
            )}
          </button>
          <div className="thermo-cta-hint">or click any marker on the map</div>
        </div>

      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// [6] APP ROOT
// ─────────────────────────────────────────────────────────────────────────────

export default function App() {
  const [selectedCrisis, setSelectedCrisis] = useState(null)
  const [filter, setFilter] = useState({ type: "all", minSeverity: 1, showConnections: false })
  const { crises, connections, loading } = useSupabase()
  const route = useHashRoute()

  // Force light theme always
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", "light")
  }, [])


  // System monitor page
  if (route === "system") {
    return <SystemPage />
  }

  const filtered = crises.filter(c => {
    if (filter.type !== "all" && c.type !== filter.type) return false
    if (c.severity < filter.minSeverity) return false
    return true
  })


  return (
    <div className="app">
      <TopBar
        crises={crises}
        filter={filter}
        onFilterChange={setFilter}
        loading={loading}
      />
      <main className="main-layout">
        <NewsFeed crises={crises} onSelectCrisis={setSelectedCrisis} />
        <CrisisMap
          crises={filtered}
          connections={connections}
          selectedCrisis={selectedCrisis}
          onSelectCrisis={setSelectedCrisis}
          showAllConnections={filter.showConnections}
        />
        {selectedCrisis ? (
          <CrisisPanel
            crisis={selectedCrisis}
            onClose={() => setSelectedCrisis(null)}
          />
        ) : (
          <TensionThermometer crises={crises} connections={connections} onSelectCrisis={setSelectedCrisis} />
        )}
      </main>
      <StatusBar crises={crises} />
    </div>
  )
}
