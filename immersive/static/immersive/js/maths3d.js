// maths3d.js - real 3D maths scenes for young learners (pre-primary / primary "Maths Wise" style books).
// No imports on purpose: viewer.js hands in everything it owns (THREE, stage, anim, pickables, label, std ...).
// Every scene: objects stand on a platform (no floating cards), cast a soft shadow, are named when tapped,
// and can be touched/clicked to see the idea (count, mix, fold, hop, open ...).
export const MATHS_TYPES = ['shapes3d', 'counting', 'numline', 'opposites', 'colours', 'lines', 'symmetry', 'oddone'];

export function installMaths(ctx) {
  const { THREE, stage, anim, pickables, label, std, camera, controls } = ctx;
  const calm = () => !!(ctx.isCalm && ctx.isCalm());
  const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];

  // ---------------------------------------------------------------- helpers
  const put = (o, x = 0, y = 0, z = 0) => { o.position.set(x, y, z); stage.add(o); return o; };
  const mesh = (geo, color, o) => new THREE.Mesh(geo, std(color, o));
  const P = (m, x, y, z) => { m.position.set(x, y, z); return m; };
  const wrap = (o) => { const g = new THREE.Group(); g.add(o); return g; };
  const pick = (m, name, onClick) => { m.userData.name = name; if (onClick) m.userData.onClick = onClick; pickables.push(m); return m; };
  const text = (t, size, color, x, y, z) => { const s = label(t, size, color); s.position.set(x, y, z); stage.add(s); return s; };
  function live(size, color, x, y, z) {
    const spr = label(' ', size, color); spr.position.set(x, y, z); stage.add(spr);
    return { spr, set(t) { const n = label(t, size, color); spr.material.map.dispose(); spr.material.map = n.material.map; spr.scale.copy(n.scale); n.material.dispose(); } };
  }
  function platform(r, color = 0x14305f) {          // a round "table" so every object stands on something
    const g = new THREE.Group();
    g.add(mesh(new THREE.CylinderGeometry(r, r * 1.04, 0.16, 72), color, { roughness: 0.7 }));
    const rim = new THREE.Mesh(new THREE.TorusGeometry(r * 1.02, 0.025, 8, 96), new THREE.MeshBasicMaterial({ color: 0x5f8fe6, transparent: true, opacity: 0.8 }));
    rim.rotation.x = Math.PI / 2; rim.position.y = 0.08; g.add(rim);
    g.position.y = -0.08; stage.add(g); return g;
  }
  function shadow(x, z, r, y = 0.012) {
    const s = new THREE.Mesh(new THREE.CircleGeometry(r, 32), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.28, depthWrite: false }));
    s.rotation.x = -Math.PI / 2; s.position.set(x, y, z); stage.add(s); return s;
  }
  function edges(m, color = 0xffffff, op = 0.45) { m.add(new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({ color, transparent: true, opacity: op }))); return m; }
  function tween(dur, fn, done) {                    // fn(u) with u = 0..1; jumps to the end when "reduce motion" is on
    if (calm()) { fn(1); if (done) done(); return; }
    let el = 0, over = false;
    const f = (t, dt) => {
      if (over) return; el += dt; const u = Math.min(1, el / dur); fn(u * u * (3 - 2 * u));
      if (u >= 1) { over = true; setTimeout(() => { const i = anim.indexOf(f); if (i >= 0) anim.splice(i, 1); }, 0); if (done) done(); }
    };
    anim.push(f);
  }
  const hop = (g, y0, h) => tween(0.55, (u) => { g.position.y = y0 + Math.sin(u * Math.PI) * h; });
  const spin = (g) => tween(0.9, (u) => { g.rotation.y = u * Math.PI * 2; });
  function disposeTree(o) { o.traverse((c) => { c.geometry?.dispose?.(); if (c.material) { c.material.map?.dispose?.(); c.material.dispose?.(); } }); }
  function frame(px, py, pz, tx, ty, tz) { camera.position.set(px, py, pz); controls.target.set(tx, ty, tz); }
  function numTexture(n, bg, fg = '#ffffff') {
    const c = document.createElement('canvas'); c.width = c.height = 128; const x = c.getContext('2d');
    x.fillStyle = bg; x.beginPath(); x.arc(64, 64, 62, 0, 6.283); x.fill();
    x.fillStyle = fg; x.font = '700 78px "Segoe UI", Arial, sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillText(String(n), 64, 70);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
  }
  const ground = (cx, cz, w, d, color = 0x1d3a70) => { const m = mesh(new THREE.BoxGeometry(w, 0.1, d), color, { roughness: 0.8 }); put(m, cx, -0.05, cz); return m; };

  // ================================================================ 1. SHAPES (2-D flat vs 3-D solid, flat / curved surfaces, real objects)
  function everyday(kind) {                           // small real-life object built from simple solids
    const g = new THREE.Group();
    if (kind === 'cube') {                            // dice
      g.add(P(mesh(new THREE.BoxGeometry(0.5, 0.5, 0.5), 0xffffff), 0, 0.25, 0));
      [[-0.12, -0.12], [0.12, -0.12], [0, 0], [-0.12, 0.12], [0.12, 0.12]].forEach(([a, b]) => { const d = mesh(new THREE.CircleGeometry(0.045, 16), 0x111111); d.rotation.x = -Math.PI / 2; d.position.set(a, 0.502, b); g.add(d); });
    } else if (kind === 'cuboid') {                   // book
      g.add(P(mesh(new THREE.BoxGeometry(0.85, 0.2, 0.6), 0xd94a4a), 0, 0.1, 0));
      g.add(P(mesh(new THREE.BoxGeometry(0.8, 0.14, 0.55), 0xfff3d6), 0.04, 0.1, 0));
    } else if (kind === 'sphere') {                   // ball
      g.add(P(mesh(new THREE.SphereGeometry(0.3, 32, 24), 0xff8a3d), 0, 0.3, 0));
      const b = new THREE.Mesh(new THREE.TorusGeometry(0.3, 0.018, 8, 48), new THREE.MeshBasicMaterial({ color: 0x222222 })); b.position.y = 0.3; g.add(b);
    } else if (kind === 'cone') {                     // party hat
      g.add(P(mesh(new THREE.ConeGeometry(0.27, 0.62, 32), 0xff5fa2), 0, 0.31, 0));
      g.add(P(mesh(new THREE.SphereGeometry(0.07, 16, 12), 0xffe066), 0, 0.64, 0));
    } else if (kind === 'cylinder') {                 // tin
      g.add(P(mesh(new THREE.CylinderGeometry(0.24, 0.24, 0.5, 32), 0xc9d2e0, { metalness: 0.4 }), 0, 0.25, 0));
      g.add(P(mesh(new THREE.CylinderGeometry(0.248, 0.248, 0.16, 32), 0xe5484d), 0, 0.25, 0));
    } else {                                          // pyramid -> tent
      const t = mesh(new THREE.ConeGeometry(0.46, 0.55, 4), 0xf0aa49); t.rotation.y = Math.PI / 4; t.position.y = 0.275; g.add(t);
    }
    return g;
  }
  function shapes3d(v, sc) {
    platform(5.4);
    const R = 3.4, base = 0.16;
    const defs = [
      ['Cube', new THREE.BoxGeometry(1, 1, 1), 0x20b7c4, 1, '6 flat faces · 12 edges · 8 corners', 'cube', 'Dice'],
      ['Cuboid', new THREE.BoxGeometry(1.5, 0.8, 0.9), 0x7a5bf1, 0.8, '6 flat faces (rectangles) · like a brick', 'cuboid', 'Book'],
      ['Sphere', new THREE.SphereGeometry(0.58, 48, 32), 0xe5484d, 1.16, '1 curved surface · no flat face · it rolls', 'sphere', 'Ball'],
      ['Cone', new THREE.ConeGeometry(0.6, 1.25, 48), 0xf0aa49, 1.25, '1 flat face (base) + 1 curved surface · 1 tip', 'cone', 'Party hat'],
      ['Cylinder', new THREE.CylinderGeometry(0.5, 0.5, 1.1, 48), 0x11a88b, 1.1, '2 flat faces + 1 curved surface · it rolls on its side', 'cylinder', 'Tin'],
      ['Pyramid', (() => { const g = new THREE.ConeGeometry(0.78, 1.2, 4); g.rotateY(Math.PI / 4); return g; })(), 0x3b82f6, 1.2, '1 square base + 4 triangle faces · 5 corners', 'pyramid', 'Tent'],
    ];
    const head = live(0.4, '#ffffff', 0, 3.75, -1.8), sub = live(0.26, '#ffe066', 0, 3.3, -1.8);
    head.set('3-D shapes you can hold'); sub.set('Tap a shape · tap the object next to it');
    defs.forEach(([name, geo, col, h, info, kind, objName], i) => {
      const a = (-62 + i * 24.8) * Math.PI / 180, x = Math.sin(a) * R, z = -Math.cos(a) * R * 0.6;
      const g = new THREE.Group(); g.position.set(x, 0, z); stage.add(g);
      shadow(x, z + 0.05, 0.85);
      g.add(P(mesh(new THREE.CylinderGeometry(0.78, 0.84, base, 40), 0x2b4a86), 0, base / 2, 0));
      const solid = mesh(geo, col, { roughness: 0.35 }); solid.position.y = base + h / 2; edges(solid); g.add(solid);
      text(name, 0.34, '#ffffff', x, base + h + 0.5, z);
      const obj = everyday(kind); obj.position.set(x + Math.sin(a) * 0.15, 0, z + 1.05); stage.add(obj);
      shadow(x, z + 1.05, 0.38);
      const show = () => { head.set(name + '  ≈  ' + objName); sub.set(info); spin(g); hop(obj, 0, 0.35); };
      pick(solid, name + ' - tap to learn', show);
      obj.traverse((c) => { if (c.isMesh) pick(c, objName + ' has the shape of a ' + name.toLowerCase(), show); });
      anim.push((t) => { solid.rotation.y = t * 0.5; });
    });
    // flat (2-D) shapes lying on the floor in front: no height, nothing can be put inside
    const flat = [['Circle', new THREE.CircleGeometry(0.42, 48), 0xe5484d], ['Square', new THREE.PlaneGeometry(0.8, 0.8), 0x20b7c4],
      ['Triangle', (() => { const s = new THREE.Shape(); s.moveTo(-0.45, -0.38); s.lineTo(0.45, -0.38); s.lineTo(0, 0.42); s.closePath(); return new THREE.ShapeGeometry(s); })(), 0x3b82f6],
      ['Rectangle', new THREE.PlaneGeometry(1.1, 0.65), 0x7a5bf1]];
    flat.forEach(([n, geo, col], i) => {
      const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: col, roughness: 0.5, side: THREE.DoubleSide }));
      m.rotation.x = -Math.PI / 2; m.position.set((i - 1.5) * 1.55, 0.02, 2.5); stage.add(m);
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: 0xffffff })); m.add(e);
      pick(m, n + ' - 2-D: flat, no height', () => { head.set(n + '  (2-D)'); sub.set('Flat: it has no height and cannot hold anything'); hop(m, 0.02, 0.3); });
    });
    text('2-D = flat   ·   3-D = solid, can hold things', 0.26, '#9fd0ff', 0, 0.55, 3.35);
    frame(0, 3.4, 9.2, 0, 1.3, -0.2);
  }

  // ================================================================ 2. COUNTING 1..10 (columns of cubes, tap = count one by one)
  function counting() {
    platform(4.6);
    const s = 0.44, step = 0.5, cols = [], cx = (i) => (i - 5.5) * 0.62;
    const big = live(0.5, '#ffe066', 0, 5.9, 0), sub = live(0.3, '#9fd0ff', 0, 5.35, 0), cnt = live(0.36, '#7fe3ff', 0, 4.85, 0);
    big.set('Count with me!'); sub.set('Tap a tower'); cnt.set(' ');
    for (let n = 1; n <= 10; n++) {
      const g = new THREE.Group(); g.position.set(cx(n), 0, 0); stage.add(g); const cubes = [];
      for (let k = 0; k < n; k++) {
        const c = mesh(new THREE.BoxGeometry(s, s, s), k < 5 ? 0x4da3ff : 0xffb347, { roughness: 0.35 }); c.position.y = s / 2 + k * step; edges(c, 0xffffff, 0.35); g.add(c); cubes.push(c);
        pick(c, n + ' = ' + WORDS[n], () => activate(n));
      }
      cols.push(cubes);
      text(String(n), 0.42, '#ffffff', cx(n), 0.3, 0.85);
      shadow(cx(n), 0.1, 0.34);
    }
    text('first 5 = one hand ✋     next 5 = other hand ✋', 0.26, '#9fd0ff', 0, -0.5, 1.2);
    let current = 0;
    function activate(n) {
      current = n; big.set(n + '  =  ' + WORDS[n]); sub.set('before: ' + (n > 1 ? n - 1 : '—') + '    ·    after: ' + (n < 10 ? n + 1 : '—'));
      tween(0.3 * n + 0.3, (u) => {
        const k = Math.min(n, Math.floor(u * (n + 0.999)));
        cols.forEach((cs, idx) => cs.forEach((c, j) => { const on = idx === n - 1 && j < k; c.material.emissive.set(on ? 0xffffff : 0x000000); c.material.emissiveIntensity = on ? 0.7 : 0; }));
        cnt.set(k ? Array.from({ length: k }, (_, i) => i + 1).join(' · ') : ' ');
      });
    }
    let touched = false, last = 0;
    cols.forEach((cs) => cs.forEach((c) => { const f = c.userData.onClick; c.userData.onClick = () => { touched = true; f(); }; }));
    anim.push((t) => { if (touched || calm()) return; const k = (Math.floor(t / 2.4) % 10) + 1; if (k !== last) { last = k; activate(k); } });
    if (calm()) activate(5);
    frame(0, 3.3, 11.2, 0, 2.5, 0);
  }

  // ================================================================ 3. NUMBER LINE / BEFORE & AFTER (stepping stones, a frog hops)
  function numline() {
    platform(5.6);
    const pos = (i) => new THREE.Vector3((i - 5.5) * 0.95, 0.09, Math.sin(i * 0.75) * 0.9);
    const stones = [];
    for (let i = 1; i <= 10; i++) {
      const p = pos(i), st = mesh(new THREE.CylinderGeometry(0.4, 0.44, 0.18, 40), i % 2 ? 0x2b6cb0 : 0x20b7c4); st.position.copy(p); st.position.y = 0.09; stage.add(st);
      const top = new THREE.Mesh(new THREE.CircleGeometry(0.36, 32), new THREE.MeshBasicMaterial({ map: numTexture(i, i % 2 ? '#2b6cb0' : '#20b7c4'), transparent: true }));
      top.rotation.x = -Math.PI / 2; top.position.set(p.x, 0.185, p.z); stage.add(top);
      pick(st, 'Number ' + i + ' - tap to hop here', () => { touched = true; goTo(i); }); pick(top, 'Number ' + i, () => { touched = true; goTo(i); });
      shadow(p.x, p.z, 0.5); stones.push(p);
    }
    const frog = new THREE.Group(); put(frog, 0, 0.18, 0);
    const body = mesh(new THREE.SphereGeometry(0.28, 24, 18), 0x4cc35e); body.scale.set(1, 0.75, 1.1); body.position.y = 0.22; frog.add(body);
    [-0.12, 0.12].forEach((x) => { const e = mesh(new THREE.SphereGeometry(0.09, 16, 12), 0xffffff); e.position.set(x, 0.46, 0.12); const pu = mesh(new THREE.SphereGeometry(0.045, 12, 10), 0x111111); pu.position.set(0, 0, 0.065); e.add(pu); frog.add(e); });
    pick(body, 'Hop the frog', () => { touched = true; goTo(Math.min(10, cur + 1)); });
    const beforeR = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.05, 10, 40), new THREE.MeshBasicMaterial({ color: 0x7fb0ff })); beforeR.rotation.x = Math.PI / 2;
    const afterR = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.05, 10, 40), new THREE.MeshBasicMaterial({ color: 0xffb347 })); afterR.rotation.x = Math.PI / 2;
    stage.add(beforeR, afterR);
    const bl = text('BEFORE', 0.24, '#7fb0ff', 0, 1, 0), al = text('AFTER', 0.24, '#ffb347', 0, 1, 0);
    const big = live(0.46, '#ffe066', 0, 3.0, 0), sub = live(0.3, '#cfe0ff', 0, 2.45, 0);
    text('numbers get bigger  ➜', 0.26, '#9fd0ff', 0, 0.3, 2.3);
    let cur = 0, touched = false;
    function goTo(n) {
      const from = cur ? stones[cur - 1].clone() : stones[0].clone().add(new THREE.Vector3(-1, 0, 0)), to = stones[n - 1].clone(), prev = cur; cur = n;
      big.set(n + ' (' + WORDS[n] + ')');
      sub.set((n > 1 ? (n - 1) + ' comes BEFORE ' + n : 'Start here: 1') + (n < 10 ? '  ·  ' + (n + 1) + ' comes AFTER ' + n : ''));
      beforeR.visible = bl.visible = n > 1; afterR.visible = al.visible = n < 10;
      if (n > 1) { const p = stones[n - 2]; beforeR.position.set(p.x, 0.2, p.z); bl.position.set(p.x, 1.0, p.z); }
      if (n < 10) { const p = stones[n]; afterR.position.set(p.x, 0.2, p.z); al.position.set(p.x, 1.0, p.z); }
      tween(0.6, (u) => { frog.position.lerpVectors(from, to, u); frog.position.y = 0.18 + Math.sin(u * Math.PI) * 0.7; frog.rotation.y = Math.atan2(to.x - from.x, to.z - from.z); });
    }
    let last = 0;
    anim.push((t) => { if (touched || calm()) return; const k = (Math.floor(t / 2.2) % 10) + 1; if (k !== last) { last = k; goTo(k); } });
    if (calm()) goTo(5);
    frame(0, 4.4, 9.0, 0, 0.6, 0);
  }

  // ================================================================ 4. OPPOSITES (pairs stand side by side; tap = next pair)
  const tree = (h, col = 0x2fa84f) => { const g = new THREE.Group(); const t = mesh(new THREE.CylinderGeometry(0.14, 0.18, h, 16), 0x8b5a2b); t.position.y = h / 2; const f = mesh(new THREE.ConeGeometry(0.62, 0.9, 24), col); f.position.y = h + 0.3; g.add(t, f); return g; };
  const ball = (r, col) => { const m = mesh(new THREE.SphereGeometry(r, 32, 24), col); m.position.y = r; return m; };
  const jar = (r, h, col) => { const m = mesh(new THREE.CylinderGeometry(r, r, h, 40), col, { roughness: 0.3 }); m.position.y = h / 2; return m; };
  const face = (happy) => {
    const g = new THREE.Group(), f = mesh(new THREE.SphereGeometry(0.8, 40, 30), happy ? 0xffd23f : 0x9bb4d8); f.position.y = 0.95; g.add(f);
    [-0.28, 0.28].forEach((x) => { const e = mesh(new THREE.SphereGeometry(0.09, 12, 10), 0x1a1a1a); e.position.set(x, 1.12, 0.72); g.add(e); });
    const m = new THREE.Mesh(new THREE.TorusGeometry(0.34, 0.045, 10, 32, Math.PI), new THREE.MeshBasicMaterial({ color: 0x1a1a1a }));
    if (happy) { m.rotation.z = Math.PI; m.position.set(0, 0.85, 0.74); } else { m.position.set(0, 0.62, 0.74); const tear = mesh(new THREE.SphereGeometry(0.07, 12, 10), 0x4da3ff); tear.scale.y = 1.4; tear.position.set(0.3, 0.98, 0.76); g.add(tear); }
    g.add(m); return g;
  };
  const openBox = (ballIn) => {
    const g = new THREE.Group(), w = 1.4, h = 0.8, t = 0.07, c = 0xd9a05b;
    [[0, 0.04, 0, w, t, w], [-w / 2, h / 2, 0, t, h, w], [w / 2, h / 2, 0, t, h, w], [0, h / 2, -w / 2, w, h, t], [0, h / 2, w / 2, w, h, t]].forEach(([x, y, z, a, b, d]) => { const m = mesh(new THREE.BoxGeometry(a, b, d), c); m.position.set(x, y, z); g.add(m); });
    const bl = ball(0.3, 0xe5484d); bl.position.set(ballIn ? 0 : 1.3, ballIn ? 0.34 : 0.3, ballIn ? 0 : 0.2); g.add(bl); return g;
  };
  const lidBox = (open) => {
    const g = new THREE.Group(), b = mesh(new THREE.BoxGeometry(1.4, 0.8, 1.1), 0x7a5bf1); b.position.y = 0.4; g.add(b);
    const piv = new THREE.Group(); piv.position.set(0, 0.8, -0.55); const lid = mesh(new THREE.BoxGeometry(1.46, 0.12, 1.14), 0xa78bfa); lid.position.set(0, 0.06, 0.57); piv.add(lid); piv.rotation.x = open ? -1.9 : 0; g.add(piv); return g;
  };
  const sunRays = () => { const g = new THREE.Group(); const s = mesh(new THREE.SphereGeometry(0.5, 32, 24), 0xffd23f, { emissive: 0xffa800, emissiveIntensity: 1.2 }); g.add(s);
    for (let i = 0; i < 10; i++) { const r = mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.36, 8), 0xffd23f, { emissive: 0xffa800, emissiveIntensity: 1 }); const a = i / 10 * Math.PI * 2; r.position.set(Math.cos(a) * 0.82, Math.sin(a) * 0.82, 0); r.rotation.z = a - Math.PI / 2; g.add(r); } return g; };
  const flame = () => { const g = new THREE.Group(); [[0.42, 0.95, 0xff3b1f], [0.32, 0.72, 0xff8a1f], [0.2, 0.46, 0xffe066]].forEach(([r, h, c]) => { const f = mesh(new THREE.ConeGeometry(r, h, 24), c, { emissive: c, emissiveIntensity: 0.9 }); f.position.y = h / 2 + 0.25; g.add(f); anim.push((t) => { f.scale.y = 1 + Math.sin(t * 9 + r * 20) * 0.08; }); }); g.add(P(mesh(new THREE.CylinderGeometry(0.6, 0.6, 0.18, 24), 0x7a4b25), 0, 0.09, 0)); return g; };
  const ice = () => { const g = new THREE.Group(); [[0, 0.3, 0], [0.55, 0.3, 0.1], [0.25, 0.85, 0.05]].forEach(([x, y, z], i) => { const c = new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.56, 0.56), new THREE.MeshStandardMaterial({ color: 0xbfeaff, transparent: true, opacity: 0.78, roughness: 0.1 })); c.position.set(x - 0.3, y, z); c.rotation.y = 0.3 * i; edges(c, 0xffffff, 0.8); g.add(c); }); return g; };
  const dayNight = (day) => { const g = new THREE.Group(); const sky = new THREE.Mesh(new THREE.CircleGeometry(1.45, 48), new THREE.MeshBasicMaterial({ color: day ? 0x5ec8ff : 0x0b1030 })); sky.position.set(0, 1.55, -0.2); g.add(sky);
    const gr = mesh(new THREE.CylinderGeometry(1.45, 1.45, 0.2, 48), day ? 0x3fae5a : 0x1d4a34); gr.position.y = 0.1; g.add(gr);
    if (day) { const s = sunRays(); s.position.set(0.25, 2.0, 0); s.scale.setScalar(0.8); g.add(s); } else { const m = mesh(new THREE.SphereGeometry(0.45, 32, 24), 0xfff4c2, { emissive: 0xfff4c2, emissiveIntensity: 0.6 }); m.position.set(0.3, 2.0, 0); g.add(m); const cut = mesh(new THREE.SphereGeometry(0.4, 32, 24), 0x0b1030); cut.position.set(0.5, 2.1, 0.12); g.add(cut);
      for (let i = 0; i < 9; i++) { const st = new THREE.Mesh(new THREE.SphereGeometry(0.04, 8, 6), new THREE.MeshBasicMaterial({ color: 0xffffff })); st.position.set(-1 + (i * 0.43) % 2, 1.2 + (i * 0.37) % 1.2, 0.1); g.add(st); } }
    return g; };
  const PAIRS = [
    { re: /\b(big|small)\b/, a: 'BIG', b: 'SMALL', mk: () => [ball(1.0, 0x3b82f6), ball(0.35, 0x3b82f6)] },
    { re: /\b(tall|short)\b/, a: 'TALL', b: 'SHORT', mk: () => [tree(2.3), tree(0.7)] },
    { re: /\b(fat|thin)\b/, a: 'FAT', b: 'THIN', mk: () => [jar(0.85, 1.3, 0xf0aa49), jar(0.3, 1.3, 0xf0aa49)] },
    { re: /\b(up and down|going up|climbing)\b/, a: 'UP', b: 'DOWN', mk: () => { const A = new THREE.Group(); const st = mesh(new THREE.CylinderGeometry(0.4, 0.5, 1.8, 24), 0x2b4a86); st.position.y = 0.9; const bl = ball(0.4, 0xe5484d); bl.position.y = 2.2; A.add(st, bl); const ar = mesh(new THREE.ConeGeometry(0.2, 0.45, 16), 0x7fe3ff); ar.position.y = 3.0; A.add(ar); const B = new THREE.Group(); const b2 = ball(0.4, 0xe5484d); const ar2 = mesh(new THREE.ConeGeometry(0.2, 0.45, 16), 0x7fe3ff); ar2.rotation.x = Math.PI; ar2.position.y = 1.2; B.add(b2, ar2); return [A, B]; } },
    { re: /\b(in and out|kennel)\b/, a: 'IN', b: 'OUT', mk: () => [openBox(true), openBox(false)] },
    { re: /\b(hot|cold)\b/, a: 'HOT', b: 'COLD', note: '⚠ Careful! Never touch hot things', mk: () => [flame(), ice()] },
    { re: /\b(open|closed|close)\b/, a: 'OPEN', b: 'CLOSED', mk: () => [lidBox(true), lidBox(false)] },
    { re: /\b(day and night|night|moon)\b/, a: 'DAY', b: 'NIGHT', mk: () => [dayNight(true), dayNight(false)] },
    { re: /\b(happy|sad)\b/, a: 'HAPPY', b: 'SAD', mk: () => [face(true), face(false)] },
  ];
  function opposites(v, sc) {
    platform(5.2);
    const holder = new THREE.Group(); stage.add(holder);
    const title = live(0.5, '#ffe066', 0, 3.9, 0), note = live(0.24, '#ffb3b3', 0, 3.35, 0), dots = live(0.2, '#9fd0ff', 0, -0.55, 1.6);
    const prev = text('◀', 0.6, '#ffffff', -3.9, 1.6, 0.5), nextB = text('▶', 0.6, '#ffffff', 3.9, 1.6, 0.5);
    pick(prev, 'Previous pair', () => { touched = true; showPair(cur - 1); }); pick(nextB, 'Next pair', () => { touched = true; showPair(cur + 1); });
    let cur = -1, touched = false;
    function showPair(i) {
      cur = (i + PAIRS.length) % PAIRS.length; const P = PAIRS[cur];
      while (holder.children.length) { const o = holder.children[0]; holder.remove(o); disposeTree(o); }
      const [A, B] = P.mk(); A.position.x = -1.9; B.position.x = 1.9; holder.add(A, B);
      [[A, -1.9, P.a], [B, 1.9, P.b]].forEach(([o, x, nm]) => { holder.add(shadow(x, 0, 0.9)); o.traverse((c) => { if (c.isMesh) pick(c, nm + ' - tap for the next pair', () => { touched = true; showPair(cur + 1); }); }); const l = label(nm, 0.5, nm === P.a ? '#ffe066' : '#7fe3ff'); l.position.set(x, 3.0, 0); holder.add(l); });
      const vs = label('↔', 0.6, '#ffffff'); vs.position.set(0, 1.5, 0); holder.add(vs);
      title.set(P.a + '  ↔  ' + P.b); note.set(P.note || ' '); dots.set(PAIRS.map((_, k) => (k === cur ? '●' : '○')).join(' '));
      A.scale.setScalar(0.01); B.scale.setScalar(0.01); tween(0.45, (u) => { A.scale.setScalar(0.01 + 0.99 * u); B.scale.setScalar(0.01 + 0.99 * u); });
    }
    const hay = ((sc && (sc.title + ' ' + (sc.narration || '') + ' ' + (v.labels || []).join(' '))) || '').toLowerCase();
    let start = -1, best = 1e9;
    PAIRS.forEach((p, k) => { const m = hay.match(p.re); if (m && m.index < best) { start = k; best = m.index; } });
    const pinned = start >= 0; showPair(pinned ? start : 0);
    let last = 0;
    anim.push((t) => { if (touched || pinned || calm()) return; const k = Math.floor(t / 5); if (k !== last) { last = k; showPair(k % PAIRS.length); } });
    frame(0, 3.0, 9.4, 0, 1.5, 0);
  }

  // ================================================================ 5. COLOURS (primary pots mix in a bowl + rainbow arch)
  function colours() {
    platform(5.2);
    const PRIM = [['Red', 0xe5484d, -2.4], ['Yellow', 0xffd23f, 0], ['Blue', 0x2b6cff, 2.4]];
    const MIX = { 'Red': [0xe5484d, 'Red'], 'Yellow': [0xffd23f, 'Yellow'], 'Blue': [0x2b6cff, 'Blue'], 'Red+Yellow': [0xff8c1a, 'Orange'], 'Blue+Yellow': [0x2fbf4a, 'Green'], 'Blue+Red': [0x8a3fd1, 'Purple'], 'Blue+Red+Yellow': [0x7a4a2a, 'Brown'] };
    ['Red', 'Orange', 'Yellow', 'Green', 'Blue', 'Indigo', 'Violet'].forEach((n, k) => {     // VIBGYOR from the outside in (red outside)
      const cols = [0xff3b30, 0xff9500, 0xffe033, 0x34c759, 0x2b6cff, 0x4b3fb5, 0x9b59d6];
      const a = new THREE.Mesh(new THREE.TorusGeometry(3.7 - k * 0.2, 0.1, 12, 80, Math.PI), new THREE.MeshStandardMaterial({ color: cols[k], emissive: cols[k], emissiveIntensity: 0.35, roughness: 0.4 }));
      a.position.set(0, 0.2, -2.6); stage.add(a); pick(a, n + ' - a colour of the rainbow');
    });
    [[-3.9, -2.6], [3.9, -2.6]].forEach(([x, z]) => [0, 0.5, -0.45].forEach((d, i) => { const c = mesh(new THREE.SphereGeometry(0.42 - i * 0.05, 20, 16), 0xffffff, { roughness: 0.9 }); put(c, x + d, 0.4 + (i ? 0.12 : 0), z); }));
    const bowl = new THREE.Group(); put(bowl, 0, 0.1, -0.2);
    const shell = new THREE.Mesh(new THREE.SphereGeometry(1.2, 48, 24, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0xe9eef8, side: THREE.DoubleSide, roughness: 0.3 })); shell.position.y = 0.85; bowl.add(shell);
    const paint = mesh(new THREE.CircleGeometry(1.05, 48), 0xbfe3ff, { roughness: 0.15 }); paint.rotation.x = -Math.PI / 2; paint.position.y = 0.9 - 0.02; bowl.add(paint);
    pick(paint, 'Mixing bowl'); pick(shell, 'Mixing bowl');
    const big = live(0.48, '#ffffff', 0, 3.7, 0), sub = live(0.28, '#9fd0ff', 0, 3.2, 0);
    big.set('Mix the colours!'); sub.set('Tap two paint pots');
    const sel = new Set(), pots = {};
    let target = new THREE.Color(0xbfe3ff), touched = false;
    PRIM.forEach(([n, col, x]) => {
      const g = new THREE.Group(); put(g, x, 0, 1.7); pots[n] = g; shadow(x, 1.75, 0.6);
      const body = mesh(new THREE.CylinderGeometry(0.48, 0.42, 0.7, 32), 0xdfe6f3, { roughness: 0.3 }); body.position.y = 0.35; const top = mesh(new THREE.CylinderGeometry(0.4, 0.4, 0.04, 32), col, { emissive: col, emissiveIntensity: 0.25 }); top.position.y = 0.68;
      const band = mesh(new THREE.CylinderGeometry(0.485, 0.435, 0.2, 32), col); band.position.y = 0.35; g.add(body, top, band);
      text(n, 0.3, '#ffffff', x, 1.3, 1.7);
      const click = () => { touched = true; toggle(n); };
      [body, top, band].forEach((m) => pick(m, n + ' paint - tap to add', click));
    });
    function describe() {
      const key = [...sel].sort().join('+'); const m = MIX[key];
      if (!m) { big.set(sel.size ? 'Pick another!' : 'Mix the colours!'); sub.set('Tap two paint pots'); target.set(0xbfe3ff); return; }
      big.set(sel.size > 1 ? [...sel].sort((a, b) => ['Red', 'Yellow', 'Blue'].indexOf(a) - ['Red', 'Yellow', 'Blue'].indexOf(b)).join(' + ') + '  =  ' + m[1] : m[1]);
      sub.set(sel.size > 1 ? 'A new colour was made!' : 'Add one more colour'); target.set(m[0]);
    }
    function toggle(n) {
      if (sel.has(n)) sel.delete(n); else { if (sel.size >= 3) sel.clear(); sel.add(n); }
      Object.entries(pots).forEach(([k, g]) => { const up = sel.has(k); tween(0.3, (u) => { g.position.y = up ? 0.35 * u : 0.35 * (1 - u); }); });
      const [, col, x] = PRIM.find((p) => p[0] === n); const drop = mesh(new THREE.SphereGeometry(0.16, 16, 12), col); put(drop, x, 1.0, 1.7);
      tween(0.55, (u) => { drop.position.set(x * (1 - u), 1.0 + Math.sin(u * Math.PI) * 1.2 - 0.1 * u, 1.7 - 1.9 * u); if (u >= 1) { stage.remove(drop); disposeTree(drop); } });
      describe();
    }
    const demo = [['Red', 'Yellow'], ['Yellow', 'Blue'], ['Red', 'Blue']]; let lastD = -1;
    anim.push((t, dt) => {
      paint.material.color.lerp(target, Math.min(1, dt * 6)); paint.material.emissive.copy(paint.material.color).multiplyScalar(0.15);
      if (touched || calm()) return; const k = Math.floor(t / 3.2) % demo.length; if (k !== lastD) { lastD = k; sel.clear(); demo[k].forEach((n) => sel.add(n)); Object.entries(pots).forEach(([kk, g]) => { g.position.y = sel.has(kk) ? 0.35 : 0; }); describe(); }
    });
    if (calm()) { sel.add('Red'); sel.add('Yellow'); describe(); paint.material.color.copy(target); }
    frame(0, 3.2, 9.0, 0, 1.4, -0.4);
  }

  // ================================================================ 6. LINES (vertical / horizontal / slanting sticks in sand, string: straight vs curved)
  function lines() {
    platform(5.4);
    const tray = mesh(new THREE.BoxGeometry(7, 0.3, 3.4), 0xd9b779, { roughness: 1 }); put(tray, 0, 0.15, 0.9);
    pick(tray, 'Sand tray');
    const stick = (len) => mesh(new THREE.CylinderGeometry(0.07, 0.07, len, 16), 0x8b5a2b);
    const v1 = stick(2.2); put(v1, -2.3, 0.3 + 1.1, 0.5); pick(v1, 'Vertical line - standing straight up');
    const h1 = stick(2.2); h1.rotation.z = Math.PI / 2; put(h1, 0, 0.3 + 0.07, 0.5); pick(h1, 'Horizontal line - lying flat');
    const s1 = stick(2.2); s1.rotation.z = -0.6; put(s1, 2.3, 0.3 + 1.1 * Math.cos(0.6) + 0.04, 0.5); pick(s1, 'Slanting line - leaning');
    text('Vertical  |', 0.32, '#ffffff', -2.3, 3.0, 0.5); text('Horizontal  —', 0.32, '#ffffff', 0, 1.2, 0.5); text('Slanting  /', 0.32, '#ffffff', 2.3, 3.0, 0.5);
    const curve = (pts, col = 0x5a3a1a) => { const m = mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 120, 0.045, 8, false), col); stage.add(m); return m; };
    const wave = []; for (let i = 0; i <= 30; i++) wave.push(new THREE.Vector3(-3 + i * 0.1, 0.34, 1.85 + Math.sin(i * 0.65) * 0.28));
    pick(curve(wave), 'A wavy curved line');
    const sp = []; for (let i = 0; i <= 50; i++) { const a = i * 0.42, r = 0.08 + i * 0.012; sp.push(new THREE.Vector3(1.9 + Math.cos(a) * r * 2.2, 0.34, 1.85 + Math.sin(a) * r * 2.2)); }
    pick(curve(sp), 'A spiral curved line');
    text('curved lines  ∿  🌀', 0.3, '#5a3a1a', 0, 0.42, 2.45).position.y = 0.5;
    // string between two "hands": taut = straight line, loose = curved line
    const posts = [-1, 1].map((sd) => { const p = mesh(new THREE.CylinderGeometry(0.1, 0.1, 1.5, 16), 0x2b4a86); put(p, sd * 1.9, 0.75, -1.9); const hand = ball(0.17, 0xffc999); hand.position.y = 0.8; p.add(hand); return p; });
    let string = null; const big = live(0.42, '#ffe066', 0, 4.15, -1.9); const sub = live(0.26, '#9fd0ff', 0, 3.7, -1.9);
    let sag = 0, touched = false, going = false, state = 0;
    function drawString() {
      const ax = posts[0].position.x, bx = posts[1].position.x, pts = [];
      for (let i = 0; i <= 24; i++) { const u = i / 24; pts.push(new THREE.Vector3(ax + (bx - ax) * u, 1.62 - sag * 4 * u * (1 - u), -1.9)); }
      if (string) { stage.remove(string); string.geometry.dispose(); const pi = pickables.indexOf(string); if (pi >= 0) pickables.splice(pi, 1); }
      string = mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 48, 0.04, 8, false), 0xff5d5d); stage.add(string); pick(string, sag < 0.2 ? 'Taut string = straight line' : 'Loose string = curved line', toggle);
    }
    function toggle() { touched = true; setState(1 - state); }
    function setState(s) {
      state = s; const from = sag, to = s ? 1.1 : 0, fx = Math.abs(posts[1].position.x), tx = s ? 0.9 : 1.9;
      big.set(s ? 'Hands closer → CURVED line' : 'String pulled tight → STRAIGHT line'); sub.set('Tap the string');
      tween(0.7, (u) => { sag = from + (to - from) * u; const x = fx + (tx - fx) * u; posts[0].position.x = -x; posts[1].position.x = x; drawString(); });
    }
    posts.forEach((p) => pick(p, 'Hand - tap to move', toggle)); drawString(); big.set('String pulled tight → STRAIGHT line'); sub.set('Tap the string');
    let last = -1; anim.push((t) => { if (touched || calm()) return; const k = Math.floor(t / 3.5) % 2; if (k !== last) { last = k; setState(k); } });
    frame(0, 3.4, 9.6, 0, 1.4, -0.2);
  }

  // ================================================================ 7. SYMMETRY / HALVES (butterfly folds onto itself, apple opens into two equal halves)
  function symmetry() {
    platform(5.2);
    const wingShape = () => { const up = new THREE.Shape(); up.moveTo(0, 0.1); up.bezierCurveTo(0.2, 1.3, 1.5, 1.5, 1.6, 0.5); up.bezierCurveTo(1.6, 0.05, 0.7, -0.02, 0, 0.1);
      const lo = new THREE.Shape(); lo.moveTo(0, 0); lo.bezierCurveTo(0.9, -0.05, 1.5, -0.45, 1.05, -0.95); lo.bezierCurveTo(0.5, -1.3, 0.05, -0.7, 0, 0); return [up, lo]; };
    const makeWing = (col, tr) => { const g = new THREE.Group(); wingShape().forEach((s, k) => { const geo = new THREE.ExtrudeGeometry(s, { depth: 0.05, bevelEnabled: false }); const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: k ? 0xffb347 : col, roughness: 0.5, side: THREE.DoubleSide, transparent: !!tr })); g.add(m);
      g.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: 0x3a2a6a }))); });
      const spot = mesh(new THREE.CircleGeometry(0.2, 24), 0xffffff); spot.position.set(0.85, 0.55, 0.06); g.add(spot); const spot2 = mesh(new THREE.CircleGeometry(0.14, 24), 0x7fe3ff); spot2.position.set(0.7, -0.5, 0.06); g.add(spot2); return g; };
    const bf = new THREE.Group(); put(bf, -2.5, 1.95, 0);
    const right = new THREE.Group(); right.add(makeWing(0xff6b6b, true)); bf.add(right);
    const left = new THREE.Group(); left.add(makeWing(0xff6b6b)); left.scale.x = -1; bf.add(left);
    const body = mesh(new THREE.CapsuleGeometry(0.1, 1.3, 6, 12), 0x3a2a6a); body.position.y = -0.1; bf.add(body);
    [-1, 1].forEach((s) => { const a = mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.6, 6), 0x3a2a6a); a.position.set(s * 0.18, 0.78, 0); a.rotation.z = -s * 0.5; bf.add(a); });
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-2.5, 0.45, 0.1), new THREE.Vector3(-2.5, 3.55, 0.1)]), new THREE.LineDashedMaterial({ color: 0x7fe3ff, dashSize: 0.14, gapSize: 0.09 })); line.computeLineDistances(); stage.add(line);
    text('line of symmetry', 0.22, '#7fe3ff', -2.5, 3.8, 0);
    const stem = mesh(new THREE.CylinderGeometry(0.05, 0.07, 1.2, 10), 0x3fae5a); put(stem, -2.5, 0.6, -0.3); const fl = mesh(new THREE.SphereGeometry(0.22, 20, 16), 0xffe066); put(fl, -2.5, 1.2, -0.3);
    shadow(-2.5, -0.3, 0.5);
    let folded = false, bfTouch = false;
    const bfToggle = () => { bfTouch = true; foldTo(!folded); };
    function foldTo(f) { folded = f; const from = right.rotation.y, to = f ? Math.PI : 0; const z0 = right.position.z, z1 = f ? 0.14 : 0; tween(0.9, (u) => { right.rotation.y = from + (to - from) * u; right.position.z = z0 + (z1 - z0) * u; right.traverse((c) => { if (c.material && c.material.transparent) c.material.opacity = 1 - 0.45 * (z1 ? u : 1 - u); }); }); bfInfo.set(f ? 'Fold: the two halves match exactly!' : 'Butterfly: left half = right half'); }
    bf.traverse((c) => { if (c.isMesh) pick(c, 'Butterfly - tap to fold it', bfToggle); });
    const bfInfo = live(0.26, '#ffe066', -2.5, 4.25, 0); bfInfo.set('Butterfly: left half = right half');
    // apple
    const ap = new THREE.Group(); put(ap, 2.6, 1.05, 0); shadow(2.6, 0, 1.0);
    const half = (back) => { const g = new THREE.Group(); const sk = new THREE.Mesh(new THREE.SphereGeometry(0.95, 48, 32, back ? Math.PI : 0, Math.PI), new THREE.MeshStandardMaterial({ color: 0xe5484d, roughness: 0.4, side: THREE.DoubleSide })); g.add(sk);
      const fl = new THREE.Mesh(new THREE.CircleGeometry(0.95, 48), new THREE.MeshStandardMaterial({ color: 0xfff1c9, side: THREE.DoubleSide })); if (!back) fl.rotation.y = Math.PI; g.add(fl);
      [-0.16, 0.16].forEach((y) => { const sd = mesh(new THREE.SphereGeometry(0.07, 10, 8), 0x3a2410); sd.scale.set(0.7, 1.4, 0.4); sd.position.set(0, y - 0.1, back ? 0.03 : -0.03); g.add(sd); });
      const st = mesh(new THREE.CylinderGeometry(0.04, 0.04, 0.3, 8), 0x5a3a1a); st.position.y = 0.98; g.add(st);
      g.traverse((c) => { if (c.isMesh) pick(c, 'Apple - tap to cut it in half', () => apToggle()); }); return g; };
    const hb = half(true), hf = half(false); ap.add(hb, hf);
    let open = false, apTouch = false; const apInfo = live(0.26, '#ffe066', 2.6, 3.0, 0);
    const apToggle = () => { apTouch = true; apTo(!open); };
    function apTo(o) { open = o; const f0 = hf.position.x, f1 = o ? 1.15 : 0, r0 = hf.rotation.y, r1 = o ? Math.PI : 0, b0 = hb.position.x, b1 = o ? -1.15 : 0;
      tween(0.9, (u) => { hf.position.x = f0 + (f1 - f0) * u; hf.rotation.y = r0 + (r1 - r0) * u; hb.position.x = b0 + (b1 - b0) * u; });
      apInfo.set(o ? '2 equal halves  =  ½  +  ½' : '1 whole apple'); }
    apInfo.set('1 whole apple');
    text('Halves', 0.3, '#ffffff', 2.6, 3.4, 0);
    anim.push((t) => { if (calm()) return; if (!bfTouch) { const k = Math.floor(t / 3.2) % 2 === 1; if (k !== folded) foldTo(k); } if (!apTouch) { const k = Math.floor((t + 1.6) / 3.2) % 2 === 1; if (k !== open) apTo(k); } });
    if (calm()) apTo(true);
    frame(0, 2.8, 9.4, 0, 1.9, 0);
  }

  // ================================================================ 8. ODD ONE OUT (3 same + 1 different; tap the odd one)
  function oddone() {
    platform(5.0);
    const sets = [
      { mk: (odd) => wrap(odd ? P(mesh(new THREE.BoxGeometry(0.8, 0.8, 0.8), 0xe5484d), 0, 0.4, 0) : P(mesh(new THREE.SphereGeometry(0.5, 32, 24), 0xe5484d), 0, 0.5, 0)), why: 'A ball is round - the box has corners' },
      { mk: (odd) => { if (!odd) return tree(1.1); const g = new THREE.Group(); const h = mesh(new THREE.BoxGeometry(1, 0.8, 0.8), 0xf0aa49); h.position.y = 0.4; const r = mesh(new THREE.ConeGeometry(0.75, 0.5, 4), 0xc0392b); r.rotation.y = Math.PI / 4; r.position.y = 1.05; g.add(h, r); return g; }, why: 'Trees grow in a garden - this one is a house' },
      { mk: (odd) => wrap(jar(odd ? 0.28 : 0.5, 1.0, odd ? 0xe5484d : 0x11a88b)), why: 'This one is thin - the others are fat' },
      { mk: (odd) => wrap(odd ? P(mesh(new THREE.CylinderGeometry(0.45, 0.45, 1, 32), 0xf0aa49), 0, 0.5, 0) : P(mesh(new THREE.ConeGeometry(0.5, 1, 32), 0xf0aa49), 0, 0.5, 0)), why: 'Three cones - one cylinder' },
    ];
    const big = live(0.5, '#ffe066', 0, 3.4, 0), sub = live(0.28, '#9fd0ff', 0, 2.85, 0), score = live(0.22, '#7fe3ff', 0, -0.6, 1.8);
    const holder = new THREE.Group(); stage.add(holder); let round = -1, solved = 0, oddAt = 0;
    function next() {
      round = (round + 1) % sets.length; const S = sets[round]; oddAt = (round * 2 + 1) % 4;
      while (holder.children.length) { const o = holder.children[0]; holder.remove(o); disposeTree(o); }
      big.set('Which one is the ODD ONE OUT?'); sub.set('Tap it!');
      for (let i = 0; i < 4; i++) {
        const x = (i - 1.5) * 2.0, isOdd = i === oddAt, o = S.mk(isOdd), g = new THREE.Group(); g.position.set(x, 0, 0);
        const ped = mesh(new THREE.CylinderGeometry(0.85, 0.9, 0.14, 32), 0x2b4a86); ped.position.y = 0.07; o.position.y = 0.14; g.add(ped, o); holder.add(g); holder.add(shadow(x, 0.02, 0.8));
        g.traverse((c) => { if (c.isMesh && c !== ped) pick(c, 'Tap if this is the odd one out', () => answer(i, g, S)); });
      }
    }
    function answer(i, g, S) {
      if (i === oddAt) { solved++; big.set('✔ Yes! That is the odd one out'); sub.set(S.why); score.set('Correct: ' + solved); hop(g, 0, 0.7); spin(g); setTimeout(() => { if (holder.parent) next(); }, calm() ? 600 : 2400); }
      else { big.set('✘ Try again'); sub.set('Look carefully: three are the same'); tween(0.4, (u) => { g.position.x = (i - 1.5) * 2.0 + Math.sin(u * 20) * 0.12 * (1 - u); }); }
    }
    score.set('Correct: 0'); next();
    frame(0, 3.2, 8.4, 0, 1.2, 0);
  }

  return { shapes3d, counting, numline, opposites, colours, lines, symmetry, oddone };
}
