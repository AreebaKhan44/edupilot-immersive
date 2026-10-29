import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { VRButton } from 'three/addons/webxr/VRButton.js';

const CFG = window.EDUPILOT;
const $ = (id) => document.getElementById(id);
const stageEl = $('stage');

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

// ---------- 3D builders (one per visual type) ----------
const BUILD = {
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
  cluster(v) {
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
function makePanel(title, points) {
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
  panel.position.set(-3.6, 2.4, -1.5); panel.rotation.y = 0.5; scene.add(panel);
}
function wrapText(ctx, text, x, y, maxW, lh, maxLines) {
  const words = text.split(' '); let line = '', n = 0;
  for (const w of words) { const t = line ? line + ' ' + w : w; if (ctx.measureText(t).width > maxW && line) { ctx.fillText(line, x, y); y += lh; line = w; if (++n >= maxLines) return y; } else line = t; }
  ctx.fillText(line, x, y); return y + lh;
}

// ---------- lesson state ----------
let M = null, idx = 0, tourOn = false, speaking = false, timer = null;
const synth = window.speechSynthesis;
const LANG = { en: 'en-US', ur: 'ur-PK', hi: 'hi-IN' }[CFG.locale] || 'en-US';

function clearStage() {
  while (stage.children.length) { const o = stage.children[0]; stage.remove(o); o.traverse?.((c) => { c.geometry?.dispose(); if (c.material) { c.material.map?.dispose(); c.material.dispose?.(); } }); }
  anim.length = 0; pickables.length = 0;
}
function show(i) {
  if (!M) return; idx = (i + M.scenes.length) % M.scenes.length; const s = M.scenes[idx];
  stopSpeech(); clearStage();
  (BUILD[s.visual?.type] || BUILD.cluster)(s.visual || {});
  controls.target.set(0, 1.4, 0);
  makePanel(s.title, s.key_points || []);
  $('counter').textContent = `${M.title} · Scene ${idx + 1}/${M.scenes.length}`;
  $('stitle').textContent = s.title; $('narr').textContent = s.narration;
  $('points').innerHTML = ''; (s.key_points || []).forEach((p) => { const li = document.createElement('li'); li.textContent = p; $('points').appendChild(li); });
  $('dots').innerHTML = M.scenes.map((_, k) => `<i class="${k <= idx ? 'on' : ''}"></i>`).join('');
  track('vr.scene.viewed', { scene_id: s.id });
  if (speaking || tourOn) speak(s.narration);
  else if (tourOn) schedule(8000);
}
function speak(text) {
  if (!synth) { if (tourOn) schedule(Math.max(7000, text.split(' ').length * 420)); return; }
  synth.cancel(); const u = new SpeechSynthesisUtterance(text); u.lang = LANG; u.rate = 0.95;
  u.onend = () => { if (tourOn) schedule(900); }; u.onerror = () => { if (tourOn) schedule(3000); }; synth.speak(u);
}
function stopSpeech() { synth?.cancel(); clearTimeout(timer); }
function schedule(ms) { clearTimeout(timer); timer = setTimeout(() => { if (tourOn) { if (idx + 1 >= M.scenes.length) { tourOn = false; $('tour').textContent = '▶ Auto tour'; track('vr.lesson.completed', {}); } else show(idx + 1); } }, ms); }

$('prev').onclick = () => show(idx - 1); $('next').onclick = () => show(idx + 1);
$('tour').onclick = () => { tourOn = !tourOn; $('tour').textContent = tourOn ? '⏸ Stop tour' : '▶ Auto tour'; if (tourOn) { speaking = true; show(idx); } else stopSpeech(); };
$('speak').onclick = () => { speaking = !speaking; $('speak').textContent = speaking ? '🔇 Mute' : '🔊 Narrate'; if (speaking) speak(M.scenes[idx].narration); else stopSpeech(); };
$('spin').onclick = () => { controls.autoRotate = !controls.autoRotate; };
addEventListener('keydown', (e) => { if (e.key === 'ArrowRight') show(idx + 1); if (e.key === 'ArrowLeft') show(idx - 1); });

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
  if (o.userData.name && synth && speaking) { synth.cancel(); const u = new SpeechSynthesisUtterance(o.userData.name); u.lang = LANG; synth.speak(u); }
  track('vr.object.selected', { name: o.userData.name });
});

// ---------- telemetry (batched, de-duplicated server side; only learning events, no motion tracking) ----------
const queue = []; const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
function track(type, evidence) {
  if (!M) return; queue.push({ event_id: crypto.randomUUID?.() || String(Math.random()).slice(2) + Date.now(), event_type: type, schema_version: 1,
    lesson_db_id: CFG.lessonId, lesson_id: M.lesson_id, lesson_version: M.version, evidence, occurred_at: new Date().toISOString() });
  if (queue.length >= 10) flush();
}
async function flush() { if (!queue.length) return; const batch = queue.splice(0, 100);
  try { await fetch(CFG.eventsUrl, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify({ events: batch }), keepalive: true }); } catch { queue.unshift(...batch); } }
setInterval(flush, 8000); addEventListener('pagehide', flush);

// ---------- boot ----------
const vrBtn = VRButton.createButton(renderer);
document.body.appendChild(vrBtn);
vrBtn.id = 'VRButton';
addEventListener('resize', () => { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); });
const clock = new THREE.Clock();
renderer.setAnimationLoop(() => { const dt = clock.getDelta(), t = clock.elapsedTime; anim.forEach((f) => f(t, dt)); controls.update(); renderer.render(scene, camera); });
fetch(CFG.manifestUrl).then((r) => r.json()).then((m) => { M = m; show(0); }).catch(() => { $('stitle').textContent = 'Could not load lesson'; });
