# CGVR roadmap: making the 3D component heavier

For whoever owns the frontend. This lists graphics upgrades for `src/scene.js`, ranked by how much they add for the
course for the effort.

## What the scene has today

Three.js 0.169 with React and Vite (`src/scene.js`, about 490 lines):

- buildings as one merged `ExtrudeGeometry` mesh, with vertex colours
- roads as ribbons, with the congestion heatmap as per-vertex colours on `MeshBasicMaterial`
- candidate roads with a glow ribbon and end markers
- hover and click picking with `Raycaster`, and a camera fly-to on select
- fog, a hemisphere light and two directional lights

It does not yet have instancing, custom shaders, shadows, post-processing, moving traffic, VR, level of detail,
or real 3D bridges for candidates. Those are where the extra graphics content can come from.

## Ranked upgrades

### 1. Animated vehicles (highest impact)

- **Backend:** make SUMO write car positions for the baseline and the top 3 micro runs.
  - Add `--fcd-output fcd.xml --fcd-output.geo --device.fcd.period 1` through the `extra_args` parameter of
    `urban.sim.run()`.
  - Thin the output to one sample every 2 s.
  - Export it as compact JSON, `[t][veh] = x, z, angle, speed`.
- **Frontend:** draw every car with one `THREE.InstancedMesh` of about 10k instances.
  - Update positions each frame with `setMatrixAt`, interpolating between samples.
  - Colour each car by its speed with `setColorAt`.
  - Add before/after playback with a time slider.
- **Course value:** covers instancing, animation and a large real-time data load.
- This is the only item that needs backend work.

### 2. Custom GLSL shaders

Everything in the scene is `MeshBasic`, `Lambert` or `Phong` right now.

- **Roads:** a `ShaderMaterial` with flow dashes that move at the simulated speed.
  - Drive it with a `uTime` uniform and a per-vertex speed attribute.
  - Blend before and after with a `uMix` uniform, instead of rebuilding the colours.
- **Candidates:** a scrolling "proposed road" dash with a fresnel glow.
- **Demolished buildings** (`buildings_hit` in `candidates.geojson`): a noise-based dissolve.

### 3. Real lighting

- Turn on `renderer.shadowMap` with a PCF soft shadow camera on the sun. Let buildings cast and receive shadows.
- Add an `EffectComposer` chain:
  - `UnrealBloomPass` on congested roads
  - SSAO
  - FXAA
- All of these ship in `three/examples/jsm`, so there is nothing new to install.
- Add a day/night cycle: move the sun with the sim clock, and add street lights as instanced point sprites.

### 4. Grade-separated candidates in true 3D

Candidates that cross a road or the metro works (34 of the 40) are bridges or underpasses by design. Draw them as
raised decks:

- `ExtrudeGeometry` along a `CatmullRomCurve3` that carries height
- ramps at both ends
- instanced piers under the deck

### 5. WebXR (the VR half of CGVR)

- Set `renderer.xr.enabled = true` and add `VRButton`. Both are built into Three.js.
- Show the city as a tabletop model.
- Pick candidates with a controller ray that reuses the existing `Raycaster`.
- No headset? Test with the WebXR emulator browser extension.

### 6. Performance as a graded metric

- Building LOD: full extrusions near the camera, simple boxes far away.
- A HUD for frustum culling and draw calls, from `renderer.info` and `stats.js`.
- Report FPS against vehicle count. This ties back to the PAGP speedup story.

### 7. Cheaper extras

- building heights from OSM `building:levels`, at about 3 m per level
- a procedural window texture, done in a shader
- SRTM terrain as a displaced plane
- the metro worksite (`construction.geojson`) as animated barrier geometry

## Suggested order

Do 1, then 2, then 4, then 5. Together they cover instancing, GLSL, procedural geometry, animation and VR.
