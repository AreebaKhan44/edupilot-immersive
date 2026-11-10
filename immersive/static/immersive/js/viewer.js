import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { VRButton } from 'three/addons/webxr/VRButton.js';
import { Voice } from 'edupilot-voice';      // same file for teacher and student (url + ?v= comes from the importmap in viewer.html)

const CFG = window.EDUPILOT;
const $ = (id) => document.getElementById(id);
const stageEl = $('stage');
const RTL = CFG.locale === 'ur';
const FONT = RTL ? '"Noto Naskh Arabic","Segoe UI",Arial,sans-serif' : '"Segoe UI",Arial,sans-serif';
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
                set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode: ignore */ } } };
let calm = store.get('edupilot.calm', matchMedia('(prefers-reduced-motion: reduce)').matches);   // reduced motion (WCAG 2.3.3)
const billboards = [];

// ---------- renderer / camera / controls ----------
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.xr.enabled = true;
stageEl.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x06101f);
scene.fog = new THREE.Fog(0x06101f, 14, 40);
const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.05, 100);
camera.position.set(0, 1.6, 6.5);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1.4, 0); controls.enableDamping = true; controls.autoRotate = false; controls.autoRotateSpeed = 1.2;
scene.add(new THREE.HemisphereLight(0xcfe4ff, 0x223355, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(4, 8, 5); scene.add(sun);
const rim = new THREE.PointLight(0x7a5bf1, 40, 20); rim.position.set(-5, 3, -3); scene.add(rim);

// stars + floor grid (cheap, comfortable in VR: no forced motion)
{
  const g = new THREE.BufferGeometry(); const n = 700; const p = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) { const r = 18 + Math.random() * 12, a = Math.random() * 6.283, b = Math.acos(2 * Math.random() - 1);
    p[i*3] = r*Math.sin(b)*Math.cos(a); p[i*3+1] = Math.abs(r*Math.cos(b))*0.8 + 0.5; p[i*3+2] = r*Math.sin(b)*Math.sin(a); }
  g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0x9fc2ff, size: 0.06 })));
  const grid = new THREE.GridHelper(30, 30, 0x2b4a86, 0x16294d); grid.position.y = -0.01; scene.add(grid);
}
const stage = new THREE.Group(); scene.add(stage);
const anim = []; // functions(t, dt)
const pickables = [];

// ---------- helpers ----------
const std = (color, o = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.45, metalness: 0.1, ...o });
function label(text, size = 0.5, color = '#ffffff') {
  const c = document.createElement('canvas'); const ctx = c.getContext('2d');
  const fs = 64; ctx.font = `700 ${fs}px "Segoe UI", Arial, sans-serif`;
  const w = Math.ceil(ctx.measureText(text).width) + 40; c.width = w; c.height = fs + 36;
  ctx.font = `700 ${fs}px "Segoe UI", Arial, sans-serif`; ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
  ctx.fillStyle = 'rgba(8,20,45,.72)'; ctx.beginPath(); ctx.roundRect(0, 0, c.width, c.height, 26); ctx.fill();
  ctx.fillStyle = color; ctx.fillText(text, c.width / 2, c.height / 2 + 3);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  spr.scale.set(size * (c.width / c.height), size, 1); spr.renderOrder = 10; return spr;
}
function tag(mesh, name, dy = 0.6, size = 0.34) {
  mesh.userData.name = name; pickables.push(mesh);
  const l = label(name, size); l.position.copy(mesh.position); l.position.y += dy; stage.add(l); return l;
}
function sphere(r, color, pos, o) { const m = new THREE.Mesh(new THREE.SphereGeometry(r, 48, 32), std(color, o)); m.position.set(...pos); stage.add(m); return m; }
function orbitRing(r, color = 0x3d5ea8) { const m = new THREE.Mesh(new THREE.RingGeometry(r - 0.012, r + 0.012, 128), new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity: 0.6 })); m.rotation.x = -Math.PI / 2; m.position.y = 1.4; stage.add(m); return m; }

// ---------- 3D concept diagrams (flow / cycle / map) built from the lesson text of ANY subject ----------
function wrapCanvas(ctx, text, x, y, maxW, lh, maxLines) {
  const words = String(text || '').split(' '); let line = '', n = 0;
  for (const w of words) { const t = line ? line + ' ' + w : w;
    if (ctx.measureText(t).width > maxW && line) { ctx.fillText(line, x, y); y += lh; line = w; if (++n >= maxLines - 1) { line = words.slice(words.indexOf(w)).join(' '); break; } } else line = t; }
  let out = line; while (ctx.measureText(out).width > maxW && out.length > 4) out = out.slice(0, -2); if (out !== line) out += '…';
  ctx.fillText(out, x, y); return y + lh;
}
function nodeCard(n, idx, color, w = 2.1, h = 1.1) {
  const c = document.createElement('canvas'); c.width = 640; c.height = Math.round(640 * h / w); const x = c.getContext('2d');
  x.fillStyle = '#ffffff'; x.beginPath(); x.roundRect(6, 6, c.width - 12, c.height - 12, 36); x.fill();
  x.lineWidth = 10; x.strokeStyle = color; x.stroke();
  x.fillStyle = color; x.beginPath(); x.arc(46, 46, 30, 0, 6.283); x.fill();
  x.fillStyle = '#fff'; x.font = `700 32px ${FONT}`; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(String(idx), 46, 48);
  x.direction = RTL ? 'rtl' : 'ltr'; x.textAlign = 'center'; x.textBaseline = 'top';
  x.fillStyle = '#16213f'; x.font = `700 46px ${FONT}`; let y = wrapCanvas(x, n.label, c.width / 2, 22, c.width - 130, 54, 2) + 4;
  x.fillStyle = '#4a5a80'; x.font = `32px ${FONT}`; wrapCanvas(x, n.detail, c.width / 2, y, c.width - 70, 40, Math.max(1, Math.floor((c.height - y - 24) / 40)));
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, transparent: true, side: THREE.DoubleSide }));
  m.userData.name = n.detail || n.label; billboards.push(m); pickables.push(m); stage.add(m); return m;
}
function marker(path, speed = 0.35) {      // glowing dot that walks along the steps so the order is visible
  const d = sphere(0.12, 0xffe066, [0, 0, 0], { emissive: 0xffcc33, emissiveIntensity: 1.5 });
  anim.push((t) => { const u = ((t * speed) % 1) * (path.length - 1), i = Math.floor(u), f = u - i; d.position.lerpVectors(path[i], path[Math.min(i + 1, path.length - 1)], f); });
}
const DIAGRAM = {
  flow(v) {
    const nodes = v.diagram.nodes, n = nodes.length, per = n > 3 ? 3 : n, col = v.color || '#5579ff', path = [];
    nodes.forEach((nd, i) => { const r = Math.floor(i / per), c = i % per, rowN = Math.min(per, n - r * per);
      const x = (c - (rowN - 1) / 2) * 2.6, y = 2.6 - r * 1.7; const m = nodeCard(nd, i + 1, col); m.position.set(x, y, 0); path.push(new THREE.Vector3(x, y, 0.15));
      if (i < n - 1 && (i + 1) % per) { const a = new THREE.Mesh(new THREE.ConeGeometry(0.13, 0.34, 16), std(0x7fb0ff, { emissive: 0x3a6ad8, emissiveIntensity: .8 })); a.rotation.z = -Math.PI / 2; a.position.set(x + 1.45, y, 0); stage.add(a); } });
    marker(path); camera.position.set(0, 2.6, 8.2); controls.target.set(0, 2.2, 0);
  },
  cycle(v) {
    const nodes = v.diagram.nodes, n = nodes.length, R = 2.5, cy = 2.2, col = v.color || '#5579ff', path = [];
    const ring = new THREE.Mesh(new THREE.TorusGeometry(R, 0.03, 12, 96), new THREE.MeshBasicMaterial({ color: 0x6da0ff, transparent: true, opacity: .55 })); ring.position.y = cy; stage.add(ring);
    nodes.forEach((nd, i) => { const a = Math.PI / 2 - (i / n) * Math.PI * 2, x = Math.cos(a) * R * 1.25, y = cy + Math.sin(a) * R * 0.9;
      const m = nodeCard(nd, i + 1, col, 2.0, 1.05); m.position.set(x, y, 0); path.push(new THREE.Vector3(Math.cos(a) * R, cy + Math.sin(a) * R, 0.1)); });
    path.push(path[0].clone()); marker(path, 0.2);
    const l = label(v.diagram.title || 'Cycle', 0.34); l.position.set(0, cy, 0); stage.add(l); camera.position.set(0, 2.6, 8.6); controls.target.set(0, 2.2, 0);
  },
  map(v) {
    const nodes = v.diagram.nodes, n = nodes.length, cy = 1.9, col = new THREE.Color(v.color || '#5579ff');
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.8, 2), std(col, { flatShading: true, emissive: col, emissiveIntensity: .3 })); core.position.y = cy; stage.add(core);
    const t = label(v.diagram.title || '', 0.36); t.position.set(0, cy + 1.2, 0); stage.add(t); core.userData.name = v.diagram.title; pickables.push(core);
    anim.push((tt) => { core.rotation.y = tt * .4; });
    nodes.forEach((nd, i) => { const a = (i / n) * Math.PI * 2, R = 3.1; const m = nodeCard(nd, i + 1, '#' + col.getHexString()); m.position.set(Math.cos(a) * R, cy + Math.sin(a * 2) * .25, Math.sin(a) * R);
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0, cy, 0), m.position]), new THREE.LineBasicMaterial({ color: 0x6da0ff, transparent: true, opacity: .5 })); stage.add(line); });
    camera.position.set(0, 3.2, 8.4); controls.target.set(0, 1.9, 0);
  },
};
let buildToken = 0;
async function loadModel(url, v, sc) {     // teacher-supplied .glb (roadmap s.7): shown instead of the built-in shape
  const token = ++buildToken;
  try {
    const { GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js');
    new GLTFLoader().load(url, (g) => {
      if (token !== buildToken) return;
      const root = g.scene, box = new THREE.Box3().setFromObject(root), size = box.getSize(new THREE.Vector3()), ctr = box.getCenter(new THREE.Vector3());
      const k = 3.2 / Math.max(size.x, size.y, size.z, 0.001); root.scale.setScalar(k); root.position.set(-ctr.x * k, 1.5 - ctr.y * k, -ctr.z * k);
      root.traverse((o) => { if (o.isMesh) { o.userData.name = o.name || 'Model part'; pickables.push(o); } });
      stage.add(root); camera.position.set(0, 2.4, 7);
      if (g.animations?.length) { const mx = new THREE.AnimationMixer(root); g.animations.forEach((a) => mx.clipAction(a).play()); anim.push((t, dt) => { if (!calm) mx.update(dt); }); }
    }, undefined, () => { if (token === buildToken) BUILD.cluster(v, sc); });
  } catch { BUILD.cluster(v, sc); }
}

function shortLabel(t) { const w = String(t || '').replace(/[.:;,]+$/, '').split(/\s+/); return w.slice(0, 3).join(' ') + (w.length > 3 ? '…' : ''); }
function autoDiagram(v, sc) {
  const pts = ((sc && sc.key_points) || []).filter(Boolean).slice(0, 6); if (pts.length < 2) return null;
  const labs = (v.labels || []).filter(Boolean);
  const nodes = pts.map((p, i) => ({ label: labs[i + 1] && labs.length > pts.length ? labs[i + 1] : shortLabel(p), detail: p }));
  return { ...v, diagram: { kind: 'map', title: (sc && sc.title) || labs[0] || '', nodes } };
}

// ---------- 3D builders (one per visual type) ----------
const BUILD = {
  // Bit & Byte: 8 clickable switches (cubes). Click a cube = flip that bit 0 <-> 1 and watch the number and the letter change.
  bits(v) {
    const ON = 0xffd23f, OFF = 0x1b2a4d, cx = 0, cy = 3.1, gap = 1.1;
    const live = (size, color) => { const spr = label(' ', size, color); stage.add(spr); const api = { spr, set(t) { const n = label(t, size, color); spr.material.map.dispose(); spr.material.map = n.material.map; spr.scale.copy(n.scale); } }; return api; };
    const digitTex = (ch, on) => { const c = document.createElement('canvas'); c.width = c.height = 128; const x = c.getContext('2d');
      x.fillStyle = on ? '#fff4c2' : '#0e1a36'; x.fillRect(0, 0, 128, 128); x.lineWidth = 8; x.strokeStyle = on ? '#ffb300' : '#3d5ea8'; x.strokeRect(4, 4, 120, 120);
      x.fillStyle = on ? '#8a5a00' : '#6f8fd8'; x.font = '700 96px "Segoe UI", Arial'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(ch, 64, 70);
      const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; };
    const title = label('Bit & Byte  ·  click the cubes!', 0.38); title.position.set(cx, cy + 2.1, 0); stage.add(title);
    // 1 byte = 8 bits bracket
    const x0 = -3.5 * gap - 0.5, x1 = 3.5 * gap + 0.5, by = cy + 1.25;
    const bracket = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x0, by - 0.18, 0), new THREE.Vector3(x0, by, 0), new THREE.Vector3(x1, by, 0), new THREE.Vector3(x1, by - 0.18, 0)]), new THREE.LineBasicMaterial({ color: 0x7fb0ff })); stage.add(bracket);
    const bl = label('1 BYTE = 8 BITS', 0.3, '#9fd0ff'); bl.position.set(cx, by + 0.3, 0); stage.add(bl);
    const bin = live(0.36, '#7fe3ff'), dec = live(0.4, '#ffe066'), chr = live(0.34, '#ffffff');
    bin.spr.position.set(cx, 2.2, 0); dec.spr.position.set(cx, 1.65, 0); chr.spr.position.set(cx, 1.15, 0);
    const bitsArr = new Array(8).fill(0), cubes = [];
    const apply = () => {
      const n = bitsArr.reduce((a, b) => a * 2 + b, 0);
      cubes.forEach((c, i) => { const on = bitsArr[i] === 1; const mat = c.material; mat.map?.dispose(); mat.map = digitTex(on ? '1' : '0', on); mat.color.set(0xffffff); mat.emissive.set(on ? ON : 0x000000); mat.emissiveMap = null; mat.emissiveIntensity = on ? 0.55 : 0; mat.needsUpdate = true; c.userData.on = on; });
      bin.set('Binary: ' + bitsArr.join(''));
      dec.set('Decimal: ' + n + '   (' + bitsArr.map((b, i) => (b ? [128, 64, 32, 16, 8, 4, 2, 1][i] : 0)).filter(Boolean).join(' + ') + (n ? '' : '0') + ')');
      chr.set(n >= 32 && n < 127 ? 'Computer reads this byte as the letter  “' + String.fromCharCode(n) + '”' : 'Computer reads this byte as the number ' + n);
    };
    const set = (n) => { for (let i = 0; i < 8; i++) bitsArr[i] = (n >> (7 - i)) & 1; apply(); };
    const vals = [128, 64, 32, 16, 8, 4, 2, 1]; let touched = false;
    for (let i = 0; i < 8; i++) {
      const x = (i - 3.5) * gap;
      const cube = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.9, 0.9), new THREE.MeshStandardMaterial({ roughness: 0.35, metalness: 0.05 }));
      cube.position.set(x, cy, 0); stage.add(cube); cubes.push(cube);
      cube.userData.name = 'Bit ' + (8 - i) + ' (value ' + vals[i] + ') – click to flip 0 ↔ 1';
      cube.userData.onClick = () => { touched = true; bitsArr[i] ^= 1; apply(); };
      pickables.push(cube);
      const pv = label(String(vals[i]), 0.26, '#cfe0ff'); pv.position.set(x, cy + 0.72, 0); stage.add(pv);
      const nm = label('bit ' + (8 - i), 0.18, '#7f98c8'); nm.position.set(x, cy - 0.68, 0); stage.add(nm);
    }
    // self-running demo until the student touches a cube: C, A, T  (67, 65, 84)
    const word = [67, 65, 84]; let last = -1;
    anim.push((t) => { cubes.forEach((c, i) => { c.rotation.y = c.userData.on ? Math.sin(t * 2 + i) * 0.18 : 0; });
      if (touched) return; const k = Math.floor(t / 3) % word.length; if (k !== last) { last = k; set(word[k]); } });
    set(67);
    // the size ladder: bit -> byte -> KB -> MB -> GB
    const ladder = [['1 Bit', '0 or 1', 0.16, 0x7a8bff], ['1 Byte', '8 bits · 1 letter', 0.32, 0x20b7c4], ['1 KB', '1024 bytes', 0.52, 0x11a88b], ['1 MB', '1024 KB · a photo', 0.82, 0xf0aa49], ['1 GB', '1024 MB · a movie', 1.2, 0xe5484d]];
    ladder.forEach(([n, d, h, col], i) => {
      const x = (i - 2) * 1.9, w = 0.55 + i * 0.12;
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, w), std(col)); m.position.set(x, h / 2, 0.3); stage.add(m);
      m.userData.name = n + ' = ' + d; pickables.push(m);
      const l = label(n, 0.26); l.position.set(x, h + 0.32, 0.3); stage.add(l);
      const l2 = label(d, 0.16, '#9fb4e6'); l2.position.set(x, h + 0.08 + 0.58, 0.3); stage.add(l2);
      anim.push((t) => { m.rotation.y = t * 0.4 + i; });
    });
    const arr = label('each step is bigger  ➜', 0.2, '#9fb4e6'); arr.position.set(0, -0.28, 0.3); stage.add(arr);
    camera.position.set(0, 3.0, 11); controls.target.set(0, 2.1, 0);
  },
  solar(v) {
    const cy = 1.4; const s = sphere(0.7, 0xffc933, [0, cy, 0], { emissive: 0xff9900, emissiveIntensity: 1.2 }); tag(s, 'Sun', 1.05);
    const L = new THREE.PointLight(0xffe2a0, 60, 30); L.position.set(0, cy, 0); stage.add(L);
    [['Mercury', 1.3, 0.12, 0xb5a79a, 1.6], ['Venus', 1.8, 0.2, 0xe6b86a, 1.2], ['Earth', 2.4, 0.22, 0x3b82f6, 1.0], ['Mars', 3.0, 0.16, 0xd1603d, 0.8], ['Jupiter', 3.8, 0.45, 0xd9a066, 0.5], ['Saturn', 4.6, 0.38, 0xe3cf9a, 0.4]]
      .forEach(([n, r, size, col, sp], i) => {
        orbitRing(r); const p = sphere(size, col, [r, cy, 0]); const l = tag(p, n, size + 0.3, 0.26); const a0 = i * 1.1;
        if (n === 'Saturn') { const rg = new THREE.Mesh(new THREE.RingGeometry(size * 1.4, size * 2, 64), new THREE.MeshBasicMaterial({ color: 0xcdbb8b, side: THREE.DoubleSide, transparent: true, opacity: .8 })); rg.rotation.x = 1.2; p.add(rg); }
        anim.push((t) => { const a = a0 + t * sp * 0.3; p.position.set(Math.cos(a) * r, cy, Math.sin(a) * r); l.position.set(p.position.x, cy + size + 0.3, p.position.z); p.rotation.y = t; });
      });
    camera.position.set(0, 5.5, 8.5);
  },
  cell(v) {
    const cy = 1.5; const mem = new THREE.Mesh(new THREE.SphereGeometry(2.1, 64, 48), new THREE.MeshPhysicalMaterial({ color: 0x11a88b, transparent: true, opacity: 0.22, roughness: 0.2, side: THREE.DoubleSide }));
    mem.position.y = cy; stage.add(mem); mem.userData.name = 'Cell membrane'; pickables.push(mem);
    const nuc = sphere(0.7, 0x7a5bf1, [-0.2, cy, 0]); tag(nuc, 'Nucleus', 1.0);
    const nucleolus = sphere(0.25, 0x3b2a8a, [-0.1, cy + 0.1, 0.45]);
    [[1.1, 0.5, 0.6], [-1.0, -0.4, 0.8], [0.8, -0.6, -0.9]].forEach((p, i) => {
      const m = new THREE.Mesh(new THREE.CapsuleGeometry(0.17, 0.4, 8, 16), std(0xf0aa49)); m.position.set(p[0], cy + p[1], p[2]); m.rotation.z = 1 + i; stage.add(m);
      if (i === 0) tag(m, 'Mitochondria', 0.55, 0.26); else { m.userData.name = 'Mitochondria'; pickables.push(m); }
      anim.push((t) => { m.rotation.y = t * 0.6; m.position.y = cy + p[1] + Math.sin(t + i) * 0.06; });
    });
    for (let i = 0; i < 26; i++) { const d = sphere(0.045, 0xffffff, [(Math.random() - .5) * 2.6, cy + (Math.random() - .5) * 2.6, (Math.random() - .5) * 2.6]); if (d.position.length() > 1.9) d.position.setLength(1.6); if (i === 0) tag(d, 'Ribosomes', 0.3, 0.22); }
    const er = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.07, 12, 48), std(0xff7aa8)); er.position.set(0.2, cy - 1.1, 0.3); er.rotation.x = 1.2; stage.add(er); tag(er, 'Endoplasmic reticulum', 0.6, 0.24);
    anim.push((t) => { mem.rotation.y = t * 0.05; }); camera.position.set(0, 2.4, 8.6);
  },
  atom(v) {
    const cy = 1.5; const g = new THREE.Group(); g.position.y = cy; stage.add(g);
    for (let i = 0; i < 6; i++) { const m = new THREE.Mesh(new THREE.SphereGeometry(0.26, 32, 24), std(i % 2 ? 0xe5484d : 0x7a8bff)); m.position.set((Math.random() - .5) * 0.45, (Math.random() - .5) * 0.45, (Math.random() - .5) * 0.45); g.add(m); if (i < 2) { m.userData.name = i ? 'Proton (+)' : 'Neutron'; pickables.push(m); } }
    tag(g.children[0], 'Neutron', 0.9, 0.28);
    const es = [];
    [[0, 0], [Math.PI / 3, 0.0], [-Math.PI / 3, 0]].forEach(([rx, rz], i) => {
      const o = new THREE.Mesh(new THREE.TorusGeometry(2.0, 0.015, 8, 128), new THREE.MeshBasicMaterial({ color: 0x6da0ff })); o.rotation.set(Math.PI / 2 + rx, rz, 0); o.scale.y = 0.7; g.add(o);
      const e = new THREE.Mesh(new THREE.SphereGeometry(0.11, 24, 16), std(0x7fe3ff, { emissive: 0x2fb6ff, emissiveIntensity: 1 })); e.userData.name = 'Electron (−)'; pickables.push(e); g.add(e); es.push([e, i, o]);
    });
    anim.push((t) => es.forEach(([e, i, o]) => { const a = t * (1.2 + i * 0.3) + i * 2; const p = new THREE.Vector3(Math.cos(a) * 2.0, 0, Math.sin(a) * 2.0 * 0.7); p.applyEuler(o.rotation); e.position.copy(p); }));
    const l = label('Electrons orbit the nucleus', 0.3); l.position.set(0, cy + 2.6, 0); stage.add(l); camera.position.set(0, 2, 7);
  },
  circuit(v) {
    const cy = 1.4, w = 3.2, h = 1.8; const wire = std(0xdddddd, { metalness: 0.7, roughness: 0.3 });
    const seg = (x, y, sx, sy) => { const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, 0.1), wire); m.position.set(x, cy + y, 0); stage.add(m); };
    seg(0, h / 2, w, 0.08); seg(0, -h / 2, w, 0.08); seg(-w / 2, 0, 0.08, h); seg(w / 2, 0, 0.08, h);
    const bat = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.9, 32), std(0x315bde)); bat.position.set(-w / 2, cy, 0); stage.add(bat); tag(bat, 'Battery (voltage source)', 0.9, 0.26);
    const bulb = sphere(0.35, 0xffe066, [0, cy + h / 2, 0], { emissive: 0xffcc33, emissiveIntensity: 1.4 }); tag(bulb, 'Bulb (load)', 0.7, 0.26);
    const res = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.22, 0.22), std(0xf0aa49)); res.position.set(0, cy - h / 2, 0); stage.add(res); tag(res, 'Resistor', 0.5, 0.26);
    const sw = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.1, 0.1), std(0x11a88b)); sw.position.set(w / 2, cy, 0); stage.add(sw); tag(sw, 'Click = switch ON/OFF', 0.6, 0.22);
    let on = true; sw.userData.onClick = () => { on = !on; sw.rotation.z = on ? 0 : 0.9; bulb.material.emissiveIntensity = on ? 1.4 : 0.05; };
    const dots = []; for (let i = 0; i < 24; i++) { const d = new THREE.Mesh(new THREE.SphereGeometry(0.06, 12, 8), new THREE.MeshBasicMaterial({ color: 0x7fe3ff })); stage.add(d); dots.push(d); }
    const P = 2 * (w + h);
    anim.push((t) => dots.forEach((d, i) => { d.visible = on; let s = ((i / dots.length) * P + t * 1.2) % P, x, y;
      if (s < w) { x = -w / 2 + s; y = h / 2; } else if (s < w + h) { x = w / 2; y = h / 2 - (s - w); } else if (s < 2 * w + h) { x = w / 2 - (s - w - h); y = -h / 2; } else { x = -w / 2; y = -h / 2 + (s - 2 * w - h); } d.position.set(x, cy + y, 0.12); }));
    camera.position.set(0, 2.4, 7.8);
  },
  dna(v) {
    const cy = 1.5, N = 36; const g = new THREE.Group(); g.position.y = cy - 1.6; stage.add(g);
    for (let i = 0; i < N; i++) { const t = i / (N - 1), y = t * 3.4, a = t * Math.PI * 5, x = Math.cos(a) * 0.7, z = Math.sin(a) * 0.7;
      const s1 = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), std(0xff7aa8)); s1.position.set(x, y, z);
      const s2 = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), std(0x7ac8ff)); s2.position.set(-x, y, -z); g.add(s1, s2);
      const rung = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 1.4, 8), std(0xffffff, { transparent: true, opacity: .55 })); rung.position.set(0, y, 0); rung.rotation.z = Math.PI / 2; rung.rotation.y = -a; g.add(rung); if (i === 8) { s1.userData.name = 'Strand (sugar-phosphate)'; pickables.push(s1); } if (i === 12) { rung.userData.name = 'Base pair'; pickables.push(rung); } }
    anim.push((t) => { g.rotation.y = t * 0.5; }); const l = label('DNA double helix', 0.34); l.position.set(0, cy + 2.4, 0); stage.add(l); camera.position.set(0, 2, 6);
  },
  geometry(v) {
    const cy = 1.4; const defs = [['Cube', new THREE.BoxGeometry(1.2, 1.2, 1.2), 0x20b7c4, -2.6], ['Sphere', new THREE.SphereGeometry(0.75, 40, 30), 0x7a5bf1, -0.9], ['Cone', new THREE.ConeGeometry(0.75, 1.5, 40), 0xf0aa49, 0.9], ['Cylinder', new THREE.CylinderGeometry(0.6, 0.6, 1.4, 40), 0xe5484d, 2.6]];
    defs.forEach(([n, geo, col, x], i) => { const m = new THREE.Mesh(geo, std(col)); m.position.set(x, cy, 0); stage.add(m); tag(m, n, 1.1, 0.3); anim.push((t) => { m.rotation.y = t * 0.6 + i; m.rotation.x = 0.3; }); const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: .5 })); m.add(e); });
    camera.position.set(0, 2.4, 6.5);
  },
  cluster(v, sc) {
    if (v.diagram && v.diagram.nodes && v.diagram.nodes.length >= 2 && DIAGRAM[v.diagram.kind]) return DIAGRAM[v.diagram.kind](v);
    const auto = autoDiagram(v, sc);        // no diagram stored for this scene: build the same card-style scene from the key points
    if (auto) return DIAGRAM[auto.diagram.kind](auto);
    const cy = 1.5; const col = new THREE.Color(v.color || '#5579ff'); const labels = v.labels && v.labels.length ? v.labels : ['Concept', 'Idea', 'Example'];
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.9, 2), std(col, { flatShading: true, emissive: col, emissiveIntensity: 0.25 })); core.position.y = cy; stage.add(core); tag(core, labels[0], 1.25, 0.34);
    anim.push((t) => { core.rotation.y = t * 0.4; core.rotation.x = t * 0.2; });
    labels.slice(1).forEach((n, i, arr) => { const R = 2.3, a0 = (i / arr.length) * Math.PI * 2; const m = new THREE.Mesh(new THREE.SphereGeometry(0.38, 32, 24), std(col.clone().offsetHSL(0.07 * i, 0, 0.12))); stage.add(m); const l = tag(m, n, 0.65, 0.26);
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), new THREE.LineBasicMaterial({ color: 0x6da0ff, transparent: true, opacity: .45 })); stage.add(line);
      anim.push((t) => { const a = a0 + t * 0.25; m.position.set(Math.cos(a) * R, cy + Math.sin(a * 2) * 0.4, Math.sin(a) * R); l.position.set(m.position.x, m.position.y + 0.65, m.position.z); line.geometry.setFromPoints([new THREE.Vector3(0, cy, 0), m.position]); }); });
    camera.position.set(0, 2.4, 7);
  },
};

// ---------- floating in-world info panel (visible inside VR headsets too) ----------
let panel = null;
function makePanel(title, points, right) {
  if (panel) { scene.remove(panel); panel.material.map.dispose(); panel = null; }
  const c = document.createElement('canvas'); c.width = 1024; c.height = 512; const x = c.getContext('2d');
  x.fillStyle = 'rgba(9,27,54,.85)'; x.beginPath(); x.roundRect(0, 0, 1024, 512, 36); x.fill();
  x.strokeStyle = 'rgba(127,176,255,.6)'; x.lineWidth = 4; x.stroke();
  x.fillStyle = '#fff'; x.textBaseline = 'top'; x.direction = CFG.locale === 'ur' ? 'rtl' : 'ltr'; x.textAlign = CFG.locale === 'ur' ? 'right' : 'left';
  const X = CFG.locale === 'ur' ? 984 : 40;
  x.font = '700 46px "Segoe UI", Arial'; wrapText(x, title, X, 34, 940, 54, 2);
  x.font = '30px "Segoe UI", Arial'; x.fillStyle = '#cfe0ff'; let y = 170;
  for (const p of points.slice(0, 3)) { y = wrapText(x, '• ' + p, X, y, 940, 38, 3) + 14; }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  panel = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 1.6), new THREE.MeshBasicMaterial({ map: tex, transparent: true }));
  panel.position.set(-3.8, 2.4, -1.5); panel.rotation.y = 0.5; scene.add(panel);
}
function wrapText(ctx, text, x, y, maxW, lh, maxLines) {
  const words = text.split(' '); let line = '', n = 0;
  for (const w of words) { const t = line ? line + ' ' + w : w; if (ctx.measureText(t).width > maxW && line) { ctx.fillText(line, x, y); y += lh; line = w; if (++n >= maxLines) return y; } else line = t; }
  ctx.fillText(line, x, y); return y + lh;
}

// ---------- picture board: the picture from the book (or the one drawn from the lesson text) floats next to the 3D scene ----------
let board = null, boardImgs = [], boardIdx = 0, boardPic = null, boardCap = null;
const texLoader = new THREE.TextureLoader();
function disposeBoard() { if (!board) return; scene.remove(board); board.traverse((o) => { o.material?.map?.dispose(); o.material?.dispose?.(); o.geometry?.dispose?.(); }); board = boardPic = boardCap = null; }
function makeBoard(images, skip3d) {
  disposeBoard(); boardImgs = images || []; boardIdx = 0; renderThumbs();
  if (!boardImgs.length || skip3d) return;      // a drawn picture that only repeats the 3D diagram stays a thumbnail (click = enlarge)
  board = new THREE.Group(); board.position.set(4.0, 2.7, -0.3); board.rotation.y = -0.38; board.scale.setScalar(1.05); scene.add(board);
  board.add(new THREE.Mesh(new THREE.PlaneGeometry(3.8, 2.4), new THREE.MeshBasicMaterial({ color: 0xffffff })));
  boardPic = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 2.2), new THREE.MeshBasicMaterial({ color: 0xdfe8fb })); boardPic.position.z = 0.01;
  boardPic.userData.name = 'Picture - click to enlarge'; boardPic.userData.onClick = () => openLightbox(); board.add(boardPic); pickables.push(boardPic);
  showPicture(0);
}
function showPicture(i) {
  if (!boardImgs.length) return;
  if (!boardPic) { boardIdx = (i + boardImgs.length) % boardImgs.length; renderThumbs(); return; }
  boardIdx = (i + boardImgs.length) % boardImgs.length; const im = boardImgs[boardIdx];
  texLoader.load(im.url, (tex) => {
    if (!boardPic || boardImgs[boardIdx] !== im) { tex.dispose(); return; }
    tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8; boardPic.material.map = tex; boardPic.material.color.set(0xffffff); boardPic.material.needsUpdate = true;
    const a = tex.image.width / tex.image.height; let w = 3.6, h = w / a; if (h > 2.2) { h = 2.2; w = h * a; } boardPic.scale.set(w / 3.6, h / 2.2, 1);
  });
  if (boardCap) { board.remove(boardCap); boardCap.material.map.dispose(); }
  const src = im.kind === 'book' ? `📖 From your book${im.page ? ' · p.' + im.page : ''}` : im.kind === 'upload' ? '🖼️ Added by teacher' : '✨ Drawn from the lesson';
  boardCap = label(src + (im.caption ? ' — ' + im.caption : ''), 0.2); boardCap.position.set(0, -1.45, 0.02); board.add(boardCap);
  renderThumbs();
}
function renderThumbs() {
  const el = $('pics'); if (!el) return; el.innerHTML = '';
  boardImgs.forEach((im, k) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'pthumb' + (k === boardIdx ? ' on' : '');
    b.title = im.caption || 'Picture ' + (k + 1); b.setAttribute('aria-label', 'Show picture ' + (k + 1) + (im.caption ? ': ' + im.caption : ''));
    const i = document.createElement('img'); i.src = im.url; i.alt = im.caption || ''; b.appendChild(i); b.onclick = () => { showPicture(k); if (!board) openLightbox(); }; el.appendChild(b); });
}
function openLightbox() {
  if (!boardImgs.length) return; const im = boardImgs[boardIdx];
  $('lbimg').src = im.url; $('lbimg').alt = im.caption || ''; $('lbcap').textContent = im.caption || ''; $('lightbox').style.display = 'flex'; $('lbclose').focus();
}
function closeLightbox() { $('lightbox').style.display = 'none'; }

// ---------- lesson state ----------
let M = null, idx = 0, tourOn = false, speaking = false, timer = null, unlocked = false;   // speaking = the student pressed a voice button for THIS scene (never true by itself)
const voice = new Voice({ locale: CFG.locale });
const LANG = voice.lang;

function clearStage() {
  while (stage.children.length) { const o = stage.children[0]; stage.remove(o); o.traverse?.((c) => { c.geometry?.dispose(); if (c.material) { c.material.map?.dispose(); c.material.dispose?.(); } }); }
  anim.length = 0; pickables.length = 0; billboards.length = 0;
}
function show(i) {
  if (!M) return; idx = (i + M.scenes.length) % M.scenes.length; const s = M.scenes[idx];
  stopSpeech(); clearStage();
  if (!tourOn) speaking = false;           // Next / Prev / arrow keys NEVER start the voice: only the Voice, Repeat or Space controls do
  billboards.length = 0; buildToken++;
  controls.target.set(0, 1.4, 0);
  if (s.model) loadModel(s.model, s.visual || {}, s); else (BUILD[s.visual?.type] || BUILD.cluster)(s.visual || {}, s);
  const isDiagram = !s.model && (BUILD[s.visual?.type] ? s.visual.type === 'cluster' : true) && !!(s.visual?.diagram?.nodes?.length >= 2 || (s.key_points || []).length >= 2);
  stage.position.x = (isDiagram || s.visual?.type === 'bits') && innerWidth > 900 ? 1.3 : 0;        // keep the diagram clear of the left panel
  makeBoard(s.images || [], (isDiagram || s.visual?.type === 'bits') && (s.images || []).every((i) => i.kind === 'generated'));
  makePanel(s.title, s.key_points || [], boardImgs.length > 0);
  $('picinfo').textContent = boardImgs.length ? '' : 'No picture for this scene.';
  $('counter').textContent = `${M.title} · Scene ${idx + 1}/${M.scenes.length}`;
  $('stitle').textContent = s.title; $('narr').textContent = s.narration;
  $('points').innerHTML = ''; (s.key_points || []).forEach((p) => { const li = document.createElement('li'); li.textContent = p; $('points').appendChild(li); });
  $('dots').innerHTML = M.scenes.map((_, k) => `<i class="${k <= idx ? 'on' : ''}"></i>`).join('');
  track('vr.scene.viewed', { scene_id: s.id });
  if (tourOn) { if (speaking) speakScene(s); else schedule(Math.max(8000, (s.narration || '').split(' ').length * 420)); }   // the tour only talks if the student switched the voice on
}

// ---------- voice ----------
function say(msg) { const el = $('vmsg'); if (el) el.textContent = msg || ''; }
function speakScene(s) {
  const words = (s.narration || '').split(' ').length;
  voice.speak(s.narration, {
    audioUrl: s.audio,
    onend: () => { if (tourOn) schedule(900); },
    onfail: () => { if (tourOn) schedule(Math.max(7000, words * 420)); },       // voice.onstatus already told the reason
  });
}
function speakKeyPoints() {
  const s = M.scenes[idx]; const text = (s.key_points || []).join('. ');
  if (!text) return say('No key points in this scene.');
  voice.speak(text, { onfail: () => say('⚠️ Voice could not play.') });
}
function stopSpeech() { voice.cancel(); clearTimeout(timer); }
function schedule(ms) { clearTimeout(timer); timer = setTimeout(() => { if (tourOn) { if (idx + 1 >= M.scenes.length) { tourOn = false; $('tour').textContent = '▶ Auto tour'; track('vr.lesson.completed', {}); } else show(idx + 1); } }, ms); }
function refreshVoiceButtons() {
  $('speak').textContent = speaking ? '🔇 Stop voice' : '🔊 Voice';
  $('pause').textContent = voice.paused ? '▶ Resume' : '⏸ Pause';
  $('pause').disabled = !voice.speaking;
}
voice.onchange = () => { refreshVoiceButtons(); if (voice.speaking) $('vhint').style.display = 'none'; };
voice.onstatus = (m) => say(m);

// The voice starts ONLY when the student presses 🔊 Voice / 🔁 Repeat / the green hint button (or says "play"). Moving between scenes is silent.
$('vhint').onclick = () => { unlocked = true; speaking = true; $('vhint').style.display = 'none'; if (M) speakScene(M.scenes[idx]); refreshVoiceButtons(); };

$('prev').onclick = () => show(idx - 1); $('next').onclick = () => show(idx + 1);
$('tour').onclick = () => { tourOn = !tourOn; $('tour').textContent = tourOn ? '⏸ Stop tour' : '▶ Auto tour'; if (tourOn) show(idx); else { speaking = false; stopSpeech(); } refreshVoiceButtons(); };   // tour moves scenes; voice only if 🔊 Voice was pressed
$('speak').onclick = () => { unlocked = true; if (speaking || voice.speaking) { speaking = false; stopSpeech(); } else { speaking = true; speakScene(M.scenes[idx]); } refreshVoiceButtons(); };
$('pause').onclick = () => voice.togglePause();
$('repeat').onclick = () => { unlocked = true; speaking = true; speakScene(M.scenes[idx]); refreshVoiceButtons(); };
$('spin').onclick = () => { controls.autoRotate = !controls.autoRotate; };
addEventListener('keydown', (e) => { if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return; if (e.key === 'Escape') closeLightbox(); if (e.key === 'p' || e.key === 'P') showPicture(boardIdx + 1); if (e.key === 'ArrowRight') show(idx + 1); if (e.key === 'ArrowLeft') show(idx - 1); if (e.key === ' ') { e.preventDefault(); if (voice.speaking) voice.togglePause(); else { speaking = true; unlocked = true; speakScene(M.scenes[idx]); refreshVoiceButtons(); } } });

// voice settings panel (voice, speed, source)
function fillVoices() {
  const sel = $('vsel'); if (!sel) return; const list = voice.voices(); const cur = voice.pickVoice();
  sel.innerHTML = list.length ? list.map((v) => `<option value="${v.voiceURI}" ${cur && cur.voiceURI === v.voiceURI ? 'selected' : ''}>${v.name} (${v.lang})</option>`).join('') : '<option value="">No browser voice for this language</option>';
  $('vengine').textContent = list.length ? '' : 'This device has no ' + LANG + ' voice, so the server voice is used automatically.';
}
voice.onVoicesChanged(fillVoices); fillVoices();
$('vsel').onchange = (e) => voice.setVoice(e.target.value);
$('vrate').value = voice.rate; $('vratev').textContent = voice.rate.toFixed(2) + '×';
$('vrate').oninput = (e) => { voice.setRate(e.target.value); $('vratev').textContent = voice.rate.toFixed(2) + '×'; };
$('vsrc').value = voice.source; $('vsrc').onchange = (e) => voice.setSource(e.target.value);
$('vtest').onclick = () => { unlocked = true; voice.speak(voice.source === 'server' && M ? M.scenes[idx].narration : (M ? M.scenes[idx].title : 'Hello'), { audioUrl: voice.source === 'server' && M ? M.scenes[idx].audio : '' }); };

// ---------- voice commands (microphone) ----------
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const CMD = {
  stop: ['stop', 'pause', 'quiet', 'ruko', 'ruk jao', 'band', 'رکو', 'رک جاؤ', 'بند', 'रुको', 'बंद'],
  mute: ['mute', 'silent', 'khamosh', 'خاموش', 'चुप'],
  tour: ['tour', 'auto tour', 'ٹور', 'टूर'],
  points: ['key point', 'points', 'nukte', 'نکات', 'نکتے', 'अहम'],
  repeat: ['repeat', 'again', 'replay', 'dobara', 'phir se', 'دوبارہ', 'پھر سے', 'दोबारा', 'फिर से'],
  next: ['next', 'forward', 'continue', 'agla', 'agli', 'aage', 'آگے', 'اگلا', 'اگلی', 'अगला', 'आगे'],
  prev: ['previous', 'back', 'pichla', 'pichli', 'peeche', 'پچھلا', 'پچھلی', 'پیچھے', 'पिछला', 'पीछे'],
  play: ['play', 'resume', 'start', 'read', 'shuru', 'sunao', 'chalao', 'شروع', 'سناؤ', 'چلاؤ', 'सुनाओ', 'शुरू'],
};
const has = (t, list) => list.some((w) => t.includes(w));
function handleCommand(raw) {
  const t = raw.toLowerCase().trim(); if (!t) return;
  const interrupt = has(t, CMD.stop) || has(t, CMD.mute);
  if (voice.speaking && !voice.paused && !interrupt) return;           // do not react to our own narration
  let name = null;
  if (has(t, CMD.stop)) { name = 'stop'; voice.pause(); if (!voice.speaking) stopSpeech(); }
  else if (has(t, CMD.mute)) { name = 'mute'; speaking = false; stopSpeech(); }
  else if (has(t, CMD.tour)) { name = 'tour'; if (!tourOn) $('tour').click(); }
  else if (has(t, CMD.points)) { name = 'key points'; unlocked = true; speakKeyPoints(); }
  else if (has(t, CMD.repeat)) { name = 'repeat'; $('repeat').click(); }
  else if (has(t, CMD.next)) { name = 'next'; show(idx + 1); }
  else if (has(t, CMD.prev)) { name = 'previous'; show(idx - 1); }
  else if (has(t, CMD.play)) { name = 'play'; unlocked = true; speaking = true; voice.paused ? voice.resume() : speakScene(M.scenes[idx]); }
  say(name ? `🎤 “${raw.trim()}” → ${name}` : `🎤 Heard “${raw.trim()}” – try: next, previous, repeat, key points, stop, tour`);
  if (name) track('vr.voice.command', { command: name });
  refreshVoiceButtons();
}
let rec = null, listening = false;
function setMic(on) { listening = on; $('mic').textContent = on ? '🎙️ Listening… (tap to stop)' : '🎤 Voice commands'; $('mic').classList.toggle('primary', on); }
$('mic').onclick = () => {
  unlocked = true;
  if (!SR) return say('🎤 Voice commands need Chrome / Edge (Web Speech recognition). Buttons and arrow keys work everywhere.');
  if (listening) { setMic(false); rec.stop(); return; }
  rec = new SR(); rec.lang = LANG; rec.continuous = true; rec.interimResults = false;
  rec.onresult = (e) => { for (let i = e.resultIndex; i < e.results.length; i++) if (e.results[i].isFinal) handleCommand(e.results[i][0].transcript); };
  rec.onerror = (e) => { if (e.error === 'not-allowed' || e.error === 'service-not-allowed') { setMic(false); say('🎤 Microphone permission was denied.'); } };
  rec.onend = () => { if (listening) { try { rec.start(); } catch { setMic(false); } } };
  try { rec.start(); setMic(true); say('🎤 Say: next · previous · repeat · key points · stop · tour (Tip: use headphones)'); } catch { say('🎤 Could not start the microphone.'); }
};
if (!SR) $('mic').title = 'Not supported in this browser (use Chrome or Edge)';

// ---------- picking ----------
const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(); const tip = $('tip');
renderer.domElement.addEventListener('pointermove', (e) => {
  mouse.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(mouse, camera);
  const h = ray.intersectObjects(pickables, false)[0]; if (h?.object.userData.name) { tip.style.display = 'block'; tip.style.left = e.clientX + 12 + 'px'; tip.style.top = e.clientY + 12 + 'px'; tip.textContent = h.object.userData.name; } else tip.style.display = 'none';
});
renderer.domElement.addEventListener('click', (e) => {
  mouse.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1); ray.setFromCamera(mouse, camera);
  const h = ray.intersectObjects(pickables, false)[0]; if (!h) return; const o = h.object;
  o.userData.onClick?.(); const old = o.scale.clone(); o.scale.multiplyScalar(1.25); setTimeout(() => o.scale.copy(old), 250);
  if (o.userData.name && speaking) voice.speak(o.userData.name);
  track('vr.object.selected', { name: o.userData.name });
});

// ---------- telemetry (batched, de-duplicated server side; only learning events, no motion tracking) ----------
const queue = store.get('edupilot.q', []); const saveQ = () => store.set('edupilot.q', queue.slice(-500)); const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
function track(type, evidence) {
  if (!M) return; queue.push({ event_id: crypto.randomUUID?.() || String(Math.random()).slice(2) + Date.now(), event_type: type, schema_version: 1,
    lesson_db_id: CFG.lessonId, lesson_id: M.lesson_id, lesson_version: M.version, evidence, occurred_at: new Date().toISOString() });
  saveQ(); if (queue.length >= 10) flush();
}
async function flush() { if (!queue.length) return; const batch = queue.splice(0, 100);
  try { const r = await fetch(CFG.eventsUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify({ events: batch }), keepalive: true });
    if (!r.ok) throw new Error('rejected'); saveQ(); } catch { queue.unshift(...batch); saveQ(); } }   // offline: events stay in localStorage, unique ids let the server drop duplicates
addEventListener('online', flush);
setInterval(flush, 8000); addEventListener('pagehide', flush);

// ---------- boot ----------
const vrBtn = VRButton.createButton(renderer);
document.body.appendChild(vrBtn);
vrBtn.id = 'VRButton';
addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); });
const clock = new THREE.Clock();
renderer.setAnimationLoop(() => { const dt = clock.getDelta(), t = calm ? 0 : clock.elapsedTime; anim.forEach((f) => f(t, dt)); billboards.forEach((b) => b.quaternion.copy(camera.quaternion)); controls.update(); renderer.render(scene, camera); });
// ---------- plan panel, accessibility, offline ----------
function fillPlan() {
  const el = $('planbox'); if (!el || !M.plan) return; const ph = M.plan.phases || [];
  el.innerHTML = ph.map((p) => `<div class="ph"><b>${p.phase}</b> <span>${p.minutes} min</span><div>${p.activity}</div></div>`).join('') || '<div class="small">No plan phases.</div>';
  if (M.plan.success_criteria) el.insertAdjacentHTML('afterbegin', `<div class="ph"><b>Success criteria</b><div></div></div>`.replace('<div></div>', '<div>' + M.plan.success_criteria + '</div>'));
}
const root = document.documentElement;
function applyA11y() { root.style.setProperty('--hudfs', String(store.get('edupilot.fs', 1))); document.body.classList.toggle('hc', !!store.get('edupilot.hc', false));
  $('narr').style.display = store.get('edupilot.cap', true) ? '' : 'none'; $('calm').checked = calm; $('cap').checked = store.get('edupilot.cap', true); $('hc').checked = store.get('edupilot.hc', false); $('fs').value = store.get('edupilot.fs', 1); }
$('fs').oninput = (e) => { store.set('edupilot.fs', +e.target.value); applyA11y(); };
$('cap').onchange = (e) => { store.set('edupilot.cap', e.target.checked); applyA11y(); };
$('hc').onchange = (e) => { store.set('edupilot.hc', e.target.checked); applyA11y(); };
$('calm').onchange = (e) => { calm = e.target.checked; store.set('edupilot.calm', calm); };
applyA11y();
$('lbclose').onclick = closeLightbox; $('lightbox').onclick = (e) => { if (e.target.id === 'lightbox') closeLightbox(); };
$('lbprev').onclick = () => { showPicture(boardIdx - 1); openLightbox(); }; $('lbnext').onclick = () => { showPicture(boardIdx + 1); openLightbox(); };
$('offline').onclick = async () => {
  if (!('serviceWorker' in navigator) || !('caches' in window)) return say('⚠️ This browser cannot save lessons for offline use.');
  try { await navigator.serviceWorker.register('/sw.js'); const pack = await (await fetch(CFG.packUrl)).json(); const cache = await caches.open(pack.cache); let ok = 0;
    for (const u of pack.urls) { try { await cache.add(u); ok++; } catch { /* optional file */ } }
    say(`✅ Saved for offline: ${ok}/${pack.urls.length} files (version ${pack.version}). Quiz and results still need a connection.`); } catch { say('⚠️ Could not save for offline use.'); } };
fetch(CFG.manifestUrl).then((r) => r.json()).then((m) => { M = m; refreshVoiceButtons(); fillPlan(); show(0); }).catch(() => { $('stitle').textContent = 'Could not load lesson'; });
