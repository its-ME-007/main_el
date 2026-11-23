import * as THREE from 'three'

const lerpStops = (stops, t) => {
  t = Math.min(1, Math.max(0, t))
  for (let i = 1; i < stops.length; i++) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1], [t1, c1] = stops[i]
      return c0.clone().lerp(c1, (t - t0) / (t1 - t0 || 1))
    }
  }
  return stops[stops.length - 1][1].clone()
}
const c = hex => new THREE.Color(hex)

export const NO_TRAFFIC = c('#3b4456')

// Congestion: speed as a share of the limit. 1 = free flow (green), 0 = standstill (red).
const SPEED_STOPS = [[0, c('#b3123a')], [0.15, c('#e8452c')], [0.4, c('#f5a623')], [0.7, c('#c9d84a')], [1, c('#2fbf71')]]
export const speedColor = rel => lerpStops(SPEED_STOPS, rel)
export const SPEED_LEGEND = { title: 'Speed vs limit', stops: SPEED_STOPS, left: 'jammed', right: 'free flow' }

// Change in an edge's total delay (seconds) with the candidate road: blue = less delay, red = more.
const CHANGE_STOPS = [[0, c('#2b8cff')], [0.5, c('#3a4050')], [1, c('#ff3b4e')]]
const CHANGE_SCALE = Math.log10(1 + 20000)
export const changeColor = delta => {
  const m = Math.min(1, Math.log10(1 + Math.abs(delta)) / CHANGE_SCALE)
  return lerpStops(CHANGE_STOPS, 0.5 + Math.sign(delta) * m / 2)
}
export const CHANGE_LEGEND = { title: 'Change in delay on each road', stops: CHANGE_STOPS, left: 'less delay', right: 'more delay' }

// Candidate score: positive = improves the network (green), negative = makes it worse (red).
const SCORE_STOPS = [[0, c('#ff3b4e')], [0.45, c('#ff8a5c')], [0.5, c('#d9d9d9')], [0.55, c('#7ee0a1')], [1, c('#18c964')]]
export const scoreColor = s => s == null ? c('#8a8f99') : lerpStops(SCORE_STOPS, 0.5 + Math.max(-1, Math.min(1, s / 20)) / 2)
export const SCORE_LEGEND = { title: 'Candidate score', stops: SCORE_STOPS, left: '≤ −20 worse', right: '+20 better' }

export const cssGradient = stops => `linear-gradient(90deg, ${stops.map(([t, col]) => `#${col.getHexString()} ${t * 100}%`).join(', ')})`
