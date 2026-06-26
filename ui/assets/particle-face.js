/* particle-face.js — agent-agnostic particle facial visualization.
 *
 * Public API (window.ParticleFace):
 *   init({ canvas, count, style })   boot + RAF loop + resize handling
 *   setExpression(name, styleKey?)   morph to a face; 'idle'/null = dissolve to freeform
 *   setStyle(styleKey)               swap agent colour/motion profile
 *   setAudioLevel(0..1)              optional speech-amplitude pulse
 *   stop()                           halt loop (rarely needed)
 *
 * Particle shape matches the spec: { x, y, vx, vy, targetX, targetY, size, alpha }.
 * No dependencies. Canvas2D, additive 'lighter' compositing, cached glow sprite.
 *
 * INTEGRATION: each agent UI includes this file then calls setExpression() from
 * its existing state handler. See the bottom of each *.html for the wiring.
 */
(function () {
  'use strict';

  // ── Agent style profiles ──────────────────────────────────────────────────
  // color is [r,g,b]. speed=spring pull, damp=velocity retention, turb=turbulence,
  // drift=idle orbit energy, flicker=glitch probability per frame, chaos=random bursts.
  const STYLES = {
    johnny:      { color: [231, 76, 60],  speed: 0.020, damp: 0.88, turb: 1.5, drift: 0.55, flicker: 0.10, chaos: false },
    reddington:  { color: [201, 162, 94], speed: 0.014, damp: 0.91, turb: 0.6, drift: 0.30, flicker: 0.0,  chaos: false },
    attenborough:{ color: [95, 168, 107], speed: 0.012, damp: 0.93, turb: 0.4, drift: 0.25, flicker: 0.0,  chaos: false },
    sheogorath:  { color: [125, 95, 255], speed: 0.022, damp: 0.86, turb: 2.2, drift: 0.70, flicker: 0.18, chaos: true  },
  };
  STYLES.silverhand = STYLES.johnny;          // solo Silverhand uses Johnny's profile
  STYLES.red = STYLES.reddington;
  STYLES.default = STYLES.reddington;

  // ── Expression parameters (parametric — no hardcoded coordinate tables) ────
  // browY: +down/-up.  browA: inner-brow angle (+up=quizzical, -down=angry).
  // eyeOpen: vertical scale.  mouthCurve: +smile/-frown.  mouthOpen: gap.
  // mouthW: width.  gaze:[x,y] pupil offset.  talk/shake/asym: animation flags.
  const EXPR = {
    listening: { browY:-0.05, browA: 0.05, eyeOpen:1.15, mouthCurve: 0.05, mouthOpen:0.02, mouthW:0.40, gaze:[0, 0.02] },
    speaking:  { browY: 0.00, browA: 0.00, eyeOpen:1.00, mouthCurve: 0.04, mouthOpen:0.14, mouthW:0.46, gaze:[0, 0.00], talk:true },
    grin:      { browY:-0.02, browA: 0.00, eyeOpen:0.85, mouthCurve: 0.42, mouthOpen:0.05, mouthW:0.54, gaze:[0, 0.00] },
    laugh:     { browY:-0.04, browA: 0.00, eyeOpen:0.18, mouthCurve: 0.50, mouthOpen:0.22, mouthW:0.56, gaze:[0, 0.00], shake:true },
    frown:     { browY: 0.05, browA:-0.12, eyeOpen:0.95, mouthCurve:-0.34, mouthOpen:0.03, mouthW:0.42, gaze:[0, 0.02] },
    angry:     { browY: 0.10, browA:-0.34, eyeOpen:0.75, mouthCurve:-0.20, mouthOpen:0.05, mouthW:0.40, gaze:[0, 0.00] },
    thinking:  { browY:-0.06, browA: 0.18, eyeOpen:1.00, mouthCurve:-0.02, mouthOpen:0.02, mouthW:0.34, gaze:[0.10,-0.12], asym:true },
  };
  // Aliases from the agents' richer emotion vocabularies → our 7 faces.
  const ALIAS = {
    smirk:'grin', amused:'grin', chuckle:'laugh', snort:'laugh',
    scoff:'frown', weary:'frown', sigh:'frown', displeased:'frown',
    intense:'angry', serious:'angry', stare:'angry', 'hard stare':'angry',
    considering:'thinking', neutral:'listening',
  };

  // Expressions that must hold ≥20s before dissolving (transient emotions).
  // speaking/listening are NOT here — they persist until the next state arrives.
  const MIN_HOLD = { grin:1, laugh:1, frown:1, angry:1, thinking:1 };
  const HOLD_MS = 20000;

  // ── Engine state ──────────────────────────────────────────────────────────
  let canvas, ctx, W = 0, H = 0, dpr = 1;
  let particles = [];
  let facePts = [];           // [{x,y,grp,oy}] current face target points (pixel space)
  let mode = 'free';          // 'free' | 'face'
  let curExpr = null;         // current expression name (normalized) or null
  let style = STYLES.default, curColor = STYLES.default.color.slice(), tgtColor = curColor.slice();
  let holdUntil = 0, pendingDissolve = false;
  let audio = 0;              // 0..1 external amplitude
  let sprite = null, spriteColorKey = '';
  let raf = 0, last = 0, t = 0;
  let cx = 0, cy = 0, scale = 0;
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ── Glow sprite (cached, retinted on colour change) ───────────────────────
  function buildSprite(rgb) {
    const key = rgb.map(Math.round).join(',');
    if (key === spriteColorKey && sprite) return;
    spriteColorKey = key;
    const s = 32, c = document.createElement('canvas'); c.width = c.height = s;
    const g = c.getContext('2d');
    const grad = g.createRadialGradient(s/2, s/2, 0, s/2, s/2, s/2);
    grad.addColorStop(0,   `rgba(${rgb[0]},${rgb[1]},${rgb[2]},1)`);
    grad.addColorStop(0.4, `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.55)`);
    grad.addColorStop(1,   `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0)`);
    g.fillStyle = grad; g.fillRect(0, 0, s, s);
    sprite = c;
  }

  // ── Face geometry builder ─────────────────────────────────────────────────
  // Parametric landmark groups → flat point list. grp: face/eye/brow/nose/mouth.
  // oy: mouth-open direction (-1 upper lip, +1 lower lip) so 'talk' can open it.
  function buildFace(name) {
    const p = EXPR[name] || EXPR.speaking;
    const pts = [];
    const ar = 0.82;                                  // face aspect (narrower than tall)
    const X = nx => cx + nx * scale * ar;
    const Y = ny => cy + ny * scale;

    // head silhouette (ellipse outline, slightly pointed chin)
    for (let i = 0; i < 150; i++) {
      const a = (i / 150) * Math.PI * 2;
      const chin = Math.sin(a) > 0 ? 1.06 : 1.0;      // elongate lower half a touch
      pts.push({ x: X(Math.cos(a) * 0.80), y: Y(Math.sin(a) * 0.98 * chin), grp: 'face', oy: 0 });
    }

    // eyes (almonds) — centre ±0.34, y -0.18
    const eo = p.eyeOpen;
    for (const side of [-1, 1]) {
      const ex = side * 0.34, ey = -0.18;
      for (let i = 0; i <= 24; i++) {
        const u = i / 24, a = Math.PI * u;            // 0..PI sweep
        const lid = Math.sin(a);
        pts.push({ x: X(ex - 0.13 + 0.26 * u), y: Y(ey - lid * 0.085 * eo), grp: 'eye', oy: 0 }); // upper
        pts.push({ x: X(ex - 0.13 + 0.26 * u), y: Y(ey + lid * 0.055 * eo), grp: 'eye', oy: 0 }); // lower
      }
      // pupil cluster (with gaze offset)
      for (let i = 0; i < 6; i++)
        pts.push({ x: X(ex + p.gaze[0]), y: Y(ey + p.gaze[1]), grp: 'eye', oy: 0 });
    }

    // eyebrows — angled arcs; asym raises the right brow (thinking)
    for (const side of [-1, 1]) {
      const ex = side * 0.34, by = -0.40 + p.browY;
      const tilt = (side === 1 && p.asym) ? p.browA + 0.10 : p.browA;
      for (let i = 0; i <= 12; i++) {
        const u = i / 12;
        // inner end lifts/drops by tilt; sign so inner = toward centre
        const inner = side < 0 ? (1 - u) : u;
        pts.push({ x: X(ex - 0.15 + 0.30 * u), y: Y(by - inner * tilt), grp: 'brow', oy: 0 });
      }
    }

    // nose — bridge + base
    for (let i = 0; i <= 12; i++)
      pts.push({ x: X(0 + p.gaze[0] * 0.4), y: Y(-0.05 + 0.22 * (i / 12)), grp: 'nose', oy: 0 });
    for (let i = 0; i <= 6; i++)
      pts.push({ x: X(-0.05 + 0.10 * (i / 6)), y: Y(0.18), grp: 'nose', oy: 0 });

    // mouth — quadratic lips around centre (0, 0.42)
    const mw = p.mouthW, my = 0.42, open = p.mouthOpen, curve = p.mouthCurve;
    for (let i = 0; i <= 40; i++) {
      const u = i / 40, x = (-0.5 + u) * 2 * mw;      // -mw..+mw
      const bend = curve * (1 - (2 * u - 1) * (2 * u - 1)); // parabola, peak mid
      pts.push({ x: X(x), y: Y(my - bend - open * 0.5), grp: 'mouth', oy: -1 }); // upper lip
      pts.push({ x: X(x), y: Y(my - bend + open * 0.5), grp: 'mouth', oy: +1 }); // lower lip
    }
    return pts;
  }

  // ── Particle init ─────────────────────────────────────────────────────────
  function makeParticles(count) {
    particles = [];
    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * W, y: Math.random() * H,
        vx: 0, vy: 0, targetX: 0, targetY: 0,
        size: 0.5 + Math.random() * 1.6,
        alpha: 0, baseAlpha: 0.35 + Math.random() * 0.55,
        // assignment metadata
        fpi: 0, jx: (Math.random() - 0.5) * 6, jy: (Math.random() - 0.5) * 6,
        grp: 'face', oy: 0,
        ang: Math.random() * Math.PI * 2, rad: 0, spin: (Math.random() - 0.5) * 0.0007,
        aura: false, seed: Math.random() * 1000,
      });
    }
  }

  // assign each particle a face point (or aura ring slot)
  function assignTargets() {
    const nAura = Math.floor(particles.length * 0.14);
    const fl = facePts.length || 1;
    for (let k = 0; k < particles.length; k++) {
      const a = particles[k];
      if (k < nAura) {
        a.aura = true;
        a.rad = scale * (1.15 + Math.random() * 0.75);
      } else {
        a.aura = false;
        const fp = facePts[(k - nAura) % fl];
        a.fpi = (k - nAura) % fl;
        a.grp = fp.grp; a.oy = fp.oy;
      }
    }
  }

  // ── Layout / resize ───────────────────────────────────────────────────────
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    W = canvas.clientWidth || window.innerWidth;
    H = canvas.clientHeight || window.innerHeight;
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cx = W * 0.5; cy = H * 0.46; scale = Math.min(W, H) * 0.34;
    if (mode === 'face' && curExpr) { facePts = buildFace(curExpr); assignTargets(); }
  }

  // ── Public: expression / style ────────────────────────────────────────────
  function normalize(name) {
    if (!name) return null;
    const n = String(name).toLowerCase();
    if (n === 'idle' || n === 'free') return null;
    return ALIAS[n] || (EXPR[n] ? n : (n === 'response' ? 'speaking' : null));
  }

  function setExpression(name, styleKey) {
    if (styleKey) setStyle(styleKey);
    const norm = normalize(name);
    const now = performance.now();
    if (!norm) { requestDissolve(now); return; }
    curExpr = norm;
    mode = 'face';
    facePts = buildFace(norm);
    assignTargets();
    pendingDissolve = false;
    holdUntil = MIN_HOLD[norm] ? now + HOLD_MS : now;   // emotions hold ≥20s
  }

  function requestDissolve(now) {
    now = now || performance.now();
    if (now < holdUntil) { pendingDissolve = true; return; } // defer until hold expires
    mode = 'free'; curExpr = null; pendingDissolve = false;
  }

  function setStyle(key) {
    const s = STYLES[String(key).toLowerCase()] || STYLES.default;
    style = s; tgtColor = s.color.slice();
  }

  function setAudioLevel(v) { audio = Math.max(0, Math.min(1, v || 0)); }

  // ── Frame ─────────────────────────────────────────────────────────────────
  function step(now) {
    raf = requestAnimationFrame(step);
    const dt = Math.min(2, (now - last) / 16.67 || 1); last = now; t += dt;

    if (pendingDissolve && now >= holdUntil) requestDissolve(now);

    // lerp colour toward target, retint sprite
    for (let i = 0; i < 3; i++) curColor[i] += (tgtColor[i] - curColor[i]) * 0.06;
    buildSprite(curColor);

    // trail fade (dark, page bg is near-black) → motion smear
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = 'rgba(8,8,10,0.22)';
    ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'lighter';

    const speakingPulse = curExpr === 'speaking' ? (audio || (0.5 + 0.5 * Math.sin(t * 0.35))) : 0;
    const talkOsc = Math.sin(t * 0.55) * (0.5 + speakingPulse);   // mouth open/close
    const chaos = style.chaos ? 1 : 0;

    for (let k = 0; k < particles.length; k++) {
      const a = particles[k];

      if (mode === 'face') {
        let tx, ty;
        if (a.aura) {
          a.ang += a.spin * dt * 16;
          tx = cx + Math.cos(a.ang) * a.rad;
          ty = cy + Math.sin(a.ang) * a.rad;
        } else {
          const fp = facePts[a.fpi] || facePts[0];
          tx = fp.x + a.jx; ty = fp.y + a.jy;
          if (a.grp === 'mouth' && curExpr === 'speaking') ty += a.oy * talkOsc * scale * 0.10;
          if (chaos) { tx += Math.sin(t * 0.2 + a.seed) * 3; ty += Math.cos(t * 0.17 + a.seed) * 3; }
        }
        const dx = tx - a.x, dy = ty - a.y;
        a.vx += dx * style.speed; a.vy += dy * style.speed;
        a.vx *= style.damp; a.vy *= style.damp;
        a.alpha += ((a.aura ? a.baseAlpha * 0.5 : a.baseAlpha) - a.alpha) * 0.05;
      } else {
        // freeform: turbulence + slow orbit around centre → digital mist
        const to = style.turb;
        a.vx += Math.sin(a.y * 0.012 + t * 0.03 * to + a.seed) * 0.06 * to;
        a.vy += Math.cos(a.x * 0.012 + t * 0.025 * to + a.seed) * 0.06 * to;
        const ox = a.x - cx, oy2 = a.y - cy;
        a.vx += -oy2 * 0.00012 * style.drift;          // gentle orbit
        a.vy += ox * 0.00012 * style.drift;
        a.vx *= 0.95; a.vy *= 0.95;
        a.alpha += (a.baseAlpha * 0.6 - a.alpha) * 0.03;
      }

      // glitch flicker (johnny/sheogorath)
      if (style.flicker && Math.random() < style.flicker * 0.02) {
        a.x += (Math.random() - 0.5) * 8; a.alpha *= 0.4;
      }

      a.x += a.vx * dt; a.y += a.vy * dt;

      // wrap in freeform so the mist fills the frame
      if (mode === 'free') {
        if (a.x < -20) a.x = W + 20; else if (a.x > W + 20) a.x = -20;
        if (a.y < -20) a.y = H + 20; else if (a.y > H + 20) a.y = -20;
      }

      const r = a.size * (2.4 + speakingPulse * 1.2);
      ctx.globalAlpha = Math.max(0, Math.min(1, a.alpha));
      ctx.drawImage(sprite, a.x - r, a.y - r, r * 2, r * 2);
    }
    ctx.globalAlpha = 1;
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  function init(opts) {
    opts = opts || {};
    canvas = opts.canvas || document.getElementById('particle-face');
    if (!canvas) { console.warn('[ParticleFace] no canvas'); return api; }
    ctx = canvas.getContext('2d');
    if (opts.style) setStyle(opts.style);
    let count = opts.count || 2600;
    if (reduce) count = Math.min(count, 1200);
    count = Math.max(1000, Math.min(5000, count));
    resize();
    makeParticles(count);
    buildSprite(curColor);
    window.addEventListener('resize', resize);
    last = performance.now();
    raf = requestAnimationFrame(step);
    return api;
  }
  function stop() { cancelAnimationFrame(raf); raf = 0; }

  const api = { init, setExpression, setStyle, setAudioLevel, stop };
  window.ParticleFace = api;
})();
