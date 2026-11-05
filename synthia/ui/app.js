/* Synthia Command Bridge — UI লজিক (v0.2 ওভারহল) */
(() => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const setText = (sel, txt) => { const el = $(sel); if (el) el.textContent = txt; };
  const on = (sel, ev, fn) => { const el = typeof sel === "string" ? $(sel) : sel; if (el) el.addEventListener(ev, fn); };
  const LS = {
    get(k, d) { try { const v = localStorage.getItem("synthia." + k); return v == null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem("synthia." + k, JSON.stringify(v)); } catch (_) {} },
    del(k) { try { localStorage.removeItem("synthia." + k); } catch (_) {} },
    keys(prefix) { try { return Object.keys(localStorage).filter((x) => x.startsWith("synthia." + prefix)).map((x) => x.slice(8)); } catch (_) { return []; } },
  };
  const rootPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 10;

  const TOKEN = new URLSearchParams(location.search).get("token") || "";
  let ws = null, brain = null, signals = 0, stepNo = 0, typingEl = null, lastSignal = "";
  const stepEls = {};
  const stats = { tasks: 0, tools: 0, ok: 0, fail: 0, ms: 0, voice: 0 };
  const lanes = {};

  /* ================= Helper Squad ================= */
  const SQUAD = [
    { id: "files",    name: "File",     role: "Files",    ico: "📁", c: "amber" },
    { id: "system",   name: "System",   role: "PC control",         ico: "🛡️", c: "blue" },
    { id: "web",      name: "Browser",  role: "Web",         ico: "🧭", c: "orange" },
    { id: "research", name: "Research", role: "Search",      ico: "🔎", c: "violet" },
    { id: "voice",    name: "Voice",    role: "Speech",    ico: "🎙️", c: "pink" },
    { id: "media",    name: "Studio",   role: "Media",              ico: "🎬", c: "cyan" },
    { id: "remote",   name: "Remote",   role: "Telegram", ico: "📡", c: "green" },
  ];
  const TOOL_SQUAD = { web_search: "research", read_webpage: "research" };
  let toolCat = {}, squadReady = {};

  function renderSquad(skills) {
    toolCat = {};
    Object.entries(skills || {}).forEach(([cat, tools]) => tools.forEach((t) => (toolCat[t] = TOOL_SQUAD[t] || cat)));
    const counts = {};
    Object.values(toolCat).forEach((c) => (counts[c] = (counts[c] || 0) + 1));
    const box = $("#squad");
    if (!box) return;
    box.innerHTML = "";
    let ready = 0;
    SQUAD.forEach((a) => {
      const ok = !!counts[a.id];
      squadReady[a.id] = ok;
      if (ok) ready++;
      const el = document.createElement("div");
      el.className = `agent ag-${a.c} ${ok ? "ready" : "soon-agent"}`;
      el.id = "ag-" + a.id;
      el.title = `${a.name} — ${a.role}`;
      el.innerHTML = `<span class="ico">${a.ico}</span><div class="c-txt"><b>${a.name}<em>${a.role}</em></b><span class="st">${ok ? "Ready" : "Soon"}</span></div><span class="num">${counts[a.id] || 0}</span>`;
      box.appendChild(el);
    });
    setText("#squadReady", `● ${ready} Ready`);
    attachPair(box, ".agent", "squad");
    renderSquadGrid();
    renderLanes();
    requestAnimationFrame(() => drawLinks());
  }

  function squadBusy(tool, busy) {
    const cat = toolCat[tool] || (tool === "set_voice_options" ? "voice" : null);
    if (!cat) return;
    const el = document.getElementById("ag-" + cat);
    if (el) {
      el.classList.toggle("busy", busy);
      const st = el.querySelector(".st");
      if (st) st.textContent = busy ? "Working" : "Ready";
    }
    lanes[cat] = { ...(lanes[cat] || {}), busy, tool };
    renderLanes();
    drawLinks(busy ? cat : null);
  }

  /* ================= কার্ড → কোর সংযোগ (রেফারেন্সের মতো সাজানো রেখা) =================
     বাম: প্রতিটি কার্ড থেকে সোজা রেখা → একটাই উল্লম্ব বাস লাইন
     ডান: ছোট সোজা রেখা → কোরের দিকে তির্যক রেখা; কার্ডের কিনারায় রঙিন বিন্দু */
  let linkRaf = 0;
  function drawLinks(hotCat) {
    cancelAnimationFrame(linkRaf);
    linkRaf = requestAnimationFrame(() => {
      const svg = $("#links"), stageEl = $("#stage");
      if (!svg || !stageEl) return;
      const sr = stageEl.getBoundingClientRect(), rp = rootPx();
      const ctr = window.Core && window.Core.center ? window.Core.center() : { cx: sr.width / 2, cy: sr.height * 0.47, R: sr.height * 0.25 };
      const GAP_R = 1.18;   // গোলক ও রেখার শেষ বিন্দুর মাঝে অল্প ফাঁক (গোলকের ব্যাসার্ধের গুণিতক)
      const ring = ctr.R * 1.5, dotR = rp * 0.32;
      const acOf = (el) => (getComputedStyle(el).getPropertyValue("--ac") || "46,242,208").trim();
      const node = (x, y, ac, hot) => `<circle cx="${x}" cy="${y}" r="${hot ? dotR * 1.35 : dotR}" fill="rgb(${ac})"/>`;
      let html = "";

      const L = $$("#cardsLeft .card");
      if (L.length) {
        const pts = L.map((el) => { const r = el.getBoundingClientRect(); return { x: r.right - sr.left, y: r.top - sr.top + r.height / 2, ac: acOf(el) }; });
        const edge = Math.max(...pts.map((q) => q.x));
        const busX = Math.min(Math.max(edge + rp * 3, edge + (ctr.cx - ring - edge) * 0.72), ctr.cx - ctr.R * 1.2);
        const y0 = Math.min(ctr.cy, ...pts.map((q) => q.y)), y1 = Math.max(ctr.cy, ...pts.map((q) => q.y));
        const coreX = ctr.cx - ctr.R * GAP_R;
        pts.forEach((q) => { html += `<path d="M${q.x},${q.y} H${busX}" style="stroke:rgba(${q.ac},0.6)"/>` + node(q.x, q.y, q.ac, false); });
        html += `<path d="M${busX},${y0} V${y1}" style="stroke:rgba(var(--c-teal),0.5)"/>`;
        // বাস → কোর (মূল সংযোগ)
        html += `<path d="M${busX},${ctr.cy} H${coreX}" style="stroke:rgba(var(--c-teal),0.75)"/>` + node(busX, ctr.cy, "var(--c-teal)", false) + node(coreX, ctr.cy, "var(--c-teal)", true);
      }

      const R = $$("#cardsRight .agent");
      if (R.length) {
        const pts = R.map((el) => {
          const r = el.getBoundingClientRect();
          return { x: r.left - sr.left, y: r.top - sr.top + r.height / 2, ac: acOf(el), id: el.id, soon: el.classList.contains("soon-agent") };
        });
        const edge = Math.min(...pts.map((q) => q.x));
        const stub = Math.max(rp * 2.5, (edge - (ctr.cx + ring)) * 0.2);
        const maxDy = Math.max(1, ...pts.map((q) => Math.abs(q.y - ctr.cy)));
        pts.forEach((q) => {
          const th = ((q.y - ctr.cy) / maxDy) * 0.8;          // গোলকের গায়ে ছড়ানো শেষ বিন্দু
          const ex = ctr.cx + Math.cos(th) * ctr.R * GAP_R, ey = ctr.cy + Math.sin(th) * ctr.R * GAP_R;
          const hot = !!hotCat && q.id === "ag-" + hotCat;
          const style = hot ? `stroke:rgb(${q.ac})` : `stroke:rgba(${q.ac},${q.soon ? 0.28 : 0.6})`;
          html += `<path class="${hot ? "hot" : ""}" d="M${q.x},${q.y} H${q.x - stub} L${ex},${ey}" style="${style}"/>`
               + node(q.x, q.y, q.ac, hot) + `<circle cx="${ex}" cy="${ey}" r="${dotR * 0.8}" fill="rgb(${q.ac})" opacity="${q.soon ? 0.3 : 0.9}"/>`;
        });
      }
      svg.innerHTML = html;
    });
  }
  window.addEventListener("resize", () => drawLinks());
  if (window.ResizeObserver && $("#stage")) new ResizeObserver(() => drawLinks()).observe($("#stage"));

  /* ================= টেনে বড়-ছোট করা সেকশন (Splitters) ================= */
  const SPLITS = {
    colLeft:       { axis: "x", el: "#colLeft",       dir: 1,  min: 15, max: 42 },
    colRight:      { axis: "x", el: "#colRight",      dir: -1, min: 20, max: 62 },
    leftTop:       { axis: "y", el: "#secTelemetry",  dir: 1,  min: 7,  max: 30 },
    leftBot:       { axis: "y", el: "#secQa",         dir: -1, min: 8,  max: 45 },
    centerMid:     { axis: "y", el: "#secLedger",     dir: -1, min: 6,  max: 70, reserve: 16 },
    rightComposer: { axis: "y", el: "#secComposer",   dir: -1, min: 7,  max: 40, reserve: 14 },
    stageLeft:     { axis: "x", el: "#cardsLeft",     dir: 1,  min: 14, max: 44, cssVar: "--cl-w" },
    stageRight:    { axis: "x", el: "#cardsRight",    dir: -1, min: 14, max: 44, cssVar: "--cr-w" },
  };
  const applySize = (name, rem) => {
    const c = SPLITS[name], el = $(c.el);
    if (!el) return;
    if (c.cssVar) $("#stage").style.setProperty(c.cssVar, rem + "rem");
    else el.style.flex = `0 0 ${rem}rem`;
  };
  const resetSize = (name) => {
    const c = SPLITS[name], el = $(c.el);
    if (c.cssVar) $("#stage").style.removeProperty(c.cssVar);
    else if (el) el.style.flex = "";
  };
  function layoutChanged() { window.Core && window.Core.relayout && window.Core.relayout(); drawLinks(); }

  function bindSingle(handle) {
    const name = handle.dataset.split, c = SPLITS[name];
    if (!c) return;
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      const el = $(c.el), rp = rootPx();
      const rect = el.getBoundingClientRect();
      const startRem = (c.axis === "x" ? rect.width : rect.height) / rp;
      const start = c.axis === "x" ? e.clientX : e.clientY;
      const parent = el.parentElement.getBoundingClientRect();
      const parentRem = (c.axis === "x" ? parent.width : parent.height) / rp;
      const max = Math.min(c.max, parentRem - (c.reserve || 30));
      handle.setPointerCapture(e.pointerId);
      document.body.classList.add("dragging", "drag-" + c.axis);
      const move = (ev) => {
        const d = (((c.axis === "x" ? ev.clientX : ev.clientY) - start) / rp) * c.dir;
        const rem = Math.round(Math.min(max, Math.max(c.min, startRem + d)) * 10) / 10;
        applySize(name, rem); LS.set("size." + name, rem);
        layoutChanged();
      };
      const up = () => {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        document.body.classList.remove("dragging", "drag-x", "drag-y");
        layoutChanged();
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", up);
    });
    handle.addEventListener("dblclick", () => { LS.del("size." + name); resetSize(name); layoutChanged(); });
  }

  /* পাশাপাশি আইটেমের মাঝের হ্যান্ডেল (বাম কার্ড, ডান Squad কার্ড) */
  function attachPair(container, itemSel, key) {
    if (!container) return;
    container.querySelectorAll(":scope > .card-split").forEach((h) => h.remove());
    const items = Array.from(container.querySelectorAll(":scope > " + itemSel));
    items.forEach((it, i) => {
      if (!i) return;
      const h = document.createElement("div");
      h.className = "card-split";
      h.title = "টেনে বড়-ছোট করুন (ডাবল-ক্লিক = রিসেট)";
      container.insertBefore(h, it);
      h.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        const list = Array.from(container.querySelectorAll(":scope > " + itemSel));
        const prev = h.previousElementSibling, next = h.nextElementSibling;
        list.forEach((x) => (x.style.flex = `${x.getBoundingClientRect().height} 1 0px`));
        const a = prev.getBoundingClientRect().height, b = next.getBoundingClientRect().height, total = a + b;
        const min = rootPx() * 2.8, start = e.clientY;
        h.setPointerCapture(e.pointerId);
        document.body.classList.add("dragging", "drag-y");
        const move = (ev) => {
          const na = Math.min(total - min, Math.max(min, a + ev.clientY - start));
          prev.style.flex = `${na} 1 0px`; next.style.flex = `${total - na} 1 0px`;
          drawLinks();
        };
        const up = () => {
          h.removeEventListener("pointermove", move); h.removeEventListener("pointerup", up); h.removeEventListener("pointercancel", up);
          document.body.classList.remove("dragging", "drag-y");
          const g = list.map((x) => parseFloat(x.style.flex) || 1), sum = g.reduce((p, q) => p + q, 0);
          LS.set("pair." + key, g.map((x) => x / sum));
          drawLinks();
        };
        h.addEventListener("pointermove", move); h.addEventListener("pointerup", up); h.addEventListener("pointercancel", up);
      });
      h.addEventListener("dblclick", () => { items.forEach((x) => (x.style.flex = "")); LS.del("pair." + key); drawLinks(); });
    });
    const saved = LS.get("pair." + key, null);
    if (Array.isArray(saved) && saved.length === items.length) items.forEach((x, i) => (x.style.flex = `${saved[i] * 100} 1 0px`));
  }

  function initLayout() {
    Object.keys(SPLITS).forEach((n) => { const v = LS.get("size." + n, null); if (v) applySize(n, v); });
    $$("[data-split]").forEach(bindSingle);
    attachPair($("#cardsLeft"), ".card", "cardsLeft");
    on("#btnResetLayout", "click", () => {
      LS.keys("size.").forEach((k) => LS.del(k));
      LS.keys("pair.").forEach((k) => LS.del(k));
      Object.keys(SPLITS).forEach(resetSize);
      $$("#cardsLeft .card, #cardsRight .agent").forEach((x) => (x.style.flex = ""));
      layoutChanged();
      signal("info", "layout", "সব সেকশনের সাইজ রিসেট হয়েছে");
    });
  }

  /* ================= থিম ================= */
  function applyTheme(name) {
    if (!["neon", "aurora", "paper"].includes(name)) name = "neon";
    document.body.dataset.theme = name;
    $$("#themeSeg button").forEach((b) => b.classList.toggle("active", b.dataset.theme === name));
    window.Core && window.Core.setTheme(name);
    LS.set("theme", name);
  }
  $$("#themeSeg button").forEach((b) => b.addEventListener("click", () => applyTheme(b.dataset.theme)));
  applyTheme(LS.get("theme", "neon"));

  /* ================= WebSocket ================= */
  function connect() {
    ws = new WebSocket(`ws://${location.host}/ws?token=${encodeURIComponent(TOKEN)}`);
    ws.onopen = () => { signal("info", "connected", "Synthia core-এর সাথে সংযুক্ত"); setCore("idle", idleText(), idleHint()); };
    ws.onclose = (e) => {
      if (e.code === 4401) { signal("error", "auth", "Invalid token — Synthia নতুন করে চালু করুন"); return; }
      setCore("error", "Core থেকে বিচ্ছিন্ন — আবার সংযোগের চেষ্টা…", "");
      setTimeout(connect, 2000);
    };
    ws.onmessage = (m) => { try { handle(JSON.parse(m.data)); } catch (err) { console.error("UI event error", err); } };
  }
  const send = (obj) => ws && ws.readyState === 1 && ws.send(JSON.stringify(obj));

  function handle(ev) {
    switch (ev.type) {
      case "state": applyState(ev); break;
      case "brain_state": applyBrain(ev); break;
      case "telemetry": telemetry(ev); break;
      case "chat": chat(ev); break;
      case "status": status(ev); break;
      case "task_start": taskStart(ev); break;
      case "tool_start": toolStart(ev); break;
      case "tool_end": toolEnd(ev); break;
      case "task_end": setText("#taskId", "done · " + ev.task_id); stats.tasks++; renderAnalytics(); break;
      case "signal": signal(ev.level || "info", ev.title || "signal", ev.text || ""); break;
      case "model_active":
        if (brain) { brain.active = ev.id; renderModels(); updateModelChips(); }
        else setText("#activeModel", ev.label);
        signal("info", "model", "Brain: " + ev.label); break;
      case "confirm_request": openConfirm(ev); break;
      case "confirm_resolved": closeConfirm(ev); break;
      case "voice_state": applyVoice(ev); break;
      case "voice_level": window.Core && window.Core.setLevel(ev.level); break;
      case "audio_play": playVoiceAudio(ev); break;
      case "audio_stop": stopVoiceAudio(); break;
    }
  }

  function applyState(s) {
    setText("#ver", "v" + s.version);
    setText("#cSkills", s.tool_count);
    setText("#cSkillsSub", Object.keys(s.skills || {}).length + " categories");
    setText("#cMem", s.memory_count);
    window.__skills = s.skills || {};
    window.__startup = !!s.startup_enabled;
    renderSquad(s.skills);
    if (s.brain) applyBrain(s.brain);
    renderMemories(s.memories, s.memory_count);
    if (s.voice) applyVoice(s.voice);
    (s.pending_confirms || []).forEach(openConfirm);
  }

  /* ================= মডেল / ব্রেন ================= */
  const providerOf = (m) => m.provider || (m.local ? "ollama" : String(m.label || "cloud").split(/[\s·(]/)[0].toLowerCase());
  function updateModelChips() {
    if (!brain) return;
    const id = brain.mode === "manual" ? brain.manual_model : brain.active;
    const act = brain.models.find((m) => m.id === id) || brain.models.find((m) => m.id === brain.active);
    if (act) {
      setText("#activeProviderModel", `${providerOf(act)} · ${act.model}`);
      setText("#activeModel", (brain.mode === "manual" ? "📌 " : "") + act.model);
    }
    const auto = brain.mode !== "manual";
    setText("#modeLabel", auto ? "Auto-Run" : "Manual Lock");
    const b = $("#btnAutoMode");
    if (b) b.classList.toggle("active", auto);
    const md = $("#modeDot");
    if (md) md.className = "dot " + (auto ? "dot-ok" : "dot-warn");
  }
  function applyBrain(b) {
    brain = b;
    $$("#modeSeg button").forEach((x) => x.classList.toggle("active", x.dataset.mode === b.mode));
    const avail = b.models.filter((m) => m.available).length;
    setText("#cModels", `${avail}/${b.models.length}`);
    updateModelChips();
    renderModels();
  }
  function renderModels() {
    if (!brain) return;
    const box = $("#modelList");
    if (!box) return;
    box.innerHTML = "";
    brain.models.forEach((m) => {
      const selected = brain.mode === "manual" ? m.id === brain.manual_model : m.id === brain.active;
      const el = document.createElement("div");
      el.className = `model ${selected ? "selected" : ""} ${m.available ? "" : "off"}`;
      const badges = [
        m.local ? '<span class="badge local">LOCAL · Offline</span>' : '<span class="badge">CLOUD</span>',
        m.available ? '<span class="badge ok">Ready</span>' : '<span class="badge warn">No API key</span>',
        m.vision ? '<span class="badge">👁 Vision</span>' : "",
        m.cooldown ? `<span class="badge warn">Limit · ${m.cooldown}s</span>` : "",
        m.id === brain.active ? '<span class="badge active">ACTIVE</span>' : "",
      ].join("");
      el.innerHTML = `<div><b>${m.label}</b><br><small>${m.model} · priority ${m.priority}</small></div><div class="badges">${badges}</div>`;
      el.addEventListener("click", () => {
        if (!m.available) { signal("warn", "model", `${m.label}: .env ফাইলে API key দিন`); return; }
        send({ type: "set_model", mode: "manual", model_id: m.id });
      });
      box.appendChild(el);
    });
  }
  function renderModelDrop() {
    const menu = $("#modelDropMenu");
    if (!menu || !brain) return;
    menu.innerHTML = "";
    brain.models.forEach((m) => {
      const sel = brain.mode === "manual" ? m.id === brain.manual_model : m.id === brain.active;
      const b = document.createElement("button");
      b.className = (sel ? "sel " : "") + (m.available ? "" : "off");
      b.innerHTML = `<span class="dot ${m.available ? "dot-ok" : ""}"></span><span>${m.model}</span><small>${m.local ? "local" : "cloud"}</small>`;
      b.addEventListener("click", () => {
        menu.hidden = true;
        if (!m.available) { signal("warn", "model", `${m.label}: .env ফাইলে API key দিন`); return; }
        send({ type: "set_model", mode: "manual", model_id: m.id });
      });
      menu.appendChild(b);
    });
  }
  on("#btnModelDrop", "click", (e) => { e.stopPropagation(); renderModelDrop(); const m = $("#modelDropMenu"); m.hidden = !m.hidden; });
  document.addEventListener("click", () => { const m = $("#modelDropMenu"); if (m) m.hidden = true; });
  on("#btnAutoMode", "click", () => {
    if (!brain) return;
    if (brain.mode === "manual") send({ type: "set_model", mode: "auto", model_id: brain.manual_model });
    else send({ type: "set_model", mode: "manual", model_id: brain.active });
  });
  on("#chipActive", "click", () => ($("#modelsWrap").hidden = false));
  $$("#modeSeg button").forEach((b) => b.addEventListener("click", () => send({ type: "set_model", mode: b.dataset.mode, model_id: brain && (brain.manual_model || brain.active) })));
  on("#btnModels", "click", () => ($("#modelsWrap").hidden = false));
  $$("[data-close]").forEach((b) => b.addEventListener("click", () => ($("#" + b.dataset.close).hidden = true)));

  /* ================= টেলিমেট্রি ================= */
  const setBar = (id, pct) => { const el = $(id); if (el) el.style.width = Math.min(100, Math.max(0, pct || 0)) + "%"; };
  function telemetry(t) {
    setBar("#barCpu", t.cpu); setText("#valCpu", Math.round(t.cpu) + "%");
    setBar("#barRam", t.ram_pct); setText("#valRam", `${t.ram_used_gb}/${t.ram_total_gb}G`);
    if (t.gpu) {
      setBar("#barGpu", t.gpu.util); setText("#valGpu", `${t.gpu.util}% ${t.gpu.temp_c}°`);
      setBar("#barVram", (t.gpu.vram_used_mb / t.gpu.vram_total_mb) * 100);
      setText("#valVram", `${(t.gpu.vram_used_mb / 1024).toFixed(1)}/${(t.gpu.vram_total_mb / 1024).toFixed(0)}G`);
    }
    if (t.disks && t.disks.length) {
      const free = t.disks.reduce((a, d) => a + d.free_gb, 0), total = t.disks.reduce((a, d) => a + d.total_gb, 0);
      setBar("#barDisk", 100 - (free / total) * 100); setText("#valDisk", `${free}G free`);
    }
    setText("#uptime", `Uptime ${t.uptime_h}h`);
    if (t.online !== undefined) {
      const d = $("#netDot");
      if (d) d.className = "dot " + (t.online ? "dot-ok" : "dot-warn");
      setText("#netText", t.online ? "Online · Cloud" : "Offline · Local");
    }
  }

  /* ================= চ্যাট ================= */
  function md(text) {
    let s = (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, l, c) => `<pre><code>${c}</code></pre>`);
    s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    s = s.replace(/(https?:\/\/[^\s<)]+)/g, '<a href="$1" target="_blank">$1</a>');
    s = s.replace(/^\s*[-*] /gm, "• ");
    return s.replace(/\n/g, "<br>");
  }
  function addMsg(role, text, extra = "") {
    const box = $("#chatView");
    const el = document.createElement("div");
    el.className = `msg ${role === "user" ? "user" : "bot"} ${extra}`;
    el.innerHTML = `<div class="who">${role === "user" ? "You" : "💠 Synthia"}</div><div class="bubble">${md(text)}</div>`;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }
  function showTyping(on_) {
    if (on_ && !typingEl) {
      typingEl = addMsg("assistant", "");
      typingEl.querySelector(".bubble").innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
    } else if (!on_ && typingEl) { typingEl.remove(); typingEl = null; }
  }
  function chat(ev) {
    if (ev.role === "user") {
      if (ev.source === "voice") { addMsg("user", `🎙️ ${ev.text}`); stats.voice++; renderAnalytics(); }
      else if (ev.source !== "ui") addMsg("user", `[${ev.source}] ${ev.text}`);
      return;
    }
    showTyping(false);
    addMsg("assistant", ev.text, ev.partial ? "partial" : "");
    if (!ev.partial) timeline("💠 " + ev.text.slice(0, 120));
  }

  /* ================= কোর স্ট্যাটাস ================= */
  const PERSONA = { female: { name: "Synthia", emo: "👩", label: "Female Voice" }, male: { name: "Jarvis", emo: "🤖", label: "Male Voice" } };
  let voiceState = { persona: "female", muted: false, mic_on: false, listening: false, speaking: false };
  let currentAudio = null, audioCtx = null, speakAnim = null, audioQueue = [];
  const isSpeakingNow = () => !!(voiceState.speaking || currentAudio || audioQueue.length);
  const idleText = () => (voiceState.mic_on ? "Ready · Mic On" : "Ready · Mic Off");
  const idleHint = () => (voiceState.mic_on ? "মাঝখানের অরব বা চ্যাটের 🎙️ বাটনে ক্লিক করে কথা বলুন" : "মাইক বন্ধ — কথা বলতে ওপরে Mic On করুন অথবা টাইপ করুন");

  function refreshPersona() {
    const p = PERSONA[voiceState.persona] || PERSONA.female;
    setText("#corePersona", `${p.emo} Active: ${p.name} (${p.label})`);
  }
  function setCore(state, text, sub) {
    window.Core && window.Core.setState(state);
    const st = $("#coreState");
    if (st) st.className = "st-state " + (state === "error" ? "err" : state === "confirm" ? "warn" : "ok");
    setText("#coreText", text);
    if (sub !== undefined) setText("#coreSubHint", sub);
    const dot = $("#coreDot");
    if (dot) dot.className = "dot " + (state === "idle" || state === "listening" ? "dot-ok" : state === "error" || state === "confirm" ? "dot-err" : "dot-warn");
    refreshPersona();
  }
  function status(ev) {
    if (ev.state === "listening") {
      setCore("listening", "🎙️ Listening Live…", "এখন বলুন · কথা শেষ হলে অটোমেটিক বুঝবে");
      showTyping(false);
    } else if (ev.state === "speaking") {
      setCore("speaking", "🔊 Speaking…", "থামাতে Crystal Core বা 🎙️ বাটনে ক্লিক করুন");
      showTyping(false);
    } else if (ev.state === "thinking") {
      const stepTxt = typeof ev.step === "number" ? `ধাপ ${ev.step}` : ev.step || "চিন্তা করছি…";
      setCore("thinking", "Thinking…", stepTxt);
      showTyping(true);
      const sb = $("#btnSend");
      if (sb) sb.disabled = false;
    } else if (ev.state === "acting") {
      setCore("acting", "Working: " + ev.tool, "টুল চালাচ্ছি…");
    } else {
      showTyping(false);
      // TTS চলার সময় 'idle' এলে Speaking ওভাররাইট হবে না
      if (isSpeakingNow()) return;
      if (voiceState.mic_on && voiceState.listening) setCore("listening", "🎙️ Listening Live…", "এখন বলুন");
      else setCore("idle", idleText(), idleHint());
    }
  }

  /* ================= ভয়েস ================= */
  function applyVoice(v) {
    voiceState = { ...voiceState, ...v };
    $$(".persona button[data-voice]").forEach((b) => b.classList.toggle("active", b.dataset.voice === voiceState.persona));
    const micOn = !!voiceState.mic_on;
    const listening = !!voiceState.listening;

    const micBtn = $("#btnMic");
    if (micBtn) {
      micBtn.classList.toggle("mic-live", listening);
      micBtn.textContent = listening ? "⏹️" : "🎙️";
      micBtn.title = listening ? "রেকর্ডিং থামাতে ক্লিক করুন" : "ক্লিক করে কথা বলুন (বাংলা / English)";
    }
    const modeBtn = $("#btnMicMode");
    if (modeBtn) {
      modeBtn.classList.toggle("on", micOn);
      setText("#micLabel", micOn ? "Mic: On" : "Mic: Off");
      modeBtn.title = micOn ? "মাইক্রোফোন অন — বন্ধ করতে ক্লিক করুন" : "মাইক্রোফোন বন্ধ — অন করতে ক্লিক করুন";
    }
    [$("#btnSpeak"), $("#btnMuteTop"), $("#btnSpeakTop2")].forEach((b) => {
      if (!b) return;
      b.textContent = (b.id === "btnMuteTop" ? (voiceState.muted ? "🔇 Unmute" : "🔊 Mute") : voiceState.muted ? "🔇" : "🔊");
      b.classList.toggle("muted-btn", !!voiceState.muted);
    });
    setText("#composerHint", `Mic: ${micOn ? (listening ? "Listening Live…" : "On") : "Off"} · বাংলা বললে বাংলায়, English বললে English-এ উত্তর · Kill: Ctrl+Shift+X`);

    const cs = window.Core && window.Core.state;
    if (listening && cs !== "listening" && !isSpeakingNow()) setCore("listening", "🎙️ Listening Live…", "এখন বলুন · কথা শেষ হলে অটোমেটিক বুঝবে");
    else if (!listening && cs === "listening") setCore("idle", idleText(), idleHint());
    else if (cs === "idle") setCore("idle", idleText(), idleHint());
    else refreshPersona();
    squadBusy("set_voice_options", !!(voiceState.listening || voiceState.speaking));
  }

  function stopVoiceAudio(notify = false) {
    if (speakAnim) { cancelAnimationFrame(speakAnim); speakAnim = null; }
    if (currentAudio) { try { currentAudio.pause(); currentAudio.src = ""; } catch (_) {} currentAudio = null; }
    if (!notify) audioQueue = [];
    if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (_) {} }
    window.Core && window.Core.setLevel(0);
    if (notify) send({ type: "audio_done" });
  }

  function playMp3(ev) {
    const audio = new Audio("data:audio/mpeg;base64," + ev.audio_b64);
    audio.playbackRate = ev.rate || 1.0;
    currentAudio = audio;
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const pumpRand = () => {
        if (currentAudio !== audio) return;
        window.Core && window.Core.setLevel(0.25 + Math.random() * 0.35);
        speakAnim = requestAnimationFrame(pumpRand);
      };
      if (audioCtx.state === "running") {
        const src = audioCtx.createMediaElementSource(audio);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        src.connect(analyser); analyser.connect(audioCtx.destination);
        const data = new Uint8Array(analyser.frequencyBinCount);
        const pump = () => {
          if (currentAudio !== audio) return;
          analyser.getByteFrequencyData(data);
          let sum = 0;
          for (let i = 0; i < 32; i++) sum += data[i];
          window.Core && window.Core.setLevel(Math.min(1, sum / (32 * 165)));
          speakAnim = requestAnimationFrame(pump);
        };
        speakAnim = requestAnimationFrame(pump);
      } else { audioCtx.resume().catch(() => {}); speakAnim = requestAnimationFrame(pumpRand); }
    } catch (_) {}
    const done = () => {
      if (currentAudio !== audio) return;
      currentAudio = null;
      if (audioQueue.length) { playMp3(audioQueue.shift()); return; }
      stopVoiceAudio(true);
    };
    audio.onended = done; audio.onerror = done;
    audio.play().catch(done);
  }

  function playVoiceAudio(ev) {
    // ev.append = true হলে আগের অডিও থামানো হয় না, লাইনে বসে (বাক্য-বাক্য স্ট্রিমিংয়ের জন্য)
    if (ev.append && ev.mode === "mp3" && currentAudio) { audioQueue.push(ev); return; }
    stopVoiceAudio(false);
    if (ev.mode === "mp3" && ev.audio_b64) playMp3(ev);
    else if (ev.mode === "offline" && ev.text && window.speechSynthesis) {
      const u = new SpeechSynthesisUtterance(ev.text);
      u.lang = ev.lang || "en-US";
      const voices = window.speechSynthesis.getVoices() || [];
      const wantMale = ev.persona === "male";
      const match = voices.find((v) => v.lang.startsWith(u.lang.slice(0, 2)) && (wantMale ? /male|david|pradeep|guy/i.test(v.name) : /female|zira|nabanita|aria/i.test(v.name)))
        || voices.find((v) => v.lang.startsWith(u.lang.slice(0, 2)));
      if (match) u.voice = match;
      u.onend = () => stopVoiceAudio(true);
      u.onerror = () => stopVoiceAudio(true);
      window.speechSynthesis.speak(u);
    } else send({ type: "audio_done" });
  }

  function unlockAudio() {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === "suspended") audioCtx.resume();
    } catch (_) {}
  }
  document.addEventListener("pointerdown", unlockAudio, { passive: true });
  document.addEventListener("keydown", unlockAudio, { passive: true });
  // মাইক্রোফোন অন/অফ সুইচ (জাস্ট অন/অফ হবে, নিজে নিজে রেকর্ড বা শোনা শুরু করবে না)
  function toggleMicPower() {
    unlockAudio();
    send({ type: "voice_toggle" });
  }
  ["#corePill", "#btnMicMode"].forEach((s) => on(s, "click", toggleMicPower));

  // মাঝখানের Crystal Core অরব ক্লিক:
  // - মাইক অফ থাকলে কিছুই হবে না (মিউট থাকবে, অটো চালু হবে না)
  // - কেবল মাইক অন থাকলেই কথা শোনা শুরু হবে (বা থামাতে চাইলে বন্ধ হবে)
  window.addEventListener("core-orb-click", () => {
    unlockAudio();
    if (!voiceState.mic_on) {
      setCore("idle", "Ready · Mic Off", "মাইক বন্ধ আছে — কথা বলতে ওপরে Mic On করুন");
      return;
    }
    send({ type: "voice_listen_toggle", force: false });
  });

  // চ্যাট ইন্টারফেসের মাইক বাটন: ক্লিক করলে শোনা শুরু হবে (প্রয়োজনে মাইক অন করবে)
  on("#btnMic", "click", () => {
    unlockAudio();
    send({ type: "voice_listen_toggle", force: true });
  });
  $$(".persona button[data-voice]").forEach((b) => b.addEventListener("click", () => send({ type: "voice_persona", persona: b.dataset.voice })));
  const toggleMute = () => send({ type: "voice_mute", muted: !voiceState.muted });
  ["#btnSpeak", "#btnMuteTop", "#btnSpeakTop2"].forEach((s) => on(s, "click", toggleMute));

  /* ================= লেজার ও স্টেপ ================= */
  function taskStart(ev) {
    stepNo = 0;
    $("#steps").innerHTML = "";
    $("#ledgerEmpty").hidden = true;
    setText("#taskId", "task · " + ev.task_id);
    const li = document.createElement("li");
    li.className = "head";
    li.innerHTML = `🎯 <b>${md(ev.text)}</b> <span class="muted">· ${ev.source}</span>`;
    $("#steps").appendChild(li);
    timeline("🎯 " + ev.text);
  }
  function toolStart(ev) {
    stepNo++;
    const li = document.createElement("li");
    li.className = "running";
    li.innerHTML = `<span class="n">${stepNo}</span><div><div class="tool">${ev.tool}</div><div class="args">${md(JSON.stringify(ev.args))}</div><div class="res"></div></div><span class="stt">⏳</span>`;
    $("#steps").appendChild(li);
    li.scrollIntoView({ block: "nearest" });
    stepEls[ev.step_id] = li;
    squadBusy(ev.tool, true);
    signal("info", ev.tool, JSON.stringify(ev.args).slice(0, 90));
  }
  function toolEnd(ev) {
    const li = stepEls[ev.step_id];
    squadBusy(ev.tool, false);
    stats.tools++; stats.ms += ev.ms || 0; ev.ok ? stats.ok++ : stats.fail++;
    const cat = toolCat[ev.tool];
    if (cat) lanes[cat] = { ...(lanes[cat] || {}), busy: false, tool: ev.tool, ms: ev.ms, ok: ev.ok };
    if (li) {
      li.className = ev.ok ? "ok" : "fail";
      li.querySelector(".stt").textContent = (ev.ok ? "✔ " : "✖ ") + ev.ms + "ms";
      li.querySelector(".res").textContent = (ev.result || "").slice(0, 300);
    }
    signal(ev.ok ? "ok" : "warn", ev.tool, String(ev.result || "").split("\n")[0].slice(0, 90));
    const tr = document.createElement("div");
    tr.className = "tr";
    tr.innerHTML = `<b>${ev.tool}</b> · ${ev.ms}ms · ${ev.ok ? "OK" : "FAIL"}\n${md(ev.result)}`;
    $("#traceView").prepend(tr);
    timeline(`${ev.ok ? "✔" : "✖"} ${ev.tool}`);
    renderAnalytics(); renderLanes();
  }

  function signal(level, title, text) {
    // শুধু "কিছু শোনা যায়নি" ধরনের ফাঁকা মাইক ইভেন্ট লগ করা হবে না; একই লাইন পরপর দুবার আসলেও না
    if (title === "mic" && /শোনা যায়নি|no speech|কোনো কথা/i.test(text || "")) return;
    const key = level + "|" + title + "|" + text;
    if (key === lastSignal) return;
    lastSignal = key;
    const li = document.createElement("li");
    li.className = level;
    const time = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    li.innerHTML = `<div class="t"><span></span><span>${time}</span></div><div class="d"></div>`;
    li.querySelector(".t span").textContent = title;
    li.querySelector(".d").textContent = text;
    const ul = $("#signals");
    ul.prepend(li);
    while (ul.children.length > 60) ul.lastChild.remove();
    setText("#sigCount", `${++signals} logged`);
  }
  function timeline(text) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${new Date().toLocaleTimeString("en-GB")}</span>`;
    li.appendChild(document.createTextNode(text));
    $("#timeline").prepend(li);
  }

  /* ================= নিচের ট্যাব: Squad / Lanes / Analytics / Memory ================= */
  const tile = (cls, title, big, sub) => `<div class="tile ${cls || ""}"><b>${title}</b>${big !== null ? `<span class="big">${big}</span>` : ""}<small>${sub || ""}</small></div>`;
  function renderSquadGrid() {
    const g = $("#squadGrid");
    if (!g) return;
    g.innerHTML = SQUAD.map((a) => {
      const tools = Object.keys(toolCat).filter((t) => toolCat[t] === a.id);
      return tile(squadReady[a.id] ? "ready" : "dim", `${a.ico} ${a.name}`, null, `${a.role}<br>${tools.length ? tools.slice(0, 6).join(", ") + (tools.length > 6 ? " …" : "") : "শীঘ্রই আসছে"}`);
    }).join("");
  }
  function renderLanes() {
    const g = $("#lanesGrid");
    if (!g) return;
    g.innerHTML = SQUAD.map((a) => {
      const l = lanes[a.id] || {};
      const sub = l.tool ? `${l.tool}${l.ms ? " · " + l.ms + "ms" : ""}` : "কোনো কাজ হয়নি";
      return tile(l.busy ? "busy" : squadReady[a.id] ? "ready" : "dim", `${a.name}`, l.busy ? "WORKING" : "IDLE", sub);
    }).join("");
  }
  function renderAnalytics() {
    const g = $("#analyticsGrid");
    if (!g) return;
    const avg = stats.tools ? Math.round(stats.ms / stats.tools) : 0;
    g.innerHTML = [
      tile("", "Tasks", stats.tasks, "এই সেশনে"),
      tile("", "Tool calls", stats.tools, `${stats.ok} ✔ · ${stats.fail} ✖`),
      tile("", "Avg speed", avg + "ms", "প্রতি টুল"),
      tile("", "Voice turns", stats.voice, "মাইক থেকে"),
    ].join("");
  }
  function renderMemories(list, count) {
    const ul = $("#memList");
    if (!ul) return;
    ul.innerHTML = "";
    const arr = Array.isArray(list) ? list : [];
    if (!arr.length) {
      const li = document.createElement("li");
      li.textContent = count ? `${count}টি মেমরি আছে — "তুমি কী কী মনে রেখেছো" বললে সব দেখাবে।` : 'এখনো কোনো মেমরি নেই — "মনে রাখো …" বলে শুরু করুন।';
      ul.appendChild(li);
      return;
    }
    arr.forEach((m) => {
      const li = document.createElement("li");
      let txt = typeof m === "string" ? m : m.text || m.fact || m.content || m.note || (m.key && m.value ? `${m.key}: ${m.value}` : JSON.stringify(m));
      li.textContent = txt;
      ul.appendChild(li);
    });
  }

  /* ================= 🔒 অনুমতি (STRICT) ================= */
  let cfId = null, cfTimer = null;
  function openConfirm(ev) {
    cfId = ev.id;
    setText("#cfTitle", ev.title);
    setText("#cfTool", "tool: " + ev.tool);
    const lines = [];
    Object.entries(ev.details || {}).forEach(([k, v]) => {
      lines.push(`${k}:`);
      (Array.isArray(v) ? v : [v]).forEach((x) => lines.push("  " + (typeof x === "string" ? x : JSON.stringify(x))));
    });
    setText("#cfDetails", lines.join("\n"));
    $("#cfCheck").checked = false;
    $("#cfApprove").disabled = true;
    $("#confirmWrap").hidden = false;
    setCore("confirm", "অনুমতির অপেক্ষায়…", ev.title);
    let left = Math.round(ev.timeout || 180);
    clearInterval(cfTimer);
    setText("#cfTimer", `${left}s`);
    cfTimer = setInterval(() => { left--; setText("#cfTimer", `${left}s`); if (left <= 0) clearInterval(cfTimer); }, 1000);
    $("#cfDeny").focus();
    signal("error", "approval", ev.title);
    try { new Audio("data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=").play(); } catch (_) {}
  }
  function closeConfirm(ev) {
    if (ev.id !== cfId) return;
    clearInterval(cfTimer);
    $("#confirmWrap").hidden = true;
    signal(ev.approved ? "ok" : "warn", "approval", ev.approved ? "অনুমোদিত ✔" : "বাতিল ✖");
    cfId = null;
    setCore("idle", idleText(), idleHint());
  }
  on("#cfCheck", "change", (e) => ($("#cfApprove").disabled = !e.target.checked));
  on("#cfApprove", "click", () => { if ($("#cfCheck").checked && cfId) send({ type: "confirm", id: cfId, approved: true }); });
  on("#cfDeny", "click", () => cfId && send({ type: "confirm", id: cfId, approved: false }));

  /* ================= ইনফো মডাল (কার্ড / Help) ================= */
  function openInfo(k) {
    if (k === "models") { $("#modelsWrap").hidden = false; return; }
    if (k === "memory") { submit("তুমি কী কী মনে রেখেছো সব দেখাও"); return; }
    let title = "", body = "";
    if (k === "skills") {
      title = "🛠️ Skills";
      body = Object.entries(window.__skills || {}).map(([cat, tools]) => `<b>${cat}</b><ul>${tools.map((t) => `<li><code>${t}</code></li>`).join("")}</ul>`).join("");
    } else if (k === "help") {
      title = "❓ শর্টকাট ও গাইড";
      body = `<ul>
        <li>🎙️ <b>মাইক:</b> Crystal Core, উপরের <code>Mic</code> বা নিচের 🎙️ — যেকোনোটায় ক্লিক = অন/অফ। অফ থাকলে Synthia কিছুই শোনে না।</li>
        <li>🌐 <b>ভাষা:</b> বাংলায় বললে বাংলায়, English-এ বললে English-এ উত্তর।</li>
        <li>↔️ <b>সেকশন টানা:</b> যেকোনো দুই প্যানেলের মাঝের পাতলা বার টানলে বড়-ছোট হবে, ডাবল-ক্লিকে রিসেট। <code>⊞</code> বাটনে সব রিসেট।</li>
        <li>⛔ <b>Kill switch:</b> <code>Ctrl+Shift+X</code></li>
        <li>🎨 <b>থিম:</b> 3D Neon / Aurora / Paper</li>
      </ul>`;
    } else {
      title = "⚙️ Settings, App & Safety";
      body = `
      <div style="display:flex;gap:.8rem;flex-wrap:wrap;margin-bottom:1.2rem;">
        <button class="btn" id="btnPinIcons">📌 Desktop ও Start Menu আইকন তৈরি করুন</button>
        <button class="btn btn-danger" id="btnQuitFull">✖ পুরোপুরি বন্ধ করুন (Exit App)</button>
      </div>
      <label class="check" style="margin-bottom:1.2rem;">
        <input type="checkbox" id="chkStartup" ${window.__startup ? "checked" : ""} />
        🚀 পিসি চালু হলেই Synthia স্বয়ংক্রিয়ভাবে ব্যাকগ্রাউন্ডে চালু হবে (Start with Windows)
      </label>
      <ul>
        <li>💠 <b>System Tray:</b> উইন্ডোর উপরের <code>✕</code> চাপলে অ্যাপ বন্ধ না হয়ে ঘড়ির পাশের ট্রে-তে মিনিমাইজ থাকে।</li>
        <li>🔒 <b>Strict Delete:</b> যেকোনো ডিলিট, ওভাররাইট, অ্যাপ বন্ধ ও PowerShell কমান্ডের আগে আপনার অনুমতি লাগবে — কোনো সেটিং দিয়ে বন্ধ করা যায় না।</li>
        <li>🗑️ ডিলিট করা সবকিছু <b>Recycle Bin</b>-এ যায় (স্থায়ী ডিলিট নিষিদ্ধ)। সিস্টেম ফোল্ডার ডিলিট ব্লকড।</li>
        <li>⛔ Kill switch: <code>Ctrl+Shift+X</code> (যেকোনো উইন্ডো থেকে)</li>
        <li>⚙️ সেটিংস ফাইল: <code>config/settings.yaml</code>, মডেল: <code>config/models.yaml</code>, keys: <code>.env</code></li>
      </ul>`;
    }
    setText("#infoTitle", title);
    $("#infoBody").innerHTML = body;
    const pin = $("#btnPinIcons"); if (pin) pin.onclick = () => send({ type: "install_shortcuts" });
    const quit = $("#btnQuitFull"); if (quit) quit.onclick = () => send({ type: "quit_app" });
    const chk = $("#chkStartup"); if (chk) chk.onchange = (e) => { window.__startup = e.target.checked; send({ type: "set_startup", enabled: e.target.checked }); };
    $("#infoWrap").hidden = false;
  }
  $$(".card[data-open]").forEach((c) => c.addEventListener("click", () => openInfo(c.dataset.open)));
  on("#btnStageSkills", "click", () => openInfo("skills"));
  on("#btnHelp", "click", () => openInfo("help"));
  on("#btnFullscreen", "click", () => {
    try { document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen(); } catch (_) {}
  });

  /* ================= ইনপুট ও ট্যাব ================= */
  const input = $("#input");
  function submit(text) {
    text = (text ?? input.value).trim();
    if (!text) return;
    addMsg("user", text);
    send({ type: "command", text });
    showTyping(true);                       // সাথে সাথে "ভাবছি…" দেখায়, backend-এর অপেক্ষা করে না
    input.value = "";
    autosize();
  }
  function autosize() { input.style.height = ""; }
  on(input, "keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
  on("#btnSend", "click", () => submit());
  on("#btnKill", "click", () => send({ type: "cancel" }));
  on("#btnReset", "click", () => { send({ type: "reset" }); $("#chatView").querySelectorAll(".msg:not(.welcome-msg)").forEach((m) => m.remove()); typingEl = null; });
  $$("#quickActions button").forEach((b) => b.addEventListener("click", () => {
    if (b.classList.contains("soon")) return;
    if (b.dataset.cmd) submit(b.dataset.cmd);
    else if (b.dataset.prompt) { input.value = b.dataset.prompt; input.focus(); }
  }));
  $$(".tabs").forEach((tabs) => tabs.querySelectorAll("button[data-tab]").forEach((b) => b.addEventListener("click", () => {
    tabs.querySelectorAll("button[data-tab]").forEach((x) => x.classList.toggle("active", x === b));
    tabs.parentElement.querySelectorAll(":scope > .tab-body").forEach((t) => t.classList.toggle("active", t.id === b.dataset.tab));
  })));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { $("#modelsWrap").hidden = true; $("#infoWrap").hidden = true; } });

  setInterval(() => setText("#clock", new Date().toLocaleTimeString("en-GB")), 1000);
  setText("#clock", new Date().toLocaleTimeString("en-GB"));

  /* ================= শুরু ================= */
  initLayout();
  renderAnalytics();
  renderLanes();
  renderSquadGrid();
  refreshPersona();
  setCore("idle", idleText(), idleHint());
  window.Core && window.Core.relayout && window.Core.relayout();
  drawLinks();
  connect();
})();
