// Three.js city. Kept outside React: React owns the panels, this class owns the GPU objects.
// World axes: x = east (m), y = up (m), z = south (m), origin at the study-box centre.
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js'
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import { Traffic } from './traffic.js'

export function projection(bbox) {
  const lon0 = (bbox[0] + bbox[2]) / 2, lat0 = (bbox[1] + bbox[3]) / 2
  const kx = 111320 * Math.cos(lat0 * Math.PI / 180), ky = 110574
  return ([lon, lat]) => [(lon - lon0) * kx, -(lat - lat0) * ky]   // -> [x, z]
}

const BG = '#0b0f16'
const BLACK = new THREE.Color(0, 0, 0)
const LANE_W = 3.4
const ARTERIAL = /trunk|primary|motorway/
const MAJOR = /trunk|primary|motorway|secondary/
const roadY = type => ARTERIAL.test(type || '') ? 0.7 : MAJOR.test(type || '') ? 0.55 : 0.4
const ZONE_COLORS = { water: '#1d5d8f', park: '#1f5a3d', institutional: '#4a4234' }

const dedupe = pts => pts.filter((p, i) => i === 0 || Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) > 0.05)

// Continuous ribbon with mitred joins. l, r = offsets of its two edges along the right-hand normal of the direction
// of travel. SUMO edge shapes are the road centreline with lanes spread to the right, so a direction's lanes are
// [0, width] and the two directions of a two-way road sit side by side.
function pushRibbon(out, raw, l, r, y, along) {
  const pts = dedupe(raw)
  if (pts.length < 2) return 0
  if (along) {   // [metres along the road in the direction of travel, 0..1 across] per vertex, for the flow shader
    const d = [0]
    for (let i = 1; i < pts.length; i++) d.push(d[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    for (let i = 0; i < pts.length - 1; i++) along.push(d[i], 0, d[i + 1], 0, d[i], 1, d[i], 1, d[i + 1], 0, d[i + 1], 1)
  }
  const norms = pts.slice(0, -1).map((a, i) => {
    const b = pts[i + 1], len = Math.hypot(b[0] - a[0], b[1] - a[1])
    return [-(b[1] - a[1]) / len, (b[0] - a[0]) / len]
  })
  const side = pts.map((p, i) => {
    const n0 = norms[Math.max(0, i - 1)], n1 = norms[Math.min(norms.length - 1, i)]
    let nx = n0[0] + n1[0], nz = n0[1] + n1[1]
    const len = Math.hypot(nx, nz) || 1
    nx /= len; nz /= len
    const k = 1 / Math.max(0.5, nx * n1[0] + nz * n1[1])   // mitre, capped at 2x on hairpins
    return [[p[0] + nx * l * k, y, p[1] + nz * l * k], [p[0] + nx * r * k, y, p[1] + nz * r * k]]
  })
  for (let i = 0; i < side.length - 1; i++) {
    const [aL, aR] = side[i], [bL, bR] = side[i + 1]
    out.push(...aL, ...bL, ...aR, ...aR, ...bL, ...bR)
  }
  return (side.length - 1) * 6
}

const ribbonGeometry = (pts, l, r, y) => {
  const pos = []
  pushRibbon(pos, pts, l, r, y)
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  return g
}

// Ribbon over a 3D polyline [[x, y, z], ...]: like ribbonGeometry, but each point keeps its own height (bridge decks).
// l, r = lateral offsets along the horizontal right-hand normal; dy lifts it above the path.
function ribbon3(path, l, r, dy) {
  const pos = []
  for (let i = 0; i < path.length - 1; i++) {
    const a = path[i], b = path[i + 1], len = Math.hypot(b[0] - a[0], b[2] - a[2]) || 1
    const nx = -(b[2] - a[2]) / len, nz = (b[0] - a[0]) / len
    const v = (p, o) => [p[0] + nx * o, p[1] + dy, p[2] + nz * o]
    pos.push(...v(a, l), ...v(b, l), ...v(a, r), ...v(a, r), ...v(b, l), ...v(b, r))
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  return g
}

// Grade-separated candidates (they cross a road or the metro worksite; priced in P) are drawn as raised decks:
// smooth ramps at both ends, a level span in between. Every deck clears 6.5 m (what crossing a road needs); short
// links therefore get steep ramps, which shows honestly that they are hard to build as bridges.
const BRIDGE = { clearance: 6.5, maxRamp: 90, halfWidth: 7, thickness: 1.3, parapet: 1.1, pierEvery: 24 }
function bridgePath(pts, samples = 48) {
  const a = pts[0], b = pts[pts.length - 1], L = Math.hypot(b[0] - a[0], b[1] - a[1])
  const ramp = Math.min(BRIDGE.maxRamp, 0.35 * L)
  const top = BRIDGE.clearance + BRIDGE.thickness   // deck surface above the clearance
  const smooth = t => t * t * (3 - 2 * t)
  const h = s => top * smooth(Math.min(1, s / ramp, (L - s) / ramp))
  return { L, top, h, path: Array.from({ length: samples + 1 }, (_, i) => {
    const t = i / samples
    return [a[0] + (b[0] - a[0]) * t, h(t * L), a[1] + (b[1] - a[1]) * t]
  }) }
}

// Sweep a closed cross-section [[lateral, up], ...] along a 3D path whose plan is a straight line. The section stays
// level (up = world up) instead of following Frenet frames, so the deck never twists.
function sweep(path, section) {
  const a = path[0], b = path[path.length - 1], len = Math.hypot(b[0] - a[0], b[2] - a[2]) || 1
  const nx = -(b[2] - a[2]) / len, nz = (b[0] - a[0]) / len
  const pos = [], idx = [], m = section.length
  for (const p of path) for (const [u, v] of section) pos.push(p[0] + nx * u, p[1] + v, p[2] + nz * u)
  for (let i = 0; i < path.length - 1; i++) {
    for (let j = 0; j < m; j++) {
      const k = (j + 1) % m, p0 = i * m + j, p1 = i * m + k, q0 = p0 + m, q1 = p1 + m
      idx.push(p0, q0, p1, p1, q0, q1)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setIndex(idx)
  const flat = g.toNonIndexed()   // flat-shaded faces: crisp concrete edges
  flat.computeVertexNormals()
  return flat
}

// deck slab with a parapet on each side, as a closed outline (lateral, up), deck top at 0
const { halfWidth: HW, thickness: TH, parapet: PH } = BRIDGE
const DECK_SECTION = [[-HW, -TH], [HW, -TH], [HW, PH], [HW - 0.45, PH], [HW - 0.45, 0], [-HW + 0.45, 0],
                      [-HW + 0.45, PH], [-HW, PH]]

// Road surface shader (CGVR: custom GLSL). Per vertex: two colours and two speeds (before / after a candidate),
// blended by uMix on the GPU, so switching scenarios is a smooth fade instead of a rebuild. The fragment shader
// draws light dashes that travel along each road in its direction of travel at FLOW x its simulated speed:
// free-flowing roads stream, jammed roads crawl, roads without traffic stay still.
const FLOW = 2.5        // dashes move 2.5x real speed, so slow traffic still visibly moves
const DASH = 26         // m between dashes
function roadMaterial(uniforms) {
  return new THREE.ShaderMaterial({
    // fog uniforms are per material (filled by the renderer); time / blend / flow are the scene's shared objects
    uniforms: { ...THREE.UniformsUtils.clone(THREE.UniformsLib.fog), uTime: uniforms.uTime, uMix: uniforms.uMix,
                uFlow: uniforms.uFlow },
    vertexShader: `
      attribute vec3 color2;
      attribute float speed, speed2;
      attribute vec2 along;
      uniform float uMix;
      varying vec3 vColor;
      varying float vSpeed;
      varying vec2 vAlong;
      #include <fog_pars_vertex>
      void main() {
        vColor = mix(color, color2, uMix);
        vSpeed = mix(speed, speed2, uMix);
        vAlong = along;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader: `
      uniform float uTime, uFlow;
      varying vec3 vColor;
      varying float vSpeed;
      varying vec2 vAlong;
      #include <fog_pars_fragment>
      void main() {
        vec3 c = vColor;
        // phase moves forward along the road; fract() repeats it every DASH metres
        float ph = fract((vAlong.x - uTime * vSpeed * ${FLOW.toFixed(1)}) / ${DASH.toFixed(1)});
        float dash = smoothstep(0.0, 0.08, ph) * (1.0 - smoothstep(0.28, 0.4, ph));
        float mid = 1.0 - smoothstep(0.18, 0.42, abs(vAlong.y - 0.5));      // a stripe down the middle only
        float moving = smoothstep(0.3, 1.5, vSpeed);                        // no dashes where nothing drives
        c = mix(c, c * 1.5 + 0.18, uFlow * dash * mid * moving * 0.55);
        gl_FragColor = vec4(c, 1.0);
        #include <colorspace_fragment>
        #include <fog_fragment>
      }`,
    vertexColors: true, side: THREE.DoubleSide, fog: true,
  })
}

// Candidate "planned road" look (CGVR: shader injection). Adds diagonal stripes in world space that scroll with time
// to a built-in material, so its colour, opacity and hover styling keep working.
function plannedStripes(mat, uniforms) {
  mat.onBeforeCompile = sh => {
    sh.uniforms.uTime = uniforms.uTime
    sh.vertexShader = 'varying vec3 vWorldP;\n' + sh.vertexShader.replace('#include <project_vertex>',
      '#include <project_vertex>\n  vWorldP = (modelMatrix * vec4(transformed, 1.0)).xyz;')
    sh.fragmentShader = 'uniform float uTime;\nvarying vec3 vWorldP;\n' + sh.fragmentShader.replace('#include <dithering_fragment>',
      `#include <dithering_fragment>
      float band = fract((vWorldP.x + vWorldP.z) / 7.0 - uTime * 0.5);
      float stripe = smoothstep(0.45, 0.5, band) * (1.0 - smoothstep(0.95, 1.0, band));
      gl_FragColor.rgb = mix(gl_FragColor.rgb, gl_FragColor.rgb * 0.55, stripe * 0.55);`)
  }
  mat.customProgramCacheKey = () => 'planned-stripes'
  return mat
}

// Stable pseudo-random numbers per building: OSM has no height data for this area, so heights are illustrative.
const rand = i => Math.abs(Math.sin(i * 12.9898 + 78.233) * 43758.5453) % 1
const heightOf = (i, area) => {
  const h = rand(i)
  // mostly 1-3 floor houses with a few taller blocks, as in Hebbal's residential layouts
  const floors = area > 2500 ? 1 + Math.floor(h * 3) : 1 + Math.floor(h * h * 4 + (area > 400 ? 1 : 0))
  return 3.2 * floors
}

function polygonShapes(geom, proj) {
  const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.type === 'MultiPolygon' ? geom.coordinates : []
  return polys.map(rings => {
    // Shape is built in (x, -z) so that rotateX(-90deg) maps it back onto the ground with +y up
    const toV = ring => ring.map(p => { const [x, z] = proj(p); return new THREE.Vector2(x, -z) })
    const shape = new THREE.Shape(toV(rings[0]))
    shape.holes = rings.slice(1).map(r => new THREE.Path(toV(r)))
    return shape
  })
}

export class CityScene {
  constructor(container, { onPick, onHover }) {
    this.container = container
    this.onPick = onPick
    this.onHover = onHover
    this.layers = {}
    this.candidates = new Map()   // key -> { mesh, glow, pts, center }
    this.clock = new THREE.Clock()
    // shared by every custom shader: time, before/after blend, flow on/off
    this.uniforms = { uTime: { value: 0 }, uMix: { value: 0 }, uFlow: { value: 1 } }

    const r = this.renderer = new THREE.WebGLRenderer({ antialias: true })
    r.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    r.setClearColor(BG)
    r.toneMapping = THREE.ACESFilmicToneMapping
    r.toneMappingExposure = 1.05
    container.appendChild(r.domElement)

    this.labels = new CSS2DRenderer()
    this.labels.domElement.className = 'labels'
    container.appendChild(this.labels.domElement)

    this.scene = new THREE.Scene()
    this.world = new THREE.Group()   // everything except lights
    this.scene.add(this.world)
    this.scene.fog = new THREE.Fog(BG, 2200, 6000)
    this.camera = new THREE.PerspectiveCamera(42, 1, 5, 20000)
    this.camera.position.set(450, 1900, 1150)
    this.controls = new OrbitControls(this.camera, r.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.maxPolarAngle = Math.PI * 0.46
    this.controls.minDistance = 60
    this.controls.maxDistance = 6000

    this.scene.add(new THREE.HemisphereLight('#c8d8ff', '#1a1f2b', 1.5))
    const sun = new THREE.DirectionalLight('#ffe9cc', 2.2)
    sun.position.set(-1400, 1800, 600)
    this.scene.add(sun)
    const fill = new THREE.DirectionalLight('#7aa0ff', 0.5)
    fill.position.set(1200, 600, -900)
    this.scene.add(fill)

    this.raycaster = new THREE.Raycaster()
    this.pointer = new THREE.Vector2()
    this._bindPointer()
    this._resize = new ResizeObserver(() => this.resize())
    this._resize.observe(container)
    this.resize()
    r.setAnimationLoop(() => this._frame())
  }

  _frame() {
    const dt = Math.min(0.1, this.clock.getDelta())   // capped, so a background tab does not jump the playback
    const t = this.clock.elapsedTime
    this.uniforms.uTime.value = t
    if (this._mixTo != null) {
      const m = this.uniforms.uMix, d = this._mixTo - m.value
      m.value = Math.abs(d) < 0.002 ? this._mixTo : m.value + d * Math.min(1, dt * 7)
    }
    if (this.traffic?.data) {
      this.traffic.update(dt, this.camera.position.distanceTo(this.controls.target))
      const now = performance.now()
      if (this.onTrafficTick && now - (this._tick || 0) > 150) { this._tick = now; this.onTrafficTick(this.traffic) }
    }
    this.controls.update()
    this._tween?.()
    if (this.halo?.visible) this.halo.material.opacity = 0.55 + 0.35 * Math.sin(t * 3)
    if (this.hoverHalo?.visible) this.hoverHalo.material.opacity = 0.35 + 0.25 * Math.sin(t * 6)
    // hovered candidate rises a few metres; ease every strip towards its target height
    for (const c of this.candidates.values()) {
      const y = c.mesh.position.y, to = c.lift || 0
      if (Math.abs(to - y) > 0.01) {
        const ny = y + (to - y) * 0.2
        c.mesh.position.y = c.glow.position.y = ny
        if (c.key === this._hoverKey) this.hoverHalo.position.y = ny
      }
    }
    this.renderer.render(this.scene, this.camera)
    this.labels.render(this.scene, this.camera)
  }

  dispose() {
    this.renderer.setAnimationLoop(null)
    this._resize.disconnect()
    this.renderer.dispose()
    this.renderer.domElement.remove()
    this.labels.domElement.remove()
  }

  resize() {
    const { clientWidth: w, clientHeight: h } = this.container
    if (!w || !h) return
    this.renderer.setSize(w, h)
    this.labels.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  _layer(name) {
    if (!this.layers[name]) { this.layers[name] = new THREE.Group(); this.world.add(this.layers[name]) }
    return this.layers[name]
  }

  setLayerVisible(name, v) { if (this.layers[name]) this.layers[name].visible = v }

  // animated vehicles: data = traffic_<run>.json (urban.fcd); null hides them
  // candKey: the run's candidate, so its cars can ride on its bridge deck
  setTraffic(data, onTick, candKey) {
    if (!this.traffic) this.traffic = new Traffic(this._layer('traffic'))
    this.onTrafficTick = onTick
    const c = candKey && this.candidates.get(candKey)
    if (c?.bridge) {
      const a = c.pts[0], b = c.pts[c.pts.length - 1], L = c.bridge.L
      const ux = (b[0] - a[0]) / L, uz = (b[1] - a[1]) / L
      this.traffic.lift = (x, z) => c.bridge.h(Math.max(0, Math.min(L, (x - a[0]) * ux + (z - a[1]) * uz)))
    } else this.traffic.lift = null
    if (data) this.traffic.load(data)
    this.traffic.setVisible(!!data)
    if (!data) this.traffic.playing = false
    return this.traffic
  }

  build(data, bbox) {
    const proj = this.proj = projection(bbox)
    this._ground(bbox, proj)
    this._roadLabels(data.roads, proj)        // labels first, in priority order: roads, metro, zones
    this._construction(data.construction, proj)
    this._zones(data.zones, proj)
    this._roads(data.roads, proj)
    this._buildings(data.buildings, proj, bbox)
    this._candidates(data.selected, data.others, proj)
  }

  _ground(bbox, proj) {
    const g = new THREE.Mesh(new THREE.CircleGeometry(9000, 64).rotateX(-Math.PI / 2),
                             new THREE.MeshLambertMaterial({ color: '#121821' }))
    g.position.y = -0.3
    this.world.add(g)
    const [x0, z0] = proj([bbox[0], bbox[1]]), [x1, z1] = proj([bbox[2], bbox[3]])
    // slightly lighter ground under the study box
    const pad = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0, z0 - z1).rotateX(-Math.PI / 2),
                               new THREE.MeshLambertMaterial({ color: '#18202c' }))
    pad.position.set((x0 + x1) / 2, -0.2, (z0 + z1) / 2)
    this._layer('studyBox').add(pad)
    const box = new THREE.BufferGeometry().setFromPoints(
      [[x0, z0], [x1, z0], [x1, z1], [x0, z1], [x0, z0]].map(([x, z]) => new THREE.Vector3(x, 1.2, z)))
    this._layer('studyBox').add(new THREE.Line(box, new THREE.LineDashedMaterial({
      color: '#7ea6ff', dashSize: 26, gapSize: 16, transparent: true, opacity: 0.7 })).computeLineDistances())
  }

  _zones(fc, proj) {
    const byKind = {}
    for (const f of fc.features) {
      const kind = f.properties.kind || 'institutional'
      for (const s of polygonShapes(f.geometry, proj)) (byKind[kind] ||= []).push(new THREE.ShapeGeometry(s))
    }
    for (const [kind, geoms] of Object.entries(byKind)) {
      const g = mergeGeometries(geoms).rotateX(-Math.PI / 2)
      g.translate(0, kind === 'water' ? 0.05 : 0.1, 0)
      const mat = kind === 'water'
        ? new THREE.MeshPhongMaterial({ color: ZONE_COLORS.water, shininess: 90, specular: '#6fa8ff', side: THREE.DoubleSide })
        : new THREE.MeshLambertMaterial({ color: ZONE_COLORS[kind], side: THREE.DoubleSide })
      this._layer('obstacles').add(new THREE.Mesh(g, mat))
    }
    // name labels for the larger named zones
    for (const f of fc.features) {
      if (!f.properties.name || f.properties.kind === 'institutional') continue
      const ring = f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] : f.geometry.coordinates[0][0]
      const pts = ring.map(proj)
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length, cz = pts.reduce((s, p) => s + p[1], 0) / pts.length
      this._label('obstacles', f.properties.name, `zone ${f.properties.kind}`, cx, 3, cz)
    }
  }

  _label(layer, text, cls, x, y, z, minGap = 220) {
    // skip labels that would sit on top of one already placed (the flyover junction has many named ramps)
    this._placed ||= []
    if (this._placed.some(([px, pz]) => Math.hypot(px - x, pz - z) < minGap)) return
    this._placed.push([x, z])
    const el = document.createElement('div')
    el.className = `label ${cls}`
    el.textContent = text
    const o = new CSS2DObject(el)
    o.position.set(x, y, z)
    this._layer(layer).add(o)
  }

  _roads(fc, proj) {
    const casing = [], strip = [], ranges = [], along = []
    this.roadProps = fc.features.map(f => f.properties)
    fc.features.forEach(f => {
      const p = f.properties, pts = f.geometry.coordinates.map(proj)
      const w = Math.max(1, p.lanes) * LANE_W * (ARTERIAL.test(p.type || '') ? 1 : 0.85), y = roadY(p.type)
      pushRibbon(casing, pts, -0.6, w + 0.6, y - 0.05)
      const start = strip.length / 3
      const n = pushRibbon(strip, pts, w * 0.1, w * 0.9, y, along)
      ranges.push([start, n])
    })
    this.roadRanges = ranges
    this.triRoad = new Int32Array(strip.length / 9)   // triangle -> road index, for picking
    ranges.forEach(([s, n], i) => this.triRoad.fill(i, s / 3, (s + n) / 3))

    const cg = new THREE.BufferGeometry()
    cg.setAttribute('position', new THREE.Float32BufferAttribute(casing, 3))
    this._layer('roads').add(new THREE.Mesh(cg, new THREE.MeshBasicMaterial({ color: '#262d39', side: THREE.DoubleSide })))

    const g = new THREE.BufferGeometry(), nv = strip.length / 3
    g.setAttribute('position', new THREE.Float32BufferAttribute(strip, 3))
    // two states per road (before / after) so the GPU can blend them; speeds drive the flow animation
    g.setAttribute('color', new THREE.Float32BufferAttribute(new Float32Array(nv * 3), 3))
    g.setAttribute('color2', new THREE.Float32BufferAttribute(new Float32Array(nv * 3), 3))
    g.setAttribute('speed', new THREE.Float32BufferAttribute(new Float32Array(nv), 1))
    g.setAttribute('speed2', new THREE.Float32BufferAttribute(new Float32Array(nv), 1))
    g.setAttribute('along', new THREE.Float32BufferAttribute(along, 2))
    this.roadMesh = new THREE.Mesh(g, roadMaterial(this.uniforms))
    this._layer('roads').add(this.roadMesh)
  }

  _roadLabels(fc, proj) {
    // one label per major named road, at the middle of its longest segment
    const best = new Map()
    for (const f of fc.features) {
      const p = f.properties
      if (!p.name || !MAJOR.test(p.type || '') || p.length < 120 || /ramp|exit|loop/i.test(p.name)) continue
      if (!best.has(p.name) || best.get(p.name).properties.length < p.length) best.set(p.name, f)
    }
    // arterials first, so they win the space when labels collide
    const order = [...best].sort(([, a], [, b]) => ARTERIAL.test(b.properties.type) - ARTERIAL.test(a.properties.type)
                                                || b.properties.length - a.properties.length)
    for (const [name, f] of order) {
      const pts = f.geometry.coordinates.map(proj), m = pts[Math.floor(pts.length / 2)]
      this._label('roadLabels', name, ARTERIAL.test(f.properties.type) ? 'road arterial' : 'road', m[0], 4, m[1])
    }
  }

  // Real traffic (TomTom) segments: their own ribbons, drawn just above the roads. colorFn(point) -> THREE.Color
  setLive(points, colorFn) {
    const layer = this._layer('live')
    layer.clear()
    const pos = [], col = []
    for (const p of points) {
      if (!p.segment?.length || p.ratio == null) continue
      const n = pushRibbon(pos, p.segment.map(this.proj), -4.5, 4.5, 1.1), c = colorFn(p)
      for (let i = 0; i < n; i++) col.push(c.r, c.g, c.b)
    }
    if (!pos.length) return
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
    layer.add(new THREE.Mesh(g, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.DoubleSide, toneMapped: false })))
  }

  // fn(props, index) -> THREE.Color; speedFn(props) -> m/s for the flow animation (0 = no flow). One state.
  setRoadColors(fn, speedFn = () => 0) { this.setRoadStates(fn, speedFn, fn, speedFn) }

  // Two states, blended on the GPU by uMix (0 = A, 1 = B): before / after a candidate.
  setRoadStates(fnA, spA, fnB, spB) {
    const at = this.roadMesh.geometry.attributes
    this.roadProps.forEach((p, i) => {
      const a = fnA(p, i), b = fnB(p, i), sa = spA(p) || 0, sb = spB(p) || 0, [s, n] = this.roadRanges[i]
      for (let v = s; v < s + n; v++) {
        at.color.setXYZ(v, a.r, a.g, a.b); at.color2.setXYZ(v, b.r, b.g, b.b)
        at.speed.setX(v, sa); at.speed2.setX(v, sb)
      }
    })
    for (const k of ['color', 'color2', 'speed', 'speed2']) at[k].needsUpdate = true
  }

  // blend between the two road states; animate = ease there over ~0.6 s (Before/After buttons), else jump (slider)
  setMix(v, animate = true) {
    this._mixTo = v
    if (!animate) this.uniforms.uMix.value = v
  }

  setFlow(on) { this.uniforms.uFlow.value = on ? 1 : 0 }

  _buildings(fc, proj, bbox) {
    const geoms = [], tmp = new THREE.Color()
    fc.features.forEach((f, i) => {
      for (const shape of polygonShapes(f.geometry, proj)) {
        const area = Math.abs(THREE.ShapeUtils.area(shape.getPoints()))
        const depth = heightOf(i, area)
        const g = new THREE.ExtrudeGeometry(shape, { depth, bevelEnabled: false })
        // vertex colours: darker at the base (cheap ambient occlusion), slight hue/brightness variation per building
        const pos = g.attributes.position, cols = new Float32Array(pos.count * 3)
        const base = tmp.setHSL(0.61 + (rand(i + 7) - 0.5) * 0.05, 0.13, 0.26 + rand(i + 3) * 0.1).clone()
        for (let v = 0; v < pos.count; v++) {
          const t = pos.getZ(v) / depth, k = 0.42 + 0.58 * Math.pow(t, 0.7)
          cols[v * 3] = base.r * k; cols[v * 3 + 1] = base.g * k; cols[v * 3 + 2] = base.b * k
        }
        g.setAttribute('color', new THREE.BufferAttribute(cols, 3))
        geoms.push(g)
      }
    })
    const g = mergeGeometries(geoms).rotateX(-Math.PI / 2)
    geoms.forEach(x => x.dispose())
    this._layer('buildings').add(new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true })))
  }

  _construction(fc, proj) {
    const lines = fc.features.filter(f => f.geometry.type === 'LineString').map(f => f.geometry.coordinates.map(proj))
    if (!lines.length) return
    const layer = this._layer('construction')
    layer.add(new THREE.Mesh(mergeGeometries(lines.map(p => ribbonGeometry(p, -9, 9, 0.9))), new THREE.MeshBasicMaterial({
      color: '#b56cff', transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false })))
    layer.add(new THREE.Mesh(mergeGeometries(lines.map(p => ribbonGeometry(p, -2, 2, 1))), new THREE.MeshBasicMaterial({
      color: '#c98bff', transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false })))
    const longest = new Map()
    for (const f of fc.features) {
      const n = f.properties.name
      if (n && f.geometry.type === 'LineString' && (longest.get(n)?.geometry.coordinates.length ?? 0) < f.geometry.coordinates.length) longest.set(n, f)
    }
    for (const [name, f] of longest) {
      const pts = f.geometry.coordinates.map(proj), m = pts[Math.floor(pts.length / 2)]
      this._label('construction', `${name} · under construction`, 'metro', m[0], 4, m[1])
    }
  }

  _candidates(selected, others, proj) {
    // feasible-but-not-selected and rejected pairs: thin lines, for context only
    const line = (feats, color, name) => {
      const pts = feats.flatMap(f => {
        const c = f.geometry.coordinates.map(proj)
        return c.slice(0, -1).flatMap((p, i) => [new THREE.Vector3(p[0], 1.4, p[1]), new THREE.Vector3(c[i + 1][0], 1.4, c[i + 1][1])])
      })
      this._layer(name).add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.3 })))
    }
    line(others.filter(f => f.properties.status === 'feasible'), '#7aa2ff', 'feasible')
    line(others.filter(f => f.properties.status.startsWith('rejected')), '#ff5c7a', 'rejected')

    // Candidates are drawn over buildings (no depth test): they are what the user is here to inspect.
    const group = this._layer('candidates')
    const over = { side: THREE.DoubleSide, depthTest: false, transparent: true, toneMapped: false }
    this.halo = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ color: '#ffffff', ...over }))
    this.halo.visible = false
    this.halo.renderOrder = 9
    group.add(this.halo)
    this.hoverHalo = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({
      color: '#ffffff', ...over, opacity: 0.4 }))
    this.hoverHalo.visible = false
    this.hoverHalo.renderOrder = 9
    group.add(this.hoverHalo)
    const endGeo = new THREE.CylinderGeometry(1.8, 1.8, 6, 16)
    this.ends = [0, 1].map(() => {
      const m = new THREE.Mesh(endGeo, new THREE.MeshBasicMaterial({ color: '#ffffff', depthTest: false }))
      m.renderOrder = 13
      m.visible = false
      group.add(m)
      return m
    })
    const bridges = this._layer('bridges'), decks = []
    // warm light concrete, so decks read apart from the blue-grey buildings
    const concrete = new THREE.MeshStandardMaterial({ color: '#d6cbb8', roughness: 0.8, metalness: 0.0, side: THREE.DoubleSide })
    const PIER = new THREE.CylinderGeometry(1.1, 1.3, 1, 12).translate(0, 0.5, 0)
    for (const c of selected) {
      const pts = c.feature.geometry.coordinates.map(proj)
      const p = c.props, grade = (p.road_crossings || 0) + (p.worksite_crossings || 0) > 0
      // flat candidates keep their old height; bridges lift the ribbon onto the deck top
      const br = grade ? bridgePath(pts) : null
      const path = br ? br.path : pts.map(q => [q[0], 0, q[1]])
      let deck = null
      if (br) {
        const ps = []
        const n = Math.floor((br.L - 2 * 12) / BRIDGE.pierEvery)
        for (let i = 0; i <= n; i++) {
          const s0 = 12 + (n ? i * (br.L - 24) / n : br.L / 2 - 12), hh = br.h(s0) - TH
          if (hh < 1.5) continue   // too low on the ramp: an embankment, not a pier
          const t = s0 / br.L, [a, b] = [pts[0], pts[pts.length - 1]]
          ps.push([a[0] + (b[0] - a[0]) * t, hh, a[1] + (b[1] - a[1]) * t])
        }
        deck = new THREE.Group()
        deck.userData.mat = concrete.clone()
        deck.add(new THREE.Mesh(sweep(br.path, DECK_SECTION), deck.userData.mat))
        if (ps.length) {
          // this bridge's piers: one InstancedMesh (a single draw call however many piers)
          const inst = new THREE.InstancedMesh(PIER, deck.userData.mat, ps.length), m4 = new THREE.Matrix4()
          ps.forEach(([x, hh, z], i) => inst.setMatrixAt(i, m4.makeScale(1, hh, 1).setPosition(x, 0, z)))
          inst.instanceMatrix.needsUpdate = true
          deck.add(inst)
        }
        bridges.add(deck)
        decks.push(deck)
      }
      const lift = br ? 0.15 : 2.6, glowLift = br ? 0.05 : 2.4
      const glow = new THREE.Mesh(ribbon3(path, -12, 12, glowLift), new THREE.MeshBasicMaterial({
        ...over, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false }))
      glow.renderOrder = 8
      const mesh = new THREE.Mesh(ribbon3(path, -4, 4, lift),
        plannedStripes(new THREE.MeshBasicMaterial({ color: '#cccccc', ...over }), this.uniforms))
      mesh.renderOrder = 10
      mesh.userData.key = c.key
      group.add(glow, mesh)
      const [a, b] = [pts[0], pts[pts.length - 1]]
      this.candidates.set(c.key, { key: c.key, mesh, glow, pts, path, bridge: br, deck,
        center: new THREE.Vector3((a[0] + b[0]) / 2, br ? br.top : 0, (a[1] + b[1]) / 2) })
    }
    this.bridgeCount = decks.length
  }

  setCandidateColors(fn) {
    for (const [key, c] of this.candidates) { const col = fn(key); c.mesh.material.color.copy(col); c.glow.material.color.copy(col) }
  }

  // per-candidate look from the selection and hover state
  _restyle() {
    const sel = this._selKey, hov = this._hoverKey
    for (const [k, c] of this.candidates) {
      // fade the others hard when one is selected, so their colour is not mistaken for the traffic change on roads;
      // a hovered candidate always lights up, even while faded
      const dim = sel && k !== sel && k !== hov
      // hovering with nothing selected: a spotlight, the others step back
      const back = !sel && hov && k !== hov
      c.mesh.material.opacity = dim ? 0.15 : back ? 0.35 : 1
      c.glow.visible = !dim && !back
      c.glow.material.opacity = k === hov ? 0.7 : 0.22
      c.lift = k === hov ? 2.5 : 0   // animated in _frame; small, so the pointer stays on it
      if (c.deck) c.deck.userData.mat.emissive.copy(k === hov ? c.mesh.material.color : BLACK).multiplyScalar(k === hov ? 0.45 : 0)
      c.mesh.renderOrder = k === sel ? 12 : k === hov ? 11 : 10
      // ~30 bridges overlap at a few seed junctions: with a selection, show only its deck (and the hovered one)
      if (c.deck) c.deck.visible = !sel || k === sel || k === hov
    }
  }

  // text: optional floating label (used when hovering from the list or chart, where no map tooltip shows)
  setHovered(key, text) {
    if (!this.hoverHalo || key === this._hoverKey) return
    this._hoverKey = key
    this._restyle()
    const c = key && key !== this._selKey && this.candidates.get(key)
    this.hoverHalo.visible = !!c
    if (c) {
      this.hoverHalo.geometry.dispose()
      this.hoverHalo.geometry = ribbon3(c.path, -6.5, 6.5, c.bridge ? 0.3 : 2.9)
      this.hoverHalo.position.y = c.mesh.position.y
    }
    if (!this.hoverLabel) {
      const el = document.createElement('div')
      el.className = 'label hover'
      this.hoverLabel = new CSS2DObject(el)
      this._layer('candidates').add(this.hoverLabel)
    }
    const lc = key && this.candidates.get(key)
    this.hoverLabel.visible = !!(lc && text)
    if (lc && text) {
      this.hoverLabel.element.textContent = text
      this.hoverLabel.position.set(lc.center.x, 22 + lc.center.y, lc.center.z)
    }
    // end markers follow the hovered candidate, then fall back to the selected one
    const show = c || (this._selKey && this.candidates.get(this._selKey))
    this.ends.forEach(m => { m.visible = !!show })
    if (show) [show.pts[0], show.pts[show.pts.length - 1]].forEach((p, i) => this.ends[i].position.set(p[0], 3, p[1]))
  }

  setSelected(key) {
    if (!this.halo) return   // not built yet
    this._selKey = key
    this._restyle()
    if (this._hoverKey === key) this.hoverHalo.visible = false
    const c = key && this.candidates.get(key)
    this.halo.visible = !!c
    this.ends.forEach(m => { m.visible = !!c })
    if (!c) return
    this.halo.geometry.dispose()
    this.halo.geometry = ribbon3(c.path, -7, 7, c.bridge ? 0.25 : 3)
    ;[c.pts[0], c.pts[c.pts.length - 1]].forEach((p, i) => this.ends[i].position.set(p[0], 3, p[1]))
  }

  focus(key) {
    const c = this.candidates.get(key)
    if (!c) return
    const t0 = this.controls.target.clone(), p0 = this.camera.position.clone()
    // aim a little left of the candidate so the detail card (bottom-left) does not cover it
    // bridges: a low, oblique view so the deck, ramps and piers read as 3D; flat roads: the usual top-down view
    const t1 = c.center.clone().add(c.bridge ? new THREE.Vector3(-40, 0, 20) : new THREE.Vector3(-120, 0, 60))
    const p1 = t1.clone().add(c.bridge ? new THREE.Vector3(160, 110, 230) : new THREE.Vector3(200, 620, 420))
    const start = performance.now()
    this._tween = () => {
      const k = Math.min(1, (performance.now() - start) / 1000), e = 1 - Math.pow(1 - k, 3)
      this.controls.target.lerpVectors(t0, t1, e)
      this.camera.position.lerpVectors(p0, p1, e)
      if (k === 1) this._tween = null
    }
  }

  _pick(ev) {
    const rect = this.renderer.domElement.getBoundingClientRect()
    this.pointer.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1)
    this.raycaster.setFromCamera(this.pointer, this.camera)
    if (this.layers.candidates?.visible) {
      const meshes = [...this.candidates.values()].map(c => c.mesh)
      const hit = this.raycaster.intersectObjects(meshes, false)[0]
      if (hit) return { kind: 'candidate', key: hit.object.userData.key }
    }
    if (this.layers.roads?.visible && this.roadMesh) {
      const hit = this.raycaster.intersectObject(this.roadMesh, false)[0]
      if (hit) { const i = this.triRoad[hit.faceIndex]; return { kind: 'road', index: i, props: this.roadProps[i] } }
    }
    return null
  }

  _bindPointer() {
    const el = this.renderer.domElement
    let down = null, last = 0
    el.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY] })
    el.addEventListener('pointerup', e => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 5) this.onPick(this._pick(e))
      down = null
    })
    el.addEventListener('pointermove', e => {
      if (e.buttons || performance.now() - last < 60) return
      last = performance.now()
      const hit = this._pick(e)
      el.style.cursor = hit ? 'pointer' : 'grab'
      this.onHover(hit, e.clientX, e.clientY)
    })
    el.addEventListener('pointerleave', () => this.onHover(null))
  }
}
