// Animated vehicles (CGVR): SUMO floating car data replayed as one InstancedMesh, so hundreds of cars cost one draw
// call. Data: traffic_<run>.json from backend urban.fcd, frames every `period` s; each frame is a flat array of
// [idx, x, z, angle, kmh, onCandidate, ...] in the scene's metric frame (x east, z south). Positions and headings are interpolated
// between frames, so playback is smooth at any speed.
import * as THREE from 'three'
import { speedColor } from './colors.js'

const CAR = { length: 4.6, width: 1.9, height: 1.6 }
// cars are a few pixels wide from the default camera; scale them up with distance so they stay visible
const sizeFor = dist => Math.min(5, Math.max(1, dist / 320))
const FREE_KMH = 50   // colour scale: 0 km/h = red (stopped) ... 50+ km/h = green
const HIGHLIGHT = new THREE.Color('#3ee6ff')

export class Traffic {
  constructor(parent) {
    this.group = new THREE.Group()
    parent.add(this.group)
    // one box per car, length along z; the per-instance colour carries the speed. Lit (Lambert) so cars read as 3D,
    // not tone-mapped so the speed colours match the road legend.
    this.geo = new THREE.BoxGeometry(CAR.width, CAR.height, CAR.length).translate(0, CAR.height / 2, 0)
    this.mat = new THREE.MeshLambertMaterial({ toneMapped: false })
    this.mesh = null
    this.lift = null      // (x, z) -> deck height for cars on the candidate, or null
    this.highlight = true // colour cars that use the new road
    this.users = new Map()
    this.data = null
    this.t = 0            // seconds since the window start
    this.rate = 10        // sim seconds per real second
    this.playing = false
    this._m = new THREE.Matrix4(); this._q = new THREE.Quaternion(); this._p = new THREE.Vector3()
    this._s = new THREE.Vector3(); this._c = new THREE.Color(); this._up = new THREE.Vector3(0, 1, 0)
  }

  load(data) {
    this.data = data
    this.stride = data.stride || 5   // 6 = with the on-candidate flag (urban.fcd)
    // per frame: vehicle idx -> offset into the flat row, to find the same car in the next frame
    this.index = data.frames.map(f => {
      const m = new Map()
      for (let o = 0; o < f.length; o += this.stride) m.set(f[o], o)
      return m
    })
    // cars that drive on the new road at some point (flag in any frame), and when each first gets onto it
    this.users = new Map()
    if (this.stride > 5) data.frames.forEach((f, fi) => {
      for (let o = 0; o < f.length; o += this.stride) if (f[o + 5] && !this.users.has(f[o])) this.users.set(f[o], fi * data.period)
    })
    if (this.mesh) { this.group.remove(this.mesh); this.mesh.dispose() }
    this.mesh = new THREE.InstancedMesh(this.geo, this.mat, Math.max(1, data.max))
    this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(3 * Math.max(1, data.max)), 3)
    this.mesh.frustumCulled = false   // instances move; the base geometry's bounds would cull them wrongly
    this.group.add(this.mesh)
    this.t = Math.min(this.t, this.duration)
    this.draw(1)
  }

  get duration() { return this.data ? (this.data.frames.length - 1) * this.data.period : 0 }
  get count() { return this.mesh?.count ?? 0 }
  // cars that have reached the new road by the current time
  get usedSoFar() { let n = 0; for (const t0 of this.users.values()) if (t0 <= this.t) n++; return n }

  // dt = real seconds since the last frame; size = car scale from the camera distance
  update(dt, dist) {
    if (!this.data) return
    if (this.playing) {
      this.t += dt * this.rate
      if (this.t >= this.duration) this.t = 0   // loop
    }
    this.draw(sizeFor(dist))
  }

  draw(size) {
    const d = this.data, fi = Math.min(d.frames.length - 2, Math.floor(this.t / d.period))
    if (fi < 0) return
    const k = this.t / d.period - fi, A = d.frames[fi], B = d.frames[fi + 1], nextIdx = this.index[fi + 1]
    let n = 0
    const S = this.stride
    for (let o = 0; o < A.length; o += S) {
      const ob = nextIdx.get(A[o])
      let x = A[o + 1], z = A[o + 2], ang = A[o + 3], kmh = A[o + 4]
      if (ob !== undefined) {
        x += (B[ob + 1] - x) * k
        z += (B[ob + 2] - z) * k
        let da = B[ob + 3] - ang
        da -= 360 * Math.round(da / 360)   // shortest way round
        ang += da * k
        kmh += (B[ob + 4] - kmh) * k
      } else if (k > 0.5) continue   // leaves the box (or the network) before the next sample
      // SUMO angle: degrees clockwise from north; north is -z here, so rotate by -angle about +y
      this._q.setFromAxisAngle(this._up, -ang * Math.PI / 180)
      // cars on the new road ride on its bridge deck when it is one (lift = deck height along the candidate)
      this._p.set(x, 0.9 + (S > 5 && A[o + 5] && this.lift ? this.lift(x, z) : 0), z)
      // highlight: users of the new road in cyan and 1.6x larger for their whole trip through the box
      const user = this.highlight && this.users.has(A[o])
      const sz = user ? size * 1.6 : size
      this._s.set(sz, sz, sz)
      this.mesh.setMatrixAt(n, this._m.compose(this._p, this._q, this._s))
      this.mesh.setColorAt(n, user ? this._c.copy(HIGHLIGHT) : this._c.copy(speedColor(Math.min(1, kmh / FREE_KMH))))
      n++
    }
    this.mesh.count = n
    this.mesh.instanceMatrix.needsUpdate = true
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true
  }

  setVisible(v) { this.group.visible = v }

  dispose() {
    if (this.mesh) { this.group.remove(this.mesh); this.mesh.dispose() }
    this.geo.dispose(); this.mat.dispose()
    this.group.parent?.remove(this.group)
  }
}
