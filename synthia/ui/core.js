/* Synthia 3D Neon Core
   idle / thinking / acting : প্রথম কোডের মতো কণার গোলক + গ্লো + ঘূর্ণি রিং
   listening               : মাঝখান জুড়ে ভাসমান ভয়েস ওয়েভ
   speaking                : স্পিকার ওয়েভ (ইকুয়ালাইজার বার + আর্ক) */
(function () {
  const canvas = document.getElementById("core");
  const ctx = canvas.getContext("2d");
  const stage = document.getElementById("stage");
  const cardsL = document.getElementById("cardsLeft");
  const cardsR = document.getElementById("cardsRight");

  const STATES = {
    idle:      { c: [46, 242, 208],  speed: 0.0025, pulse: 0.03, label: "READY" },
    listening: { c: [52, 235, 155],  speed: 0.007,  pulse: 0.11, label: "LISTENING" },
    thinking:  { c: [167, 139, 250], speed: 0.009,  pulse: 0.10, label: "THINKING" },
    acting:    { c: [56, 189, 248],  speed: 0.014,  pulse: 0.14, label: "ACTING" },
    speaking:  { c: [45, 226, 255],  speed: 0.008,  pulse: 0.13, label: "SPEAKING" },
    confirm:   { c: [251, 90, 107],  speed: 0.003,  pulse: 0.12, label: "AWAITING APPROVAL" },
    error:     { c: [251, 191, 36],  speed: 0.004,  pulse: 0.05, label: "ERROR" },
  };

  let state = "idle", theme = "neon";
  let col = [...STATES.idle.c];
  let rot = 0, t = 0, W = 0, H = 0, dpr = 1, remPx = 10, insetL = 0, insetR = 0;
  let audioLevel = 0, targetLevel = 0, hoverOrb = false;
  let G = { cx: 0, cy: 0, R: 60, x0: 0, x1: 0 };

  /* ---------- গোলক: প্রথম কোডের মতো ১১০০ কণা (গোল্ডেন-স্পাইরাল) ---------- */
  const N = 1100, pts = [], golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = golden * i;
    pts.push({ x: Math.cos(th) * r, y, z: Math.sin(th) * r, j: Math.random() * Math.PI * 2 });
  }

  /* ---------- থিম অনুযায়ী রঙ ---------- */
  function tc(c) {
    if (theme === "paper") return [c[0] * 0.5 | 0, c[1] * 0.55 | 0, c[2] * 0.55 | 0];
    if (theme === "aurora") return [c[0] * 0.65 + 167 * 0.35 | 0, c[1] * 0.65 + 139 * 0.35 | 0, c[2] * 0.65 + 250 * 0.35 | 0];
    return [c[0] | 0, c[1] | 0, c[2] | 0];
  }
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(0, Math.min(1, a)).toFixed(3)})`;
  const light = () => theme === "paper";

  /* ---------- সাইজ ও লেআউট ---------- */
  function resize() {
    dpr = window.devicePixelRatio || 1;
    const r = canvas.getBoundingClientRect();
    W = r.width; H = r.height;
    if (!W || !H) return;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    remPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 10;
    insetL = cardsL ? cardsL.offsetLeft + cardsL.offsetWidth : 0;
    insetR = cardsR ? W - cardsR.offsetLeft : 0;
    const topR = remPx * 5.4, botR = remPx * 8;
    const availW = Math.max(120, W - insetR - insetL);
    const availH = Math.max(120, H - topR - botR);
    const R = Math.min(availW * 0.22, availH * 0.31);
    G = { cx: insetL + availW / 2, cy: topR + availH * 0.46, R, x0: insetL + remPx * 2, x1: W - insetR - remPx * 2, W, H };
  }
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(resize);
    [canvas, cardsL, cardsR].forEach((el) => el && ro.observe(el));
  }
  window.addEventListener("resize", resize);
  resize();

  /* ---------- ইনপুট (অরবে ক্লিক = মাইক টগল) ---------- */
  const inOrb = (e, k) => {
    const rect = canvas.getBoundingClientRect();
    return Math.hypot(e.clientX - rect.left - G.cx, e.clientY - rect.top - G.cy) <= G.R * k;
  };
  canvas.addEventListener("mousemove", (e) => { hoverOrb = inOrb(e, 1.1); canvas.style.cursor = hoverOrb ? "pointer" : "default"; });
  canvas.addEventListener("mouseleave", () => { hoverOrb = false; canvas.style.cursor = "default"; });
  canvas.addEventListener("click", (e) => { if (inOrb(e, 1.25)) window.dispatchEvent(new CustomEvent("core-orb-click")); });

  /* ---------- দৃশ্য উপাদান ---------- */
  function drawGrid(c) {
    const horizon = G.cy + G.R * 1.55, bottom = H;
    if (horizon > bottom - 4) return;
    ctx.save();
    ctx.strokeStyle = rgba(c, light() ? 0.14 : 0.09);
    ctx.lineWidth = 1;
    for (let i = -16; i <= 16; i++) {
      ctx.beginPath(); ctx.moveTo(G.cx + i * remPx * 1.6, horizon);
      ctx.lineTo(G.cx + i * remPx * 12, bottom); ctx.stroke();
    }
    const off = (t * 0.5) % 1;
    for (let k = 0; k < 8; k++) {
      const p = (k + off) / 8, y = horizon + (bottom - horizon) * p * p;
      ctx.globalAlpha = p * 0.9;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }
    ctx.restore();
  }

  /* মাঝের আইকন: প্রথম কোডের হুবহু — গ্লো + কণার গোলক + অরবিট রিং */
  function drawOrb(c, S, dim) {
    const { cx, cy, R } = G;
    ctx.save();
    ctx.globalAlpha = dim;
    if (hoverOrb && state === "idle") {
      ctx.strokeStyle = rgba(c, 0.28); ctx.lineWidth = 1.8;
      ctx.beginPath(); ctx.arc(cx, cy, R * 0.68, 0, Math.PI * 2); ctx.stroke();
    }
    // কোর গ্লো
    const boost = 1 + audioLevel * 0.55 + (hoverOrb ? 0.08 : 0);
    const pulse = (1 + Math.sin(t * 3) * S.pulse) * boost;
    const gr = R * 0.58 * pulse;
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, gr);
    g.addColorStop(0, light() ? rgba(c, 0.9) : "rgba(255,255,255,0.96)");
    g.addColorStop(0.16, rgba(c, 0.92));
    g.addColorStop(1, rgba(c, 0));
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, gr, 0, Math.PI * 2); ctx.fill();

    // কণার গোলক
    const cr = Math.cos(rot), sr = Math.sin(rot);
    const tilt = 0.35, ct = Math.cos(tilt), st = Math.sin(tilt);
    const px0 = Math.max(1, remPx / 10);
    for (const p of pts) {
      const wob = (1 + Math.sin(t * 2 + p.j) * S.pulse * 0.5) * (1 + audioLevel * 0.22 * Math.sin(t * 8 + p.j));
      let x = p.x * cr - p.z * sr, z = p.x * sr + p.z * cr, y = p.y;
      const y2 = y * ct - z * st; z = y * st + z * ct; y = y2;
      const persp = 2.4 / (2.4 + z);
      const px = cx + x * R * wob * persp, py = cy + y * R * wob * persp;
      const a = 0.15 + (1 - (z + 1) / 2) * 0.78;
      const sz = (0.6 + persp * 0.95) * px0;
      ctx.fillStyle = rgba(c, a);
      ctx.fillRect(px, py, sz, sz);
    }
    // অরবিট রিং
    ctx.strokeStyle = rgba(c, 0.28); ctx.lineWidth = 1;
    for (let k = 0; k < 2; k++) {
      ctx.beginPath();
      ctx.ellipse(cx, cy, R * (1.25 + k * 0.18), R * (0.32 + k * 0.05), rot * (k ? -1 : 1) * 0.5, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  const eff = (base, wob) => Math.max(audioLevel, base + wob * Math.sin(t * 5));
  const env = (u, p) => Math.pow(Math.max(0, Math.sin(Math.PI * u)), p);

  /* listening: মাঝখান জুড়ে ভাসমান ভয়েস ওয়েভ */
  function drawVoiceWaves(c) {
    const lv = eff(0.16, 0.06);
    const { cy, x0, x1 } = G, span = x1 - x0;
    if (span < 40) return;
    const cols = [c, tc([56, 189, 248]), tc([167, 139, 250]), c, tc([56, 189, 248])];
    ctx.save();
    if (!light()) ctx.globalCompositeOperation = "lighter";
    for (let k = 0; k < 5; k++) {
      const amp = H * (0.04 + 0.1 * lv) * (1 - k * 0.13);
      const freq = 2.2 + k * 0.75, sp = 1.5 + k * 0.45, drift = Math.sin(t * 0.9 + k) * 0.5;
      ctx.beginPath();
      for (let s = 0; s <= 90; s++) {
        const u = s / 90, x = x0 + u * span;
        const y = cy + Math.sin(u * Math.PI * freq + t * sp + k * 1.3) * amp * env(u, 1.3) * (0.65 + 0.35 * Math.sin(t * 2 + k + u * 4)) + drift * amp * 0.25 * env(u, 1);
        s ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      const gr = ctx.createLinearGradient(x0, 0, x1, 0);
      gr.addColorStop(0, rgba(cols[k], 0)); gr.addColorStop(0.2, rgba(cols[k], 0.85 - k * 0.12));
      gr.addColorStop(0.8, rgba(cols[k], 0.85 - k * 0.12)); gr.addColorStop(1, rgba(cols[k], 0));
      ctx.strokeStyle = gr; ctx.lineWidth = 2.4 - k * 0.3;
      if (!light()) { ctx.shadowColor = rgba(cols[k], 0.8); ctx.shadowBlur = 10; }
      ctx.stroke();
    }
    ctx.restore();
  }

  /* speaking: স্পিকার ওয়েভ — ইকুয়ালাইজার বার + দুই পাশে সাউন্ড আর্ক */
  function drawSpeaker(c) {
    const lv = eff(0.34, 0.12);
    const { cx, cy, R, x0, x1 } = G, span = x1 - x0;
    if (span < 40) return;
    const N = Math.max(24, Math.min(72, Math.round(span / (remPx * 1.2))));
    const step = span / N, bw = step * 0.55;
    ctx.save();
    if (!light()) ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < N; i++) {
      const u = i / (N - 1), x = x0 + step * (i + 0.5);
      const e = 0.15 + 0.85 * env(u, 1.1);
      const n = (Math.sin(t * 9 + i * 1.7) + Math.sin(t * 5.3 + i * 0.9 + 1.2) + Math.sin(t * 13 + i * 2.3) + 3) / 6;
      const h = H * (0.008 + 0.17 * lv * n * e);
      const bc = u < 0.5 ? c : tc([167, 139, 250]);
      const gr = ctx.createLinearGradient(0, cy - h, 0, cy + h);
      gr.addColorStop(0, rgba(bc, 0.2)); gr.addColorStop(0.5, rgba(bc, 0.95)); gr.addColorStop(1, rgba(bc, 0.2));
      ctx.fillStyle = gr;
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x - bw / 2, cy - h, bw, h * 2, bw / 2); else ctx.rect(x - bw / 2, cy - h, bw, h * 2);
      ctx.fill();
    }
    ctx.lineWidth = 2;
    for (const side of [1, -1]) {
      for (let w = 0; w < 3; w++) {
        const ph = (t * 0.9 + w / 3) % 1, r = R * (1.1 + ph * 1.5);
        ctx.strokeStyle = rgba(c, (1 - ph) * (0.25 + lv * 0.7));
        ctx.beginPath();
        const a0 = side > 0 ? -0.55 : Math.PI - 0.55, a1 = side > 0 ? 0.55 : Math.PI + 0.55;
        ctx.arc(cx, cy, r, a0, a1); ctx.stroke();
      }
    }
    ctx.restore();
  }

  function frame() {
    if (W && H) {
      const S = STATES[state] || STATES.idle;
      for (let i = 0; i < 3; i++) col[i] += (S.c[i] - col[i]) * 0.07;
      audioLevel += (targetLevel - audioLevel) * 0.25;
      targetLevel *= 0.9;
      rot += S.speed + audioLevel * 0.008;
      t += 0.016;
      ctx.clearRect(0, 0, W, H);
      const c = tc(col), waveMode = state === "listening" || state === "speaking";
      drawGrid(c);
      drawOrb(c, S, waveMode ? 0.5 : 1);
      if (state === "listening") drawVoiceWaves(c);
      else if (state === "speaking") drawSpeaker(c);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  window.Core = {
    setState(s) {
      state = STATES[s] ? s : "idle";
      const el = document.getElementById("coreState");
      if (el) el.textContent = STATES[state].label;
    },
    setLevel(lv) { targetLevel = Math.max(0, Math.min(1, lv || 0)); },
    setTheme(n) { theme = n || "neon"; },
    relayout: resize,
    center() { return { cx: G.cx, cy: G.cy, R: G.R }; },
    get state() { return state; },
  };
})();
