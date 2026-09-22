// 3D warehouse view. Built procedurally from the same /warehouse grid the robots
// plan on, so every rack sits exactly on a shelf cell and robots drive the real aisles.
// Reads live fleet data from window.dash (set in index.html); never talks to robots.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const host = document.getElementById('stage3d');
const MARGIN = 3; // cells of floor around the operating grid
const S = 1.8;    // metres per grid cell in 3D: wide aisles, same robot logic

// ---------------------------------------------------------------- renderer
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
host.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0f14);
scene.fog = new THREE.Fog(0x0b0f14, 60, 130);
scene.environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;

const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
camera.position.set(-18, 22, 26);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.48;
controls.minDistance = 3;
controls.maxDistance = 80;
controls.zoomSpeed = 7.5; // Made zoom 3x faster as requested

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
composer.addPass(new UnrealBloomPass(new THREE.Vector2(1, 1), 0.6, 0.5, 0.82));
composer.addPass(new OutputPass());

new ResizeObserver(() => {
  const w = host.clientWidth, h = host.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h);
  composer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}).observe(host);

// ---------------------------------------------------------------- lights
scene.add(new THREE.HemisphereLight(0xcfe3ff, 0x20252c, 0.6));
const sun = new THREE.DirectionalLight(0xfff4e6, 1.8);
sun.position.set(16, 34, 12);
sun.castShadow = true;
sun.shadow.mapSize.set(4096, 4096);
Object.assign(sun.shadow.camera, { left: -30, right: 30, top: 26, bottom: -26, near: 1, far: 100 });
sun.shadow.normalBias = 0.03;
scene.add(sun);

// ---------------------------------------------------------------- helpers
function rng(seed) { // mulberry32: same box layout every reload
  return () => {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rand = rng(7);
const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.1, ...o });
const glow = (color, intensity = 2.5) => new THREE.MeshStandardMaterial({ color: 0x000000, emissive: color, emissiveIntensity: intensity });

// Instanced parts: thousands of rack pieces in a handful of draw calls.
const unitBox = new THREE.BoxGeometry(1, 1, 1);
const batches = new Map();
function part(mat, x, y, z, sx, sy, sz, color) {
  if (!batches.has(mat)) batches.set(mat, []);
  const m = new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), new THREE.Quaternion(), new THREE.Vector3(sx, sy, sz));
  batches.get(mat).push({ m, color });
}
function flushParts() {
  for (const [mat, list] of batches) {
    const mesh = new THREE.InstancedMesh(unitBox, mat, list.length);
    list.forEach((p, i) => { mesh.setMatrixAt(i, p.m); if (p.color) mesh.setColorAt(i, new THREE.Color(p.color)); });
    mesh.castShadow = mesh.receiveShadow = true;
    scene.add(mesh);
  }
  batches.clear();
}

function labelTexture(draw, w = 256, h = 96) {
  const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
  draw(cv.getContext('2d'), w, h);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// ---------------------------------------------------------------- world
const M = {
  upright: std(0x2c5aa0, { metalness: 0.6, roughness: 0.4 }),
  beam: std(0xe0701c, { metalness: 0.5, roughness: 0.45 }),
  deck: std(0x7d8590, { metalness: 0.7, roughness: 0.5 }),
  box: std(0xffffff, { roughness: 0.85 }),
  pallet: std(0x9a7a52, { roughness: 0.9 }),
  dark: std(0x22272e, { metalness: 0.4, roughness: 0.5 }),
  steel: std(0x9aa3ad, { metalness: 0.8, roughness: 0.35 }),
};
const BOX_COLORS = [0xb98a55, 0xa57a48, 0xc79b63, 0xb08050, 0xd2a86e, 0x2a6fd6];

let ROWS = 0, COLS = 0, grid = null;
const cellPos = (r, c, y = 0) => new THREE.Vector3((c - COLS / 2 + 0.5) * S, y, (r - ROWS / 2 + 0.5) * S);
const isShelf = (r, c) => r >= 0 && r < ROWS && c >= 0 && c < COLS && grid[r][c] === 1;

function floorTexture(wm) {
  const P = 64, W = (COLS + 2 * MARGIN) * P, H = (ROWS + 2 * MARGIN) * P;
  const X = c => (c + MARGIN) * P, Y = r => (r + MARGIN) * P;
  return labelTexture((g) => {
    g.fillStyle = '#4a4f56'; g.fillRect(0, 0, W, H);
    for (let i = 0; i < W * H / 30; i++) { // concrete speckle
      const v = 60 + (rand() * 40) | 0;
      g.fillStyle = `rgba(${v},${v + 2},${v + 6},0.35)`;
      g.fillRect(rand() * W, rand() * H, 2, 2);
    }
    g.strokeStyle = 'rgba(0,0,0,0.3)'; g.lineWidth = 2; // slab seams
    for (let x = 0; x <= W; x += P * 4) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
    for (let y = 0; y <= H; y += P * 4) { g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
    g.strokeStyle = 'rgba(255,255,255,0.06)'; g.lineWidth = 1; // nav grid
    for (let c = 0; c <= COLS; c++) { g.beginPath(); g.moveTo(X(c), Y(0)); g.lineTo(X(c), Y(ROWS)); g.stroke(); }
    for (let r = 0; r <= ROWS; r++) { g.beginPath(); g.moveTo(X(0), Y(r)); g.lineTo(X(COLS), Y(r)); g.stroke(); }
    g.strokeStyle = '#e8b923'; g.lineWidth = 6; // operating area boundary
    g.strokeRect(X(0) - 6, Y(0) - 6, COLS * P + 12, ROWS * P + 12);

    // yellow safety lines around every rack footprint
    g.lineWidth = 4; g.strokeStyle = '#e8b923';
    for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) {
      if (!isShelf(r, c)) continue;
      g.fillStyle = 'rgba(20,22,26,0.45)'; g.fillRect(X(c), Y(r), P, P);
      const edge = (x1, y1, x2, y2) => { g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke(); };
      if (!isShelf(r - 1, c)) edge(X(c), Y(r) - 3, X(c + 1), Y(r) - 3);
      if (!isShelf(r + 1, c)) edge(X(c), Y(r + 1) + 3, X(c + 1), Y(r + 1) + 3);
      if (!isShelf(r, c - 1)) edge(X(c) - 3, Y(r), X(c) - 3, Y(r + 1));
      if (!isShelf(r, c + 1)) edge(X(c + 1) + 3, Y(r), X(c + 1) + 3, Y(r + 1));
    }
    g.fillStyle = 'rgba(255,207,107,0.18)'; // choke points
    wm.choke_points.forEach(([r, c]) => {
      const cx = X(c) + P / 2, cy = Y(r) + P / 2, s = P * 0.18;
      g.beginPath(); g.moveTo(cx, cy - s); g.lineTo(cx + s, cy); g.lineTo(cx, cy + s); g.lineTo(cx - s, cy); g.fill();
    });
    const zone = (cells, color, label) => cells.forEach(([r, c], i) => {
      const x = X(c) + 4, y = Y(r) + 4, s = P - 8;
      g.save(); g.beginPath(); g.rect(x, y, s, s); g.clip();
      g.strokeStyle = color + '55'; g.lineWidth = 5;
      for (let d = -s; d < s * 2; d += 14) { g.beginPath(); g.moveTo(x + d, y); g.lineTo(x + d - s, y + s); g.stroke(); }
      g.restore();
      g.strokeStyle = color; g.lineWidth = 4; g.strokeRect(x, y, s, s);
      // Removed the central pill and P1/D1 text labels per user request
    });
    // zone(wm.pickup, '#3d9cff', 'P');
    // zone(wm.dropoff, '#ff5fc8', 'D');
    zone(wm.charge, '#37f0b0', 'C');

    // aisle tags at the top of every aisle running between two racks
    let aisle = 0;
    g.font = 'bold 11px sans-serif'; g.textAlign = 'center';
    for (let c = 0; c < COLS; c++) for (let r = 0; r < ROWS; r++) {
      const inAisle = (rr) => !isShelf(rr, c) && isShelf(rr, c - 1) && isShelf(rr, c + 1);
      if (!inAisle(r) || inAisle(r - 1)) continue;
      const cx = X(c) + P / 2, cy = Y(r) + 14;
      g.fillStyle = 'rgba(9,12,16,0.8)'; g.beginPath(); g.roundRect(cx - 18, cy - 9, 36, 17, 4); g.fill();
      g.fillStyle = '#dfe7ee'; g.fillText(`A-${String(++aisle).padStart(2, '0')}`, cx, cy + 4);
    }
  }, W, H);
}

function rack(r, c) {
  const p = cellPos(r, c), h = S / 2, I = 0.4, H = 2.6, levels = [0.14, 0.95, 1.76, 2.56];
  const x0 = p.x - h + (isShelf(r, c - 1) ? 0 : I), x1 = p.x + h - (isShelf(r, c + 1) ? 0 : I);
  const z0 = p.z - h + (isShelf(r - 1, c) ? 0 : I), z1 = p.z + h - (isShelf(r + 1, c) ? 0 : I);
  const w = x1 - x0, d = z1 - z0, cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
  // an edge shared with the next shelf cell is drawn by that cell, not twice
  const xs = isShelf(r, c + 1) ? [x0] : [x0, x1], zs = isShelf(r + 1, c) ? [z0] : [z0, z1];
  for (const x of xs) for (const z of zs) part(M.upright, x, H / 2, z, 0.07, H + 0.05, 0.07);
  levels.forEach((y, li) => {
    for (const z of zs) part(M.beam, cx, y, z, w, 0.09, 0.05);
    if (li === levels.length - 1) return; // no top deck: keeps cartons visible from above
    part(M.deck, cx, y + 0.03, cz, w - 0.02, 0.025, d - 0.02);
    let x = x0 + 0.06;
    while (x < x1 - 0.3) {
      const bw = Math.min(0.25 + rand() * 0.3, x1 - 0.06 - x), bh = 0.2 + rand() * 0.4, bd = d * (0.45 + rand() * 0.35);
      if (rand() < 0.85) part(M.box, x + bw / 2, y + 0.05 + bh / 2, cz + (rand() - 0.5) * (d - bd) * 0.8, bw - 0.03, bh, bd,
        BOX_COLORS[(rand() * BOX_COLORS.length) | 0]);
      x += bw;
    }
  });
}

function buildWorld(wm) {
  grid = wm.grid; ROWS = grid.length; COLS = grid[0].length;
  const FW = COLS + 2 * MARGIN, FH = ROWS + 2 * MARGIN;

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(FW * S, FH * S),
    new THREE.MeshStandardMaterial({ map: floorTexture(wm), roughness: 0.8, metalness: 0.05 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  floor.name = 'floor';
  scene.add(floor);

  // Building shell rendered from the inside only: walls between the camera and the
  // floor are back-face culled, so orbiting always gives a clean cutaway view.
  const wallTex = labelTexture((g, w, h) => {
    g.fillStyle = '#2a3038'; g.fillRect(0, 0, w, h);
    g.fillStyle = '#323a44';
    for (let x = 0; x < w; x += 16) g.fillRect(x, 0, 8, h);
    g.fillStyle = '#e8b923'; g.fillRect(0, h * 0.86, w, h * 0.04);
  }, 128, 256);
  wallTex.wrapS = THREE.RepeatWrapping; wallTex.repeat.set(24, 1);
  const shell = new THREE.Mesh(new THREE.BoxGeometry(FW * S, 6, FH * S),
    new THREE.MeshStandardMaterial({ map: wallTex, side: THREE.BackSide, roughness: 0.7, metalness: 0.3 }));
  shell.position.y = 3 - 0.02;
  scene.add(shell);

  for (let r = 0; r < ROWS; r++) for (let c = 0; c < COLS; c++) if (grid[r][c] === 1) rack(r, c);

  // pick faces behind each pickup cell, packing conveyors behind dropoff, chargers behind docks
  wm.pickup.forEach(([r, c]) => {
    rack(r - 1, c);
    const pole = cellPos(r - 1, c + 0.5);
    part(M.dark, pole.x, 1.3, pole.z + 0.45, 0.05, 2.6, 0.05);
    const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.09, 16, 12), glow(0x3d9cff, 4));
    beacon.position.set(pole.x, 2.65, pole.z + 0.45);
    scene.add(beacon);
  });
  wm.dropoff.forEach(([r, c]) => {
    const p = cellPos(r + 1, c);
    part(M.steel, p.x, 0.42, p.z - 0.05, 2.6, 0.06, 0.8);
    part(M.dark, p.x, 0.47, p.z - 0.05, 2.5, 0.04, 0.6);
    for (const dx of [-1.2, 1.2]) for (const dz of [-0.4, 0.3]) part(M.steel, p.x + dx, 0.2, p.z + dz, 0.06, 0.4, 0.06);
    for (let i = 0; i < 3; i++) part(M.box, p.x - 0.8 + i * 0.75, 0.62, p.z - 0.05, 0.36, 0.26, 0.34, BOX_COLORS[i]);
    const light = new THREE.Mesh(new THREE.BoxGeometry(2.4, 0.04, 0.04), glow(0xff5fc8, 3));
    light.position.set(p.x, 0.5, p.z + 0.36);
    scene.add(light);
  });
  wm.charge.forEach(([r, c]) => {
    const p = cellPos(r + 1, c);
    part(M.dark, p.x, 0.45, p.z + 0.1, 0.6, 0.9, 0.35);
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.34, 0.2), glow(0x37f0b0, 2.5));
    screen.position.set(p.x, 0.65, p.z - 0.08);
    screen.rotation.y = Math.PI;
    scene.add(screen);
  });

  // pallet stacks along the free margin for a lived-in look
  for (let i = 0; i < 10; i++) {
    const side = i % 2 ? -1 : 1, p = cellPos(1 + i, side > 0 ? COLS + 1.2 : -2.2);
    if (i >= ROWS - 1) break;
    const stacks = 1 + ((rand() * 3) | 0);
    for (let s = 0; s < stacks; s++) {
      part(M.pallet, p.x, 0.07 + s * 0.55, p.z, 0.9, 0.12, 0.9);
      part(M.box, p.x, 0.36 + s * 0.55, p.z, 0.8, 0.42, 0.8, BOX_COLORS[(rand() * 5) | 0]);
    }
  }

  flushParts();
}

// ---------------------------------------------------------------- robots
const STATE_COLORS = { move: 0x37f0b0, wait: 0xffb454, alert: 0xff5c72, charge: 0x4da3ff, idle: 0x8a96a3 };
function stateKey(rb) {
  const d = rb.display_status || '';
  if (rb.state === 'CHARGING' || rb.state === 'EN_ROUTE_TO_CHARGE') return 'charge';
  if (d === 'RECALCULATING') return 'alert';
  if (d.startsWith('YIELDING') || d === 'WAITING' || d === 'ASKING TO MOVE') return 'wait';
  if (rb.state === 'IDLE' && d !== 'MAKING WAY') return 'idle';
  return 'move';
}
function statusText(rb) {
  const d = rb.display_status || '';
  if (d.startsWith('YIELDING')) return `YIELD → ${d.split('|')[1]}`;
  if (d) return d;
  if (rb.state === 'EN_ROUTE_TO_PICKUP') return 'TO PICKUP';
  if (rb.state === 'EN_ROUTE_TO_DROPOFF') return 'DELIVERING';
  if (rb.state === 'EN_ROUTE_TO_CHARGE') return 'TO CHARGER';
  return rb.state.replaceAll('_', ' ');
}

const bodyGeo = new RoundedBoxGeometry(0.62, 0.2, 0.62, 3, 0.06);
const wheelGeo = new THREE.CylinderGeometry(0.07, 0.07, 0.05, 16).rotateZ(Math.PI / 2);
const shadowTex = labelTexture((g, w, h) => {
  const grd = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
  grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, w, h);
}, 128, 128);

const fleet = new Map(); // robot_id -> view object

function makeRobot(id, color) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(bodyGeo, std(0x2b3139, { metalness: 0.5, roughness: 0.35 }));
  body.position.y = 0.17; body.castShadow = true;
  const shell = new THREE.Mesh(new RoundedBoxGeometry(0.64, 0.05, 0.64, 2, 0.02), std(0xe9edf1, { roughness: 0.3 }));
  shell.position.y = 0.29; shell.castShadow = true;
  const band = new THREE.Mesh(new THREE.BoxGeometry(0.635, 0.03, 0.635), glow(color, 2.2));
  band.position.y = 0.2;
  const lift = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.03, 32), std(0x6c7580, { metalness: 0.8 }));
  lift.position.y = 0.33;
  const lidar = new THREE.Group();
  const puck = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.07, 20), std(0x111418));
  const eye = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.02, 0.13), glow(0xff3344, 3));
  eye.position.y = 0.01;
  lidar.add(puck, eye);
  lidar.position.set(0, 0.2, 0.33);
  const head = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.035, 0.02), glow(0xffffff, 2)); // front light bar
  head.position.set(0, 0.17, 0.315);
  const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 8), glow(STATE_COLORS.idle, 4));
  beacon.position.set(0.22, 0.34, -0.22);
  const wheels = [];
  for (const dx of [-0.3, 0.3]) for (const dz of [-0.18, 0.18]) {
    const w = new THREE.Mesh(wheelGeo, M.dark);
    w.position.set(dx, 0.07, dz);
    wheels.push(w); g.add(w);
  }
  const cargo = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.34, 0.44), std(0xb98a55, { roughness: 0.9 }));
  cargo.position.y = 0.52; cargo.castShadow = true; cargo.visible = false;
  const halo = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 1.5),
    new THREE.MeshBasicMaterial({ map: shadowTex, color, transparent: true, opacity: 0.35, depthWrite: false, blending: THREE.AdditiveBlending }));
  halo.rotation.x = -Math.PI / 2; halo.position.y = 0.012;
  g.add(body, shell, band, lift, lidar, head, beacon, cargo, halo);

  const label = new THREE.Sprite(new THREE.SpriteMaterial({ depthTest: false, transparent: true }));
  label.scale.set(1.3, 0.49, 1);
  label.renderOrder = 10;

  // goal beam + intent dots
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 3.5, 24, 1, true),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.16, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending }));
  beam.position.y = 1.75; beam.visible = false;
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.62, 32), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.9, depthWrite: false }));
  ring.rotation.x = -Math.PI / 2; ring.visible = false;
  const dots = Array.from({ length: 8 }, (_, i) => {
    const d = new THREE.Mesh(new THREE.CircleGeometry(0.12, 16),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 - i * 0.09, depthWrite: false }));
    d.rotation.x = -Math.PI / 2; d.visible = false;
    scene.add(d); return d;
  });
  const pathLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.8 }));
  scene.add(g, label, beam, ring, pathLine);
  return { id, g, lidar, beacon, wheels, cargo, label, beam, ring, dots, pathLine, color,
           yaw: 0, labelKey: '', init: false };
}

function updateLabel(v, rb, key) {
  const text = statusText(rb), k = `${rb.robot_id}|${Math.round(rb.battery)}|${text}|${key}`;
  if (k === v.labelKey) return;
  v.labelKey = k;
  v.label.material.map?.dispose();
  v.label.material.map = labelTexture((g, w, h) => {
    const hex = '#' + v.color.toString(16).padStart(6, '0');
    const sc = '#' + STATE_COLORS[key].toString(16).padStart(6, '0');
    g.fillStyle = 'rgba(9,12,16,0.82)';
    g.beginPath(); g.roundRect(4, 4, w - 8, h - 8, 16); g.fill();
    g.fillStyle = hex; g.fillRect(4, 18, 6, h - 36);
    g.font = 'bold 30px "Space Grotesk", sans-serif'; g.fillStyle = hex; g.textAlign = 'left';
    g.fillText(rb.robot_id, 22, 40);
    g.font = '22px "JetBrains Mono", monospace'; g.fillStyle = rb.battery < 20 ? '#ff5c72' : '#9aa6b2'; g.textAlign = 'right';
    g.fillText(`${Math.round(rb.battery)}%`, w - 18, 40);
    g.font = 'bold 20px "JetBrains Mono", monospace'; g.fillStyle = sc; g.textAlign = 'left';
    g.fillText(text.slice(0, 18), 22, 74);
  });
  v.label.material.needsUpdate = true;
}

const tmp = new THREE.Vector3();
function syncRobots(dt, time) {
  const data = window.dash?.robots || {};
  for (const [id, rb] of Object.entries(data)) {
    if (!rb.pos) continue;
    let v = fleet.get(id);
    if (!v) { v = makeRobot(id, new THREE.Color(window.dash.colorFor(id)).getHex()); fleet.set(id, v); }
    const target = cellPos(rb.pos[0], rb.pos[1]);
    const dist = v.g.position.distanceTo(target);
    if (!v.init || dist > 3 * S) { v.g.position.copy(target); v.init = true; }
    else if (dist > 1e-3) {
      // constant-speed glide (one cell per robot tick), catch up if we fall behind
      const step = Math.min(dist, Math.max(3.0 * S, dist * 4) * dt);
      tmp.subVectors(target, v.g.position).normalize();
      v.g.position.addScaledVector(tmp, step);
      const want = Math.atan2(tmp.x, tmp.z);
      v.yaw += Math.atan2(Math.sin(want - v.yaw), Math.cos(want - v.yaw)) * Math.min(1, dt * 12);
      v.wheels.forEach(w => { w.rotation.x += step / 0.07; });
    }
    v.g.rotation.y = v.yaw;
    v.g.position.y = dist > 0.02 ? Math.sin(time * 30) * 0.004 : 0; // motor vibration while driving
    v.lidar.rotation.y += dt * 9;

    const key = stateKey(rb);
    v.beacon.material.emissive.setHex(STATE_COLORS[key]);
    v.beacon.material.emissiveIntensity = key === 'wait' || key === 'alert' ? 2 + Math.sin(time * 10) * 2 : 4;
    v.cargo.visible = rb.state === 'EN_ROUTE_TO_DROPOFF';
    v.label.position.set(v.g.position.x, 1.15, v.g.position.z);
    updateLabel(v, rb, key);

    // goal beam on the current pickup / dropoff
    const goal = rb.state === 'EN_ROUTE_TO_PICKUP' ? rb.task_pickup : rb.state === 'EN_ROUTE_TO_DROPOFF' ? rb.task_dropoff : null;
    v.beam.visible = v.ring.visible = !!goal;
    if (goal) {
      const gp = cellPos(goal[0], goal[1]);
      v.beam.position.set(gp.x, 1.75, gp.z);
      v.ring.position.set(gp.x, 0.02, gp.z);
      const s = 1 + ((time * 0.8) % 1) * 0.6;
      v.ring.scale.set(s, s, s);
      v.ring.material.opacity = 1 - ((time * 0.8) % 1);
    }

    // broadcast intent (next PLAN_HORIZON cells) drawn on the floor
    const intent = (rb.intent || []).slice(1);
    v.dots.forEach((d, i) => {
      d.visible = i < intent.length;
      if (d.visible) d.position.copy(cellPos(intent[i][0], intent[i][1], 0.02));
    });
    const pts = [v.g.position.clone().setY(0.03), ...intent.map(c => cellPos(c[0], c[1], 0.03))];
    v.pathLine.geometry.setFromPoints(pts);
    v.pathLine.visible = intent.length > 0;
  }
}

// ---------------------------------------------------------------- user task queue (click floor)
const pendingGroup = new THREE.Group();
scene.add(pendingGroup);
let pendingKey = '';
function syncPending(time) {
  const q = window.dash?.taskQueue || [], cur = window.dash?.currentPickup;
  const key = JSON.stringify([q, cur]);
  if (key !== pendingKey) {
    pendingKey = key;
    pendingGroup.children.forEach(o => o.geometry.dispose());
    pendingGroup.clear();
    const marker = (cell, color) => {
      const m = new THREE.Mesh(new THREE.RingGeometry(0.35, 0.55, 32), new THREE.MeshBasicMaterial({ color, transparent: true, depthWrite: false }));
      m.rotation.x = -Math.PI / 2; m.position.copy(cellPos(cell[0], cell[1], 0.03));
      pendingGroup.add(m); return m;
    };
    q.forEach(t => {
      marker(t.pickup, 0x3d9cff); marker(t.dropoff, 0xff5fc8);
      const a = cellPos(t.pickup[0], t.pickup[1], 0.05), b = cellPos(t.dropoff[0], t.dropoff[1], 0.05);
      const mid = a.clone().lerp(b, 0.5).setY(2 + a.distanceTo(b) * 0.12);
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(new THREE.QuadraticBezierCurve3(a, mid, b).getPoints(40)),
        new THREE.LineDashedMaterial({ color: 0x7fb0ff, dashSize: 0.2, gapSize: 0.12 }));
      line.computeLineDistances();
      pendingGroup.add(line);
    });
    if (cur) marker(cur, 0x3d9cff).userData.pulse = true;
  }
  pendingGroup.children.forEach(o => { if (o.userData.pulse) o.scale.setScalar(1 + Math.sin(time * 6) * 0.25); });
}

const hover = new THREE.Mesh(new THREE.PlaneGeometry(0.94 * S, 0.94 * S).rotateX(-Math.PI / 2),
  new THREE.MeshBasicMaterial({ color: 0x37f0b0, transparent: true, opacity: 0.25, depthWrite: false }));
hover.visible = false;
scene.add(hover);

const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
function cellAt(ev) {
  const rect = renderer.domElement.getBoundingClientRect();
  ndc.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hit = ray.ray.intersectPlane(groundPlane, tmp);
  if (!hit || !grid) return null;
  const c = Math.floor(hit.x / S + COLS / 2), r = Math.floor(hit.z / S + ROWS / 2);
  if (r < 0 || r >= ROWS || c < 0 || c >= COLS || grid[r][c] === 1) return null;
  return [r, c];
}
let downAt = null;
renderer.domElement.addEventListener('pointerdown', e => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointermove', e => {
  const cell = cellAt(e);
  hover.visible = !!cell;
  if (cell) hover.position.copy(cellPos(cell[0], cell[1], 0.025));
});
renderer.domElement.addEventListener('pointerup', e => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return; // it was a drag
  const cell = cellAt(e);
  if (cell) window.dash.cellClick(cell[0], cell[1]);
});


// ---------------------------------------------------------------- follow a robot
// Camera keeps its angle and zoom but glides along with the robot; drag still orbits around it.
let followId = null, approach = false;
let globalView = null; // 'VIEW: ISO' or 'VIEW: TOP'
const followBtn = document.getElementById('btn-follow');
const FOLLOW_OFFSET = new THREE.Vector3(-4, 5.5, 6.5);

followBtn.onclick = () => {
  const ids = [...fleet.keys()].sort();
  const cycle = ['OFF', 'VIEW: ISO', 'VIEW: TOP', ...ids];
  
  let currentKey = followId || globalView || 'OFF';
  let nextKey = cycle[cycle.indexOf(currentKey) + 1] || 'OFF';
  
  followId = null;
  globalView = null;
  
  if (nextKey === 'OFF') {
      followBtn.textContent = 'CAMERA: FREE';
      followBtn.classList.remove('on');
  } else if (nextKey.startsWith('VIEW:')) {
      globalView = nextKey;
      followBtn.textContent = globalView;
      followBtn.classList.add('on');
  } else {
      followId = nextKey;
      followBtn.textContent = `FOLLOW: ${followId}`;
      followBtn.classList.add('on');
      approach = true;
  }
};

controls.addEventListener('start', () => { 
    approach = false; 
    globalView = null; 
    if (!followId) {
        followBtn.textContent = 'CAMERA: FREE';
        followBtn.classList.remove('on');
    }
});

function updateFollow(dt) {
  if (globalView) {
      // Lerp to the global view
      const targetPos = globalView === 'VIEW: TOP' ? new THREE.Vector3(0.1, 45, 0) : new THREE.Vector3(-18, 22, 26);
      const targetLook = new THREE.Vector3(0, 0, 0);
      
      const k = 1 - Math.exp(-dt * 4);
      camera.position.lerp(targetPos, k);
      controls.target.lerp(targetLook, k);
      return;
  }

  const v = fleet.get(followId);
  if (!v) return;
  const k = 1 - Math.exp(-dt * 5);
  const delta = v.g.position.clone().setY(0.3).sub(controls.target).multiplyScalar(k);
  controls.target.add(delta);
  camera.position.add(delta);
  if (approach) {
    const want = controls.target.clone().add(FOLLOW_OFFSET);
    camera.position.lerp(want, 1 - Math.exp(-dt * 2.5));
    if (camera.position.distanceTo(want) < 0.1) approach = false;
  }
}

// ---------------------------------------------------------------- boot
const wm = await (await fetch('/warehouse')).json();
buildWorld(wm);

const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = Math.min(clock.getDelta(), 0.1), time = clock.elapsedTime;
  if (!host.offsetParent) return; // tab hidden: skip rendering
  syncRobots(dt, time);
  syncPending(time);
  updateFollow(dt);
  controls.update();
  composer.render();
});
