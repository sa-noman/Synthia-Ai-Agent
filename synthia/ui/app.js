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
      el.title = `${a.name} — ${a.role} (ক্লিক করে বিস্তারিত দেখুন)`;
      el.innerHTML = `<span class="ico">${a.ico}</span><div class="c-txt"><b>${a.name}<em>${a.role}</em></b><span class="st">${ok ? "Ready" : "Soon"}</span></div><span class="num">${counts[a.id] || 0}</span>`;
      el.addEventListener("click", () => renderSquadModal(a.id));
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

  let currentInfoModal = "", currentSkillFilter = "all";
  const modelTests = {};
  const openDrawers = {};

  function handle(ev) {
    switch (ev.type) {
      case "state": applyState(ev); break;
      case "brain_state": applyBrain(ev); break;
      case "telemetry": telemetry(ev); break;
      case "chat": chat(ev); break;
      case "status": status(ev); break;
      case "task_start": taskStart(ev); break;
      case "tool_start": toolStart(ev); break;
      case "tool_end":
        toolEnd(ev);
        if (["memory", "remember", "skill_manage"].includes(ev.tool)) send({ type: "state" });
        break;
      case "task_end":
        setText("#taskId", "done · " + ev.task_id);
        stats.tasks++;
        renderAnalytics();
        setTimeout(() => send({ type: "state" }), 1200);
        break;
      case "signal": signal(ev.level || "info", ev.title || "signal", ev.text || ""); break;
      case "model_active": {
        const changed = !brain || brain.active !== ev.id;
        if (brain) {
          brain.active = ev.id;
          if (ev.mode) brain.mode = ev.mode;
          renderModels();
          updateModelChips();
        } else {
          setText("#activeModel", ev.label);
        }
        if (changed) signal("info", "model", "Brain: " + (ev.label || ev.id));
        break;
      }
      case "model_test_result":
        modelTests[ev.model_id] = ev;
        renderModels();
        signal(ev.ok ? "ok" : "error", "model_test", ev.ok ? `✔ ${ev.model_id} সচল (${ev.ms}ms)` : `✖ ${ev.model_id}: ${ev.error}`);
        break;
      case "session_search_result":
        renderSessionSearchResult(ev.query, ev.result);
        break;
      case "chat_thread_loaded":
        loadChatThreadIntoView(ev.thread_id, ev.messages || []);
        break;
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
    const lCount = (s.learned_skills || []).length;
    setText("#cSkillsSub", Object.keys(s.skills || {}).length + " categories" + (lCount ? ` · ${lCount} learned` : ""));
    setText("#cMem", s.memory_count);
    window.__skills = s.skills || {};
    window.__toolsDetail = s.tools_detail || [];
    window.__learnedSkills = s.learned_skills || [];
    window.__memories = s.memories || [];
    window.__learningMem = s.learning_memory || { user: [], memory: [], stats: {} };
    window.__chatHistory = Array.isArray(s.chat_history) ? s.chat_history : [];
    window.__mobileHistory = Array.isArray(s.mobile_history) ? s.mobile_history : [];
    window.__activeThread = s.active_thread || "";
    window.__activeMobileThread = s.active_mobile_thread || "";
    window.__mobile = s.mobile || null;
    window.__startup = !!s.startup_enabled;
    renderSquad(s.skills);
    if (s.brain) applyBrain(s.brain);
    renderChatHistory(window.__chatHistory, window.__activeThread);
    renderMobileHistory(window.__mobileHistory, window.__activeMobileThread);
    if (s.voice) applyVoice(s.voice);
    (s.pending_confirms || []).forEach(openConfirm);
    if ($("#infoWrap") && !$("#infoWrap").hidden) {
      if (currentInfoModal === "memory") renderMemoryModal();
      else if (currentInfoModal === "skills") renderSkillsModal(currentSkillFilter);
      else if (currentInfoModal && currentInfoModal.startsWith("squad:")) renderSquadModal(currentInfoModal.slice(6));
    }
  }

  /* ================= মডেল / ব্রেন ================= */
  const KEY_LINKS = {
    GEMINI_API_KEY: "https://aistudio.google.com/app/apikey",
    GROQ_API_KEY: "https://console.groq.com/keys",
    CEREBRAS_API_KEY: "https://cloud.cerebras.ai/",
    OPENROUTER_API_KEY: "https://openrouter.ai/keys",
    MISTRAL_API_KEY: "https://console.mistral.ai/api-keys/",
    GITHUB_TOKEN: "https://github.com/settings/personal-access-tokens/new",
    NVIDIA_API_KEY: "https://build.nvidia.com/",
  };
  const providerOf = (m) => m.provider_name || m.provider || (m.local ? "Ollama (Local)" : String(m.label || "Cloud").split(/[\s·(]/)[0]);
  let selectedProvider = "Google AI Studio";
  const PROVIDER_ICONS = {
    "Google AI Studio": "⚡",
    "OpenRouter": "🌐",
    "Ollama (Local)": "💻",
    "Groq": "⚡",
    "Cerebras": "⚡",
    "Mistral AI": "🌪️",
    "GitHub Models": "🐙",
    "NVIDIA NIM": "🟢",
  };

  function groupByProvider(list) {
    const map = new Map();
    (list || []).forEach((m) => {
      const pname = (m.provider_name || providerOf(m) || "Other").trim();
      if (!map.has(pname)) map.set(pname, []);
      map.get(pname).push(m);
    });
    return map;
  }

  function updateModelChips() {
    if (!brain) return;
    const isManual = brain.mode === "manual";
    const id = isManual ? brain.manual_model : (brain.preferred_model || brain.active);
    const act = brain.models.find((m) => m.id === (isManual ? brain.manual_model : brain.active))
      || brain.models.find((m) => m.id === id)
      || brain.models[0];
    if (act) {
      const pname = act.provider_name || providerOf(act);
      if (!selectedProvider) selectedProvider = pname;
      const cleanName = (act.label || act.model || "").replace(/\s*\([^)]*\)\s*$/, "").trim();
      const modeIcon = isManual ? "📌 " : "⚡ ";
      const shortDisp = cleanName && cleanName !== act.model ? `${cleanName} (${act.model})` : act.model;

      setText("#activeProviderModel", `${pname} · ${act.model}`);
      setText("#activeModel", modeIcon + shortDisp);

      const brainDot = $("#brainDot");
      if (brainDot) brainDot.className = "dot " + (act.available ? "dot-ok" : "dot-warn");
    }

    const provModels = brain.models.filter((m) => (m.provider_name || providerOf(m)) === selectedProvider);
    const provAvail = provModels.some((m) => m.available);
    setText("#activeProvider", selectedProvider || "Provider");
    const provDot = $("#providerDot");
    if (provDot) provDot.className = "dot " + (provAvail ? "dot-ok" : "dot-warn");

    const auto = !isManual;
    setText("#modeLabel", auto ? "Auto-Switch" : "Manual Lock");
    const b = $("#btnAutoMode");
    if (b) b.classList.toggle("active", auto);
    const md = $("#modeDot");
    if (md) md.className = "dot " + (auto ? "dot-ok" : "dot-warn");
  }

  function applyBrain(b) {
    brain = b;
    if (b.active_provider) {
      selectedProvider = b.active_provider;
    } else {
      const act = b.models.find((m) => m.id === b.active);
      if (act) selectedProvider = act.provider_name || providerOf(act);
    }
    $$("#modeSeg button, #topModeSeg button").forEach((x) => x.classList.toggle("active", x.dataset.mode === b.mode));
    const provMap = groupByProvider(b.models);
    let readyProvs = 0;
    provMap.forEach((pModels) => {
      if (pModels.some((m) => m.available)) readyProvs += 1;
    });
    setText("#cModels", `${readyProvs}/${provMap.size}`);

    const delProvMap = groupByProvider(b.deleted_models || []);
    const delCount = delProvMap.size;
    const btnRes = $("#btnRestoreDefaults");
    if (btnRes) {
      btnRes.textContent = delCount ? `♻️ Restore Defaults (${delCount})` : "♻️ Restore Defaults";
      btnRes.classList.toggle("btn-accent", delCount > 0);
    }
    updateModelChips();
    renderModels();
  }

  function renderModels() {
    if (!brain) return;
    const box = $("#modelList");
    if (!box) return;
    box.innerHTML = "";

    const providerMap = groupByProvider(brain.models);

    providerMap.forEach((pModels, pname) => {
      const drawerKey = "prov:" + pname;
      const firstM = pModels[0];
      const provEnvKey = (pModels.find((m) => m.api_key_env) || {}).api_key_env || "";
      const provHasKey = pModels.some((m) => m.has_key);
      const provKeyMasked = (pModels.find((m) => m.key_masked) || {}).key_masked || "";
      const provKeyVal = (pModels.find((m) => m.api_key_val) || {}).api_key_val || "";
      const provIsLocal = pModels.every((m) => m.local);
      const provAvail = pModels.some((m) => m.available);
      const provVision = pModels.some((m) => m.vision);
      const activeTarget = brain.mode === "manual" ? brain.manual_model : brain.active;
      const provActive = pModels.some((m) => m.id === activeTarget || m.id === brain.active);
      const minPrio = Math.min(...pModels.map((m) => Number(m.priority || 50)));
      const coolModel = pModels.find((m) => m.cooldown);
      const testTarget = pModels.find((m) => m.id === brain.active) || pModels.find((m) => m.available) || firstM;
      const tst = testTarget ? modelTests[testTarget.id] : null;
      const icon = PROVIDER_ICONS[pname] || (provIsLocal ? "💻" : "🌐");
      const keyUrl = KEY_LINKS[provEnvKey] || "";
      const drawerState = openDrawers[drawerKey] || "";

      if (provIsLocal) {
        const readyCount = pModels.filter((m) => m.available).length;
        const hdr = document.createElement("div");
        hdr.className = "provider-group-title";
        hdr.innerHTML = `
          <span>💻 ${pname}</span>
          <div class="prov-actions">
            <small>${readyCount}/${pModels.length} Ready · পিসির লোকাল মডেল (অফলাইন)</small>
          </div>
        `;
        box.appendChild(hdr);

        const lbox = document.createElement("div");
        lbox.className = "local-group-box";
        pModels.forEach((m) => {
          const isCur = m.id === activeTarget || m.id === brain.active;
          const mTst = modelTests[m.id];
          const mDrawer = openDrawers[m.id] || "";
          const card = document.createElement("div");
          card.className = `model ${isCur ? "selected" : ""} ${m.available ? "" : "off"}`;
          card.innerHTML = `
            <div class="model-top">
              <div class="model-info">
                <b>${m.label}</b>
                <small>${m.model} · priority ${m.priority}</small>
              </div>
              <div class="badges">
                <span class="badge local">LOCAL · Offline</span>
                ${m.vision ? '<span class="badge">👁 Vision</span>' : ""}
                <span class="badge ok">✔ Ready</span>
                ${mTst ? `<span class="badge ${mTst.ok ? "ok" : "warn"}">${mTst.ok ? "✔ " + mTst.ms + "ms" : "✖ Error"}</span>` : ""}
                <button class="btn-sm ${isCur ? "btn-accent" : ""}" data-act="select">${isCur ? "✔ Active" : "⚡ Use Model"}</button>
                <button class="btn-sm" data-act="test">📡 Test</button>
                <button class="btn-sm" data-act="edit">✏️ Edit</button>
                <button class="btn-sm btn-danger-sm" data-act="del-model">🗑️ Delete</button>
              </div>
            </div>
            <div class="model-drawer" data-drawer="edit" ${mDrawer === "edit" ? "" : "hidden"}>
              <div style="font-size:1.12rem;font-weight:700;color:rgb(var(--c-teal));margin-bottom:0.25rem;">
                ✏️ লোকাল মডেল এডিট করুন
              </div>
              <div class="edit-grid">
                <div class="edit-field">
                  <label>মডেলের নাম (Label):</label>
                  <input type="text" class="inp-lbl" value="${m.label || ""}" />
                </div>
                <div class="edit-field">
                  <label>Ollama Model ID:</label>
                  <input type="text" class="inp-mname" value="${m.model || ""}" />
                </div>
                <div class="edit-field">
                  <label>Base URL:</label>
                  <input type="text" class="inp-burl" value="${m.base_url || "http://127.0.0.1:11434"}" />
                </div>
                <div class="edit-field" style="max-width:12rem;">
                  <label>Priority:</label>
                  <input type="number" class="inp-prio" value="${m.priority}" min="1" max="200" />
                </div>
              </div>
              <div style="display:flex;align-items:center;justify-content:space-between;gap:0.8rem;flex-wrap:wrap;margin-top:0.5rem;">
                <label class="check" style="margin:0;">
                  <input type="checkbox" class="chk-vision" ${m.vision ? "checked" : ""} />
                  <span>👁 Vision সাপোর্ট আছে</span>
                </label>
                <div style="display:flex;gap:0.6rem;flex-wrap:wrap;">
                  ${m.is_default ? `<button class="btn-sm" data-act="reset-default">♻️ Reset Default</button>` : ""}
                  <button class="btn-sm" data-act="close-drawer">✕ বাতিল</button>
                  <button class="btn-sm btn-accent" data-act="save-edit">💾 Update সেভ করুন</button>
                </div>
              </div>
            </div>
          `;
          const pick = () => {
            selectedProvider = pname;
            send({ type: "set_model", mode: brain.mode, model_id: m.id });
          };
          card.querySelector(".model-top").addEventListener("click", (e) => {
            if (e.target.closest("button")) return;
            pick();
          });
          card.querySelector('[data-act="select"]')?.addEventListener("click", pick);
          card.querySelector('[data-act="test"]')?.addEventListener("click", (e) => {
            e.currentTarget.textContent = "⏳ Testing…";
            send({ type: "test_model", model_id: m.id });
          });
          card.querySelector('[data-act="edit"]')?.addEventListener("click", () => {
            openDrawers[m.id] = openDrawers[m.id] === "edit" ? "" : "edit";
            renderModels();
          });
          card.querySelector('[data-act="close-drawer"]')?.addEventListener("click", () => {
            openDrawers[m.id] = "";
            renderModels();
          });
          card.querySelector('[data-act="save-edit"]')?.addEventListener("click", () => {
            openDrawers[m.id] = "";
            send({
              type: "update_model",
              model_id: m.id,
              updates: {
                label: card.querySelector(".inp-lbl")?.value.trim(),
                model: card.querySelector(".inp-mname")?.value.trim(),
                base_url: card.querySelector(".inp-burl")?.value.trim(),
                priority: parseInt(card.querySelector(".inp-prio")?.value || m.priority, 10),
                vision: !!card.querySelector(".chk-vision")?.checked,
              },
            });
          });
          card.querySelector('[data-act="reset-default"]')?.addEventListener("click", () => {
            if (confirm(`'${m.label}' রিসেট করতে চান?`)) {
              openDrawers[m.id] = "";
              send({ type: "reset_single_default", model_id: m.id });
            }
          });
          card.querySelector('[data-act="del-model"]')?.addEventListener("click", () => {
            if (confirm(`'${m.label}' মডেলটি তালিকা থেকে সরাতে চান?`)) {
              openDrawers[m.id] = "";
              send({ type: "delete_model", model_id: m.id });
            }
          });
          lbox.appendChild(card);
        });
        box.appendChild(lbox);
        return;
      }

      const el = document.createElement("div");
      el.className = `model ${provActive ? "selected" : ""} ${provAvail ? "" : "off"}`;

      const badges = [
        provIsLocal ? '<span class="badge local">LOCAL · Offline</span>' : '<span class="badge">CLOUD</span>',
        provVision ? '<span class="badge">👁 Vision</span>' : "",
        provAvail
          ? `<span class="badge ok">✔ Ready${provKeyMasked ? " · " + provKeyMasked : ""}</span>`
          : (!provIsLocal && provEnvKey
            ? `<button class="btn-sm btn-key-add" data-act="key">🔑 + Add API Key</button>`
            : `<span class="badge warn">Offline</span>`),
        coolModel ? `<span class="badge warn">⏳ Cooldown · ${coolModel.cooldown}s</span>` : "",
        tst ? `<span class="badge ${tst.ok ? "ok" : "warn"}">${tst.ok ? "✔ " + tst.ms + "ms" : "✖ Error"}</span>` : "",
      ].join("");

      const actionBtns = [
        !provIsLocal && provHasKey && provEnvKey ? `<button class="btn-sm" data-act="key">🔑 Key এডিট</button>` : "",
        !provIsLocal && provHasKey && provEnvKey ? `<button class="btn-sm btn-danger-sm" data-act="clear-key" title="${provEnvKey} মুছে ফেলুন">🗑️ Key</button>` : "",
        provAvail ? `<button class="btn-sm ${provActive ? "btn-accent" : ""}" data-act="select">${provActive ? "✔ Active" : "⚡ Use API"}</button>` : "",
        provAvail ? `<button class="btn-sm" data-act="test">📡 Test</button>` : "",
        `<button class="btn-sm" data-act="edit" title="প্ল্যাটফর্ম কনফিগারেশন ও মডেলসমূহ এডিট করুন">✏️ Edit</button>`,
        `<button class="btn-sm btn-danger-sm" data-act="del-prov" title="প্ল্যাটফর্মটি মুছে ফেলুন (রিস্টোর করা যাবে)">🗑️ Delete</button>`,
      ].join("");

      el.innerHTML = `
        <div class="model-top">
          <div class="model-info">
            <b>${icon} ${pname}</b>
            <small>${pModels.length}টি মডেল · priority ${minPrio}${provEnvKey ? " · " + provEnvKey : ""}</small>
          </div>
          <div class="badges">${badges} ${actionBtns}</div>
        </div>

        <div class="model-drawer" data-drawer="key" ${drawerState === "key" ? "" : "hidden"}>
          <div style="font-size:1.05rem;color:var(--text-dim);margin-bottom:0.15rem;">
            🔑 <b>${pname}</b> (${provEnvKey || "API Key"}):
          </div>
          <div class="key-input-row">
            <input type="password" class="inp-key" value="${provKeyVal}" placeholder="${provEnvKey || "API_KEY"} এখানে পেস্ট বা এডিট করুন (Ctrl+V)…" />
            <button class="btn-sm" data-act="toggle-vis" title="দেখুন/লুকান">👁</button>
            <button class="btn-sm btn-accent" data-act="save-key">💾 Save &amp; Use</button>
            ${provHasKey && provEnvKey ? `<button class="btn-sm btn-danger-sm" data-act="clear-key">🗑️ Key মুছুন</button>` : ""}
            ${keyUrl ? `<a class="btn-sm" href="${keyUrl}" target="_blank" style="text-decoration:none;">🔗 Get Free Key ↗</a>` : ""}
          </div>
        </div>

        <div class="model-drawer" data-drawer="edit" ${drawerState === "edit" ? "" : "hidden"}>
          <div style="font-size:1.15rem;font-weight:700;color:rgb(var(--c-teal));margin-bottom:0.25rem;">
            ✏️ ${pname} প্ল্যাটফর্ম ও মডেলসমূহ এডিট করুন
          </div>
          <div class="edit-grid">
            <div class="edit-field">
              <label>প্ল্যাটফর্ম নাম:</label>
              <input type="text" class="inp-pname" value="${pname}" placeholder="যেমন: OpenRouter / Google AI Studio" />
            </div>
            <div class="edit-field">
              <label>Base URL:</label>
              <input type="text" class="inp-burl" value="${firstM.base_url || ""}" placeholder="Base URL" />
            </div>
            <div class="edit-field" style="max-width:12rem;">
              <label>Priority (১-৯৯):</label>
              <input type="number" class="inp-prio" value="${minPrio}" min="1" max="200" />
            </div>
            ${!provIsLocal ? `
            <div class="edit-field">
              <label>Env Key Name:</label>
              <input type="text" class="inp-ekey" value="${provEnvKey}" placeholder="যেমন: OPENROUTER_API_KEY" />
            </div>
            <div class="edit-field">
              <label>API Key (পাসওয়ার্ড):</label>
              <div style="display:flex;gap:0.4rem;">
                <input type="password" class="inp-akey" value="${provKeyVal}" placeholder="API Key পেস্ট করুন…" />
                <button class="btn-sm" data-act="toggle-edit-vis" title="দেখুন/লুকান">👁</button>
              </div>
            </div>
            ` : ""}
          </div>

          <div style="font-size:1.05rem;color:var(--text-dim);margin-top:0.4rem;">
            এই API-এর অধীনে মডেলসমূহ (${pModels.length}টি):
          </div>
          <div class="prov-models-pills">
            ${pModels.map((m) => `
              <span class="model-pill ${m.id === activeTarget ? "active" : ""}" title="${m.label} (${m.model})">
                <span>${m.model}</span>
                ${pModels.length > 1 || brain.models.length > 1 ? `<button class="pill-del" data-del-model="${m.id}" title="${m.model} সরান">✕</button>` : ""}
              </span>
            `).join("")}
          </div>
          <div class="quick-add-row">
            <input type="text" class="inp-quick-model" placeholder="${pname}-এ নতুন Model ID যোগ করুন (যেমন: anthropic/claude-3.5-sonnet)" />
            <button class="btn-sm btn-accent" data-act="quick-add-model">➕ মডেল যুক্ত</button>
          </div>

          <div style="display:flex;align-items:center;justify-content:flex-end;gap:0.6rem;flex-wrap:wrap;margin-top:0.5rem;">
            <button class="btn-sm btn-danger-sm" data-act="del-prov" title="প্ল্যাটফর্মটি মুছে ফেলুন (রিস্টোর করা যাবে)">🗑️ প্ল্যাটফর্ম মুছুন</button>
            <button class="btn-sm" data-act="close-drawer">✕ বাতিল</button>
            <button class="btn-sm btn-accent" data-act="save-edit">💾 Update সেভ করুন</button>
          </div>
        </div>
      `;

      const focusKeyInput = () => {
        requestAnimationFrame(() => {
          const inp = el.querySelector(`.model-drawer:not([hidden]) .inp-key`);
          if (inp) inp.focus();
        });
      };

      const selectProviderApi = () => {
        const pick = pModels.find((m) => m.id === brain.active) || pModels.find((m) => m.available) || firstM;
        if (!pick || !provAvail) {
          openDrawers[drawerKey] = "key";
          renderModels();
          focusKeyInput();
          signal("warn", "api_key", `${pname} চালাতে নিচের বক্সে API Key পেস্ট করে Save & Use চাপুন`);
          return;
        }
        selectedProvider = pname;
        send({ type: "set_model", mode: brain.mode, model_id: pick.id });
      };

      el.querySelector(".model-top").addEventListener("click", (e) => {
        if (e.target.closest("button") || e.target.closest("a")) return;
        selectProviderApi();
      });

      el.querySelector('[data-act="select"]')?.addEventListener("click", selectProviderApi);

      el.querySelectorAll('[data-act="key"]').forEach((btn) => {
        btn.addEventListener("click", () => {
          openDrawers[drawerKey] = openDrawers[drawerKey] === "key" ? "" : "key";
          renderModels();
          if (openDrawers[drawerKey] === "key") focusKeyInput();
        });
      });

      el.querySelector('[data-act="edit"]')?.addEventListener("click", () => {
        openDrawers[drawerKey] = openDrawers[drawerKey] === "edit" ? "" : "edit";
        renderModels();
      });

      el.querySelector('[data-act="close-drawer"]')?.addEventListener("click", () => {
        openDrawers[drawerKey] = "";
        renderModels();
      });

      el.querySelector('[data-act="test"]')?.addEventListener("click", (e) => {
        if (!testTarget) return;
        e.currentTarget.textContent = "⏳ Testing…";
        send({ type: "test_model", model_id: testTarget.id });
      });

      el.querySelector('[data-act="toggle-vis"]')?.addEventListener("click", () => {
        const inp = el.querySelector(".inp-key");
        if (inp) inp.type = inp.type === "password" ? "text" : "password";
      });

      el.querySelector('[data-act="toggle-edit-vis"]')?.addEventListener("click", () => {
        const inp = el.querySelector(".inp-akey");
        if (inp) inp.type = inp.type === "password" ? "text" : "password";
      });

      const saveKey = () => {
        const val = (el.querySelector(".inp-key")?.value || "").trim();
        if (!val) { signal("warn", "api_key", "API Key ফাঁকা রাখা যাবে না"); return; }
        openDrawers[drawerKey] = "";
        selectedProvider = pname;
        const pick = pModels.find((m) => m.id === brain.active) || firstM;
        send({ type: "save_api_key", env_key: provEnvKey, api_key: val, model_id: pick ? pick.id : "" });
      };
      el.querySelector('[data-act="save-key"]')?.addEventListener("click", saveKey);
      el.querySelector(".inp-key")?.addEventListener("keydown", (e) => { if (e.key === "Enter") saveKey(); });

      el.querySelectorAll('[data-act="clear-key"]').forEach((btn) => {
        btn.addEventListener("click", () => {
          if (provEnvKey && confirm(`${pname} (${provEnvKey}) কি মুছে ফেলতে চান?`)) {
            openDrawers[drawerKey] = "";
            send({ type: "save_api_key", env_key: provEnvKey, api_key: "" });
          }
        });
      });

      el.querySelector('[data-act="save-edit"]')?.addEventListener("click", () => {
        const newPname = el.querySelector(".inp-pname")?.value.trim();
        const base_url = el.querySelector(".inp-burl")?.value.trim();
        const priority = parseInt(el.querySelector(".inp-prio")?.value || minPrio, 10);
        const api_key_env = el.querySelector(".inp-ekey")?.value.trim();
        const api_key = el.querySelector(".inp-akey")?.value.trim();
        openDrawers[drawerKey] = "";
        send({
          type: "update_provider",
          provider_name: pname,
          updates: { provider_name: newPname, base_url, priority, api_key_env },
        });
        if (!provIsLocal && api_key !== undefined && api_key_env) {
          const targetEnv = api_key_env.toUpperCase();
          if (api_key || provHasKey) {
            send({ type: "save_api_key", env_key: targetEnv, api_key });
          }
        }
      });

      el.querySelectorAll("[data-del-model]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const mid = btn.dataset.delModel;
          if (confirm(`এই মডেলটি '${pname}' থেকে সরাতে চান?`)) {
            send({ type: "delete_model", model_id: mid });
          }
        });
      });

      const quickAddModel = () => {
        const inp = el.querySelector(".inp-quick-model");
        const midVal = (inp?.value || "").trim();
        if (!midVal) { signal("warn", "model", "নতুন Model ID লিখুন"); return; }
        send({
          type: "add_custom_model",
          data: {
            provider_name: pname,
            label: `${midVal} (${pname})`,
            provider: firstM.provider || (provIsLocal ? "ollama" : "openai_compat"),
            base_url: firstM.base_url || "",
            model: midVal,
            api_key_env: provEnvKey,
            priority: minPrio,
            vision: provVision,
          },
        });
        if (inp) inp.value = "";
      };
      el.querySelector('[data-act="quick-add-model"]')?.addEventListener("click", quickAddModel);
      el.querySelector(".inp-quick-model")?.addEventListener("keydown", (e) => { if (e.key === "Enter") quickAddModel(); });

      el.querySelectorAll('[data-act="del-prov"]').forEach((btn) => {
        btn.addEventListener("click", () => {
          if (confirm(`'${pname}' প্ল্যাটফর্মটি (${pModels.length}টি মডেলসহ) তালিকা থেকে সরাতে চান?\n(পরে নিচে থেকে রিস্টোর করতে পারবেন)`)) {
            openDrawers[drawerKey] = "";
            send({ type: "delete_provider", provider_name: pname, clear_key: false });
          }
        });
      });

      box.appendChild(el);
    });

    if (brain.deleted_models && brain.deleted_models.length > 0) {
      const delProvMap = groupByProvider(brain.deleted_models);
      const delSec = document.createElement("div");
      delSec.className = "deleted-sec";
      const cardsHtml = [];
      delProvMap.forEach((dModels, pname) => {
        const isDef = dModels.some((dm) => dm.is_default);
        const icon = PROVIDER_ICONS[pname] || (dModels.every((dm) => dm.local) ? "💻" : "🌐");
        cardsHtml.push(`
          <div class="model deleted-card">
            <div class="model-top" style="cursor:default;">
              <div class="model-info">
                <b>${icon} ${pname}</b>
                <small>${dModels.length}টি মডেল সংরক্ষিত</small>
              </div>
              <div class="badges">
                <button class="btn-sm btn-accent" data-restore-prov="${pname}">♻️ Restore</button>
                ${!isDef ? `<button class="btn-sm btn-danger-sm" data-purge-prov="${pname}" title="স্থায়ীভাবে মুছে ফেলুন">❌ স্থায়ীভাবে মুছুন</button>` : `<span class="badge">Built-in Default</span>`}
              </div>
            </div>
          </div>
        `);
      });

      delSec.innerHTML = `
        <div class="deleted-head">
          <span>🗑️ মুছে ফেলা প্ল্যাটফর্ম (${delProvMap.size}টি)</span>
          <button class="btn-sm btn-accent" data-act="restore-all-defaults">♻️ সব ডিফল্ট প্ল্যাটফর্ম রিস্টোর করুন</button>
        </div>
        <div style="display:grid;gap:0.6rem;margin-top:0.4rem;">
          ${cardsHtml.join("")}
        </div>
      `;

      delSec.querySelector('[data-act="restore-all-defaults"]')?.addEventListener("click", () => {
        send({ type: "restore_default_models" });
      });

      delSec.querySelectorAll("[data-restore-prov]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          send({ type: "restore_provider", provider_name: btn.dataset.restoreProv });
        });
      });

      delSec.querySelectorAll("[data-purge-prov]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          if (confirm(`'${btn.dataset.purgeProv}' প্ল্যাটফর্মটি কি স্থায়ীভাবে মুছে ফেলতে চান?`)) {
            send({ type: "purge_deleted_provider", provider_name: btn.dataset.purgeProv });
          }
        });
      });

      box.appendChild(delSec);
    }
  }

  function renderProviderDrop() {
    const menu = $("#providerDropMenu");
    if (!menu || !brain) return;
    menu.innerHTML = "";

    const providerMap = groupByProvider(brain.models);

    providerMap.forEach((models, pname) => {
      const isCurrent = pname === selectedProvider;
      const hasAvail = models.some((m) => m.available);
      const isLocal = models.every((m) => m.local);
      const icon = PROVIDER_ICONS[pname] || (isLocal ? "💻" : "🌐");

      const b = document.createElement("button");
      b.className = (isCurrent ? "sel " : "") + (hasAvail ? "" : "off");
      const tag = isLocal ? "LOCAL" : (hasAvail ? "✔ Ready" : "🔑 + Key");
      b.innerHTML = `
        <span class="dot ${hasAvail ? "dot-ok" : "dot-warn"}"></span>
        <span>${icon} ${pname}</span>
        <small>${tag}</small>
      `;

      b.addEventListener("click", (e) => {
        e.stopPropagation();
        menu.hidden = true;
        selectedProvider = pname;
        const availModel = models.find((m) => m.available);
        const targetModel = availModel || models[0];

        if (models.length === 1 && targetModel && targetModel.available) {
          send({
            type: "set_model",
            mode: brain.mode,
            model_id: targetModel.id,
          });
        }
        updateModelChips();
        renderModelDrop();
        const mm = $("#modelDropMenu");
        if (mm) mm.hidden = false;
      });

      menu.appendChild(b);
    });

    const div = document.createElement("div");
    div.style.cssText = "border-top:1px dashed var(--line);margin-top:0.4rem;padding-top:0.4rem;";

    const btnAdd = document.createElement("button");
    btnAdd.className = "btn-drop-action";
    btnAdd.innerHTML = `<span>➕ Add Custom Provider / Model</span>`;
    btnAdd.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = true;
      $("#modelsWrap").hidden = false;
      const box = $("#customModelBox");
      if (box) box.hidden = false;
    });
    div.appendChild(btnAdd);

    const btnManage = document.createElement("button");
    btnManage.className = "btn-drop-action";
    btnManage.innerHTML = `<span>🔑 Manage Keys &amp; Platforms</span>`;
    btnManage.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = true;
      $("#modelsWrap").hidden = false;
      renderModels();
    });
    div.appendChild(btnManage);

    menu.appendChild(div);
  }

  function renderModelDrop() {
    const menu = $("#modelDropMenu");
    if (!menu || !brain) return;
    menu.innerHTML = "";

    let filtered = brain.models.filter((m) => (m.provider_name || providerOf(m)) === selectedProvider);
    if (!filtered.length) filtered = brain.models;
    const activeTarget = brain.mode === "manual" ? brain.manual_model : brain.active;

    filtered.forEach((m) => {
      const sel = m.id === activeTarget;
      const b = document.createElement("button");
      b.className = (sel ? "sel " : "") + (m.available ? "" : "off");
      const rightTag = m.local ? "LOCAL" : (m.available ? "✔ Ready" : "🔑 + Key");
      const cleanLabel = (m.label || m.model || "").replace(/\s*\([^)]*\)\s*$/, "").trim();
      const titleHtml = cleanLabel && cleanLabel !== m.model
        ? `${cleanLabel} <em style="font-style:normal;opacity:0.65;font-size:0.92em;">(${m.model})</em>`
        : `${m.model}`;
      b.innerHTML = `
        <span class="dot ${m.available ? "dot-ok" : "dot-warn"}"></span>
        <span>${titleHtml}</span>
        <small>${rightTag}</small>
      `;
      b.addEventListener("click", (e) => {
        e.stopPropagation();
        menu.hidden = true;
        const pname = m.provider_name || providerOf(m);
        if (!m.available) {
          openDrawers["prov:" + pname] = "key";
          $("#modelsWrap").hidden = false;
          renderModels();
          requestAnimationFrame(() => {
            const inp = $("#modelList")?.querySelector(`.model-drawer:not([hidden]) .inp-key`);
            if (inp) inp.focus();
          });
          signal("warn", "api_key", `${pname} চালাতে API Key পেস্ট করে Save & Use চাপুন`);
          return;
        }
        selectedProvider = pname;
        send({
          type: "set_model",
          mode: brain.mode,
          model_id: m.id,
        });
      });
      menu.appendChild(b);
    });

    const div = document.createElement("div");
    div.style.cssText = "border-top:1px dashed var(--line);margin-top:0.4rem;padding-top:0.4rem;";

    if (selectedProvider && filtered.length) {
      const refM = filtered[0];
      const btnAddModel = document.createElement("button");
      btnAddModel.className = "btn-drop-action";
      btnAddModel.innerHTML = `<span>➕ ${selectedProvider}-এ নতুন মডেল যোগ করুন</span>`;
      btnAddModel.addEventListener("click", (e) => {
        e.stopPropagation();
        menu.hidden = true;
        $("#modelsWrap").hidden = false;
        const box = $("#customModelBox");
        if (box) box.hidden = false;
        if ($("#cmProviderName")) $("#cmProviderName").value = selectedProvider;
        if ($("#cmProvider")) $("#cmProvider").value = refM.local ? "ollama" : "openai_compat";
        if ($("#cmBaseUrl")) $("#cmBaseUrl").value = refM.base_url || "";
        if ($("#cmEnvKey")) $("#cmEnvKey").value = refM.api_key_env || "";
        const ek = $("#cmEnvKey"), ak = $("#cmApiKey");
        if (ek) ek.hidden = !!refM.local;
        if (ak) ak.hidden = !!refM.local;
        if ($("#cmModel")) $("#cmModel").focus();
      });
      div.appendChild(btnAddModel);
    }

    const btnManage = document.createElement("button");
    btnManage.className = "btn-drop-action";
    btnManage.innerHTML = `<span>🔑 Manage Keys &amp; Models</span>`;
    btnManage.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = true;
      $("#modelsWrap").hidden = false;
      renderModels();
    });
    div.appendChild(btnManage);
    menu.appendChild(div);
  }

  on("#btnProviderDrop", "click", (e) => {
    e.stopPropagation();
    const mm = $("#modelDropMenu");
    if (mm) mm.hidden = true;
    renderProviderDrop();
    const pm = $("#providerDropMenu");
    if (pm) pm.hidden = !pm.hidden;
  });

  on("#btnModelDrop", "click", (e) => {
    e.stopPropagation();
    const pm = $("#providerDropMenu");
    if (pm) pm.hidden = true;
    renderModelDrop();
    const mm = $("#modelDropMenu");
    if (mm) mm.hidden = !mm.hidden;
  });

  document.addEventListener("click", () => {
    const pm = $("#providerDropMenu");
    if (pm) pm.hidden = true;
    const mm = $("#modelDropMenu");
    if (mm) mm.hidden = true;
  });
  on("#btnAutoMode", "click", () => {
    if (!brain) return;
    if (brain.mode === "manual") send({ type: "set_model", mode: "auto" });
    else send({ type: "set_model", mode: "manual", model_id: brain.manual_model || brain.active });
  });
  on("#chipActive", "click", () => ($("#modelsWrap").hidden = false));
  $$("#modeSeg button, #topModeSeg button").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.mode === "auto") {
      send({ type: "set_model", mode: "auto" });
    } else {
      send({ type: "set_model", mode: "manual", model_id: brain && (brain.manual_model || brain.active) });
    }
  }));
  on("#btnResetCooldowns", "click", () => send({ type: "reset_cooldowns" }));
  on("#btnRestoreDefaults", "click", () => send({ type: "restore_default_models" }));
  on("#btnToggleAddModel", "click", () => {
    const box = $("#customModelBox");
    if (box) box.hidden = !box.hidden;
  });
  on("#btnCancelAddModel", "click", () => {
    const box = $("#customModelBox");
    if (box) box.hidden = true;
  });
  on("#cmProvider", "change", (e) => {
    const isLocal = e.target.value === "ollama";
    const bu = $("#cmBaseUrl");
    if (bu) bu.value = isLocal ? "http://127.0.0.1:11434" : "https://openrouter.ai/api/v1";
    const ek = $("#cmEnvKey"), ak = $("#cmApiKey");
    if (ek) ek.hidden = isLocal;
    if (ak) ak.hidden = isLocal;
  });
  on("#btnSaveCustomModel", "click", () => {
    const data = {
      provider_name: $("#cmProviderName")?.value.trim(),
      label: $("#cmLabel")?.value.trim(),
      provider: $("#cmProvider")?.value || "openai_compat",
      base_url: $("#cmBaseUrl")?.value.trim(),
      model: $("#cmModel")?.value.trim(),
      api_key_env: $("#cmEnvKey")?.value.trim(),
      api_key: $("#cmApiKey")?.value.trim(),
      priority: parseInt($("#cmPriority")?.value || "35", 10),
      vision: !!$("#cmVision")?.checked,
    };
    if ((!data.provider_name && !data.label) || !data.model || !data.base_url) {
      signal("warn", "model", "অনুগ্রহ করে প্ল্যাটফর্মের নাম, Model ID এবং Base URL পূরণ করুন");
      return;
    }
    send({ type: "add_custom_model", data });
    if ($("#cmLabel")) $("#cmLabel").value = "";
    if ($("#cmProviderName")) $("#cmProviderName").value = "";
    if ($("#cmModel")) $("#cmModel").value = "";
    if ($("#cmApiKey")) $("#cmApiKey").value = "";
    if ($("#customModelBox")) $("#customModelBox").hidden = true;
  });
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
  function addMsg(role, text, extra = "", model = "", customTime = "") {
    const box = $("#chatView");
    const el = document.createElement("div");
    el.className = `msg ${role === "user" ? "user" : "bot"} ${extra}`;
    const now = new Date();
    const timeStr = customTime || now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    let metaHtml = "";
    if (role === "assistant" || role === "bot") {
      let displayModel = model;
      if (!displayModel && brain) {
        const act = brain.models?.find((m) => m.id === brain.active) || brain.models?.[0];
        displayModel = act ? (act.model || act.id) : (brain.active || "");
      }
      metaHtml = `
        <div class="msg-meta">
          ${displayModel ? `<span class="msg-model" title="Model: ${displayModel}">⚡ ${displayModel}</span>` : ""}
          <span class="msg-time">${timeStr}</span>
        </div>
      `;
    } else {
      metaHtml = `
        <div class="msg-meta">
          <span class="msg-time">${timeStr}</span>
        </div>
      `;
    }

    el.innerHTML = `<div class="who">${role === "user" ? "You" : "💠 Synthia"}</div><div class="bubble"><div class="bubble-content">${md(text)}</div>${metaHtml}</div>`;
    box.appendChild(el);
    box.scrollTop = box.scrollHeight;
    return el;
  }
  function showTyping(on_) {
    if (on_ && !typingEl) {
      typingEl = addMsg("assistant", "");
      const bc = typingEl.querySelector(".bubble-content");
      if (bc) bc.innerHTML = '<span class="typing"><span></span><span></span><span></span></span>';
      const mm = typingEl.querySelector(".msg-meta");
      if (mm) mm.style.display = "none";
    } else if (!on_ && typingEl) { typingEl.remove(); typingEl = null; }
  }
  function chat(ev) {
    if (ev.role === "user") {
      if (ev.source === "voice") { addMsg("user", `🎙️ ${ev.text}`); stats.voice++; renderAnalytics(); }
      else if (ev.source !== "ui") addMsg("user", `[${ev.source}] ${ev.text}`);
      return;
    }
    showTyping(false);
    addMsg("assistant", ev.text, ev.partial ? "partial" : "", ev.model || ev.model_id);
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
    const pumpRand = () => {
      if (currentAudio !== audio) return;
      if (!audio.paused) window.Core && window.Core.setLevel(0.25 + Math.random() * 0.35);
      speakAnim = requestAnimationFrame(pumpRand);
    };
    speakAnim = requestAnimationFrame(pumpRand);
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
  const histFilters = { pc: "", mobile: "" };

  function loadChatThreadIntoView(threadId, messages) {
    const box = $("#chatView");
    if (!box) return;
    box.querySelectorAll(".msg:not(.welcome-msg)").forEach((m) => m.remove());
    typingEl = null;
    (messages || []).forEach((m) => {
      addMsg(m.role === "user" ? "user" : "assistant", m.content || "", "", "", m.ts || "");
    });
    if (String(threadId || "").startsWith("mob_")) window.__activeMobileThread = threadId;
    else window.__activeThread = threadId || "";
    // Chat ট্যাব সক্রিয় করি
    const rightTabs = document.querySelector('#colRight .tabs[data-tabs="right"]');
    if (rightTabs) {
      rightTabs.querySelectorAll("button[data-tab]").forEach((b) => {
        b.classList.toggle("active", b.dataset.tab === "chatView");
      });
      rightTabs.parentElement.querySelectorAll(":scope > .tab-body").forEach((tb) => {
        tb.classList.toggle("active", tb.id === "chatView");
      });
    }
    renderChatHistory(window.__chatHistory || [], window.__activeThread);
    renderMobileHistory(window.__mobileHistory || [], window.__activeMobileThread);
  }

  function renderThreadList(ul, threads, activeThreadId, filterKey, emptyMsg, iconChar) {
    if (!ul) return;
    const prevFocus = ul.querySelector(".hist-search-inp") === document.activeElement;
    ul.innerHTML = "";
    const list = Array.isArray(threads) ? threads : [];

    const searchLi = document.createElement("li");
    searchLi.className = "hist-search-row";
    const inp = document.createElement("input");
    inp.type = "text";
    inp.className = "hist-search-inp";
    inp.placeholder = filterKey === "mobile" ? "🔍 মোবাইলের কমান্ড খুঁজুন…" : "🔍 পুরনো চ্যাট খুঁজুন…";
    inp.value = histFilters[filterKey] || "";
    inp.addEventListener("input", () => {
      histFilters[filterKey] = inp.value;
      renderThreadList(ul, threads, activeThreadId, filterKey, emptyMsg, iconChar);
    });
    searchLi.appendChild(inp);
    ul.appendChild(searchLi);
    if (prevFocus) {
      inp.focus();
      inp.setSelectionRange(inp.value.length, inp.value.length);
    }

    const q = (histFilters[filterKey] || "").trim().toLowerCase();
    const filtered = q
      ? list.filter((t) =>
          (t.title || "").toLowerCase().includes(q)
          || (t.preview || "").toLowerCase().includes(q)
          || (t.messages || []).some((m) => (m.content || "").toLowerCase().includes(q))
        )
      : list;

    if (!filtered.length) {
      const li = document.createElement("li");
      li.style.borderBottom = "none";
      li.textContent = q ? `"${histFilters[filterKey]}" দিয়ে কোনো হিস্ট্রি পাওয়া যায়নি।` : emptyMsg;
      ul.appendChild(li);
      return;
    }

    filtered.forEach((t) => {
      const li = document.createElement("li");
      li.className = `hist-item ${t.id === activeThreadId ? "active" : ""}`;
      li.innerHTML = `
        <div class="hist-head">
          <div class="hist-title">${iconChar} ${md(t.title || "Conversation")}</div>
          <span class="hist-meta">${t.ts || ""} · ${t.msg_count || 0}</span>
          <button class="hist-del" title="হিস্ট্রি মুছুন">🗑️</button>
        </div>
        <div class="hist-preview"></div>
      `;
      li.querySelector(".hist-preview").textContent = t.preview || "";
      li.querySelector(".hist-del").addEventListener("click", (e) => {
        e.stopPropagation();
        send({ type: "delete_chat_thread", thread_id: t.id });
      });
      li.addEventListener("click", () => {
        send({ type: "load_chat_thread", thread_id: t.id });
      });
      ul.appendChild(li);
    });
  }

  function renderChatHistory(threads, activeThreadId) {
    renderThreadList($("#memList"), threads, activeThreadId, "pc",
      "এখনো কোনো চ্যাট হিস্ট্রি নেই। কথা বললেই এখানে জমা হবে।", "💬");
  }

  function renderMobileHistory(threads, activeThreadId) {
    renderThreadList($("#mobHistList"), threads, activeThreadId, "mobile",
      "এখনো মোবাইল থেকে কোনো কমান্ড দেওয়া হয়নি। ফোনের অ্যাপ থেকে কমান্ড দিলেই এখানে জমা হবে।", "📱");
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

  /* ================= ইনফো মডাল (Memory / Skills / Settings / Help) ================= */
  const escHtml = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function renderMemoryModal() {
    currentInfoModal = "memory";
    setText("#infoTitle", "🧠 Memory & Brain — সংরক্ষিত তথ্য ও স্মৃতি");
    const lm = window.__learningMem || { user: [], memory: [], stats: {} };
    const userItems = Array.isArray(lm.user) ? lm.user : [];
    const envItems = Array.isArray(lm.memory) ? lm.memory : [];
    const notes = Array.isArray(window.__memories) ? window.__memories : [];
    const totalCount = userItems.length + envItems.length + notes.length;

    const renderList = (items, target) => {
      if (!items.length) return `<div class="muted" style="padding:0.6rem 0;">কোনো তথ্য সেভ করা নেই।</div>`;
      return `<ul class="mem-items">${items.map((item, idx) => {
        const txt = typeof item === "string" ? item : (item.note || item.text || JSON.stringify(item));
        const ts = typeof item === "object" && item && item.ts ? `<span class="ts">${escHtml(item.ts)}</span>` : "";
        return `<li class="mem-item">
          <div class="txt">${ts}${escHtml(txt)}</div>
          <button class="btn-sm btn-danger-sm" data-mem-del="${escHtml(target)}" data-mem-idx="${idx}" data-mem-txt="${escHtml(txt)}" title="মুছে ফেলুন">🗑️</button>
        </li>`;
      }).join("")}</ul>`;
    };

    const body = $("#infoBody");
    if (!body) return;
    body.innerHTML = `
      <div class="mem-stats">
        <div class="mem-stat-card"><b>${totalCount}</b><small>মোট সংরক্ষিত স্মৃতি</small></div>
        <div class="mem-stat-card"><b>${userItems.length}</b><small>👤 USER.md · ${escHtml(lm.user_usage || "0/1375 chars")}</small></div>
        <div class="mem-stat-card"><b>${envItems.length}</b><small>💻 MEMORY.md · ${escHtml(lm.memory_usage || "0/2200 chars")}</small></div>
        <div class="mem-stat-card"><b>${notes.length}</b><small>📝 দ্রুত নোটস (Notes)</small></div>
        <div class="mem-stat-card"><b>${lm.stats?.messages ?? 0}</b><small>💬 আর্কাইভ মেসেজ (FTS5)</small></div>
      </div>

      <div class="mem-add-bar">
        <select id="memTargetSel" class="modal-input" style="flex:0 0 21rem;">
          <option value="user">👤 আমার সম্পর্কে (USER.md)</option>
          <option value="memory">💻 পিসি / প্রজেক্ট পরিবেশ (MEMORY.md)</option>
          <option value="notes">📝 দ্রুত নোট (Notes)</option>
        </select>
        <input id="memContentInp" type="text" class="modal-input" placeholder="নতুন তথ্য বা নোট লিখুন (যেমন: আমার প্রিয় ভাষা Python)…" />
        <button id="btnAddMemItem" class="btn-sm btn-accent">➕ সেভ করুন</button>
      </div>

      <div class="mem-sec">
        <div class="mem-sec-hdr">
          <span>👤 আপনার সম্পর্কে তথ্য (USER.md)</span>
          <small class="muted">${escHtml(lm.user_usage || "")}</small>
        </div>
        ${renderList(userItems, "user")}
      </div>

      <div class="mem-sec">
        <div class="mem-sec-hdr">
          <span>💻 পরিবেশ ও সিস্টেম নোট (MEMORY.md)</span>
          <small class="muted">${escHtml(lm.memory_usage || "")}</small>
        </div>
        ${renderList(envItems, "memory")}
      </div>

      <div class="mem-sec">
        <div class="mem-sec-hdr">
          <span>📝 সংরক্ষিত দ্রুত নোটস (Notes)</span>
          <small class="muted">${notes.length}টি নোট</small>
        </div>
        ${renderList(notes, "notes")}
      </div>

      <div class="mem-sec" style="margin-bottom:0;">
        <div class="mem-sec-hdr">
          <span>🔎 পুরনো কথোপকথন অনুসন্ধান (Session Archive)</span>
          <small class="muted">SQLite FTS5</small>
        </div>
        <div class="key-input-row" style="margin-bottom:0.8rem;">
          <input id="sessSearchInp" type="text" class="modal-input" placeholder="পুরনো চ্যাট থেকে শব্দ খুঁজুন (ফাঁকা রেখে চাপলে সাম্প্রতিক মেসেজ দেখাবে)…" />
          <button id="btnSessSearch" class="btn-sm btn-accent">🔎 খুঁজুন</button>
        </div>
        <div id="sessionSearchRes" class="muted" style="font-family:var(--mono);white-space:pre-wrap;line-height:1.55;"></div>
      </div>
    `;

    const doAdd = () => {
      const target = $("#memTargetSel")?.value || "user";
      const content = ($("#memContentInp")?.value || "").trim();
      if (!content) {
        signal("warn", "memory", "অনুগ্রহ করে সেভ করার জন্য কিছু লিখুন");
        return;
      }
      send({ type: "memory_action", action: "add", target, content });
      if ($("#memContentInp")) $("#memContentInp").value = "";
    };
    on("#btnAddMemItem", "click", doAdd);
    on("#memContentInp", "keydown", (e) => { if (e.key === "Enter") doAdd(); });

    body.querySelectorAll("[data-mem-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.getAttribute("data-mem-del");
        const idx = parseInt(btn.getAttribute("data-mem-idx") || "-1", 10);
        const old_text = btn.getAttribute("data-mem-txt") || "";
        send({ type: "memory_action", action: "remove", target, index: idx, old_text });
      });
    });

    const doSearch = () => {
      const q = ($("#sessSearchInp")?.value || "").trim();
      const box = $("#sessionSearchRes");
      if (box) box.textContent = "⏳ খোঁজা হচ্ছে…";
      send({ type: "session_search", query: q });
    };
    on("#btnSessSearch", "click", doSearch);
    on("#sessSearchInp", "keydown", (e) => { if (e.key === "Enter") doSearch(); });

    $("#infoWrap").hidden = false;
  }

  function renderSessionSearchResult(query, result) {
    const box = $("#sessionSearchRes");
    if (!box) return;
    box.textContent = result || "কোনো ফলাফল পাওয়া যায়নি।";
  }

  const CAT_LABELS = {
    all: "🌐 সব স্কিল",
    files: "📁 Files",
    system: "🛡️ System",
    web: "🧭 Browser",
    research: "🔎 Research",
    voice: "🎙️ Voice",
    media: "🎬 Studio",
    remote: "📡 Remote",
    memory: "🧠 Memory",
    learning: "📚 Learning",
    learned: "✨ Learned Skills",
  };

  function renderSkillsModal(filterCat = "all") {
    currentInfoModal = "skills";
    currentSkillFilter = filterCat || "all";
    setText("#infoTitle", "🛠️ Skills & Tools — দক্ষতার তালিকা");

    const toolsDetail = Array.isArray(window.__toolsDetail) ? window.__toolsDetail : [];
    const learned = Array.isArray(window.__learnedSkills) ? window.__learnedSkills : [];

    // যদি toolsDetail না থাকে তবে window.__skills থেকে বেসিক অবজেক্ট বানিয়ে নিই
    const allTools = toolsDetail.length
      ? toolsDetail
      : Object.entries(window.__skills || {}).flatMap(([cat, names]) =>
          names.map((n) => ({ name: n, description: "", category: cat, risk: "safe", params: [], required: [] }))
        );

    const effectiveCat = (t) => TOOL_SQUAD[t.name] || t.category || "other";
    const catCounts = { all: allTools.length + learned.length };
    allTools.forEach((t) => {
      const c = effectiveCat(t);
      catCounts[c] = (catCounts[c] || 0) + 1;
      if (t.category && t.category !== c) {
        catCounts[t.category] = (catCounts[t.category] || 0) + 1;
      }
    });
    catCounts.learned = learned.length;

    const cats = ["all", ...Array.from(new Set(allTools.map(effectiveCat))), "learned"];
    const filteredTools =
      currentSkillFilter === "learned"
        ? []
        : currentSkillFilter === "all"
        ? allTools
        : allTools.filter((t) => effectiveCat(t) === currentSkillFilter || t.category === currentSkillFilter);

    const showLearned = currentSkillFilter === "all" || currentSkillFilter === "learned";

    const body = $("#infoBody");
    if (!body) return;

    body.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:0.8rem;flex-wrap:wrap;margin-bottom:1rem;">
        <div class="skill-cats" style="margin-bottom:0;">
          ${cats.map((c) => `
            <button class="btn-sm ${currentSkillFilter === c ? "btn-accent" : ""}" data-skill-cat="${escHtml(c)}">
              ${escHtml(CAT_LABELS[c] || c)} (${catCounts[c] || 0})
            </button>
          `).join("")}
        </div>
        <button class="btn-sm btn-accent" id="btnToggleCreateSkill">➕ নতুন Skill তৈরি করুন</button>
      </div>

      <div id="createSkillBox" class="custom-model-box" hidden>
        <div class="cm-title">✨ নতুন Learned Skill (SKILL.md) তৈরি বা আপডেট করুন</div>
        <div style="display:grid;gap:0.7rem;">
          <input id="skNameInp" type="text" class="modal-input" placeholder="Skill-এর নাম (ছোট হাতের অক্ষর ও হাইফেন, যেমন: youtube-summary)" />
          <input id="skDescInp" type="text" class="modal-input" placeholder="সংক্ষিপ্ত বিবরণ (কখন ও কী কাজে ব্যবহৃত হবে)" />
          <textarea id="skBodyInp" rows="6" class="modal-input" style="resize:vertical;line-height:1.45;" placeholder="ধাপে ধাপে নির্দেশনা লিখুন (Markdown ফরম্যাটে)…"></textarea>
          <div style="display:flex;justify-content:flex-end;gap:0.6rem;">
            <button class="btn-sm" id="btnCancelCreateSkill">বাতিল</button>
            <button class="btn-sm btn-accent" id="btnSaveSkill">💾 সেভ করুন</button>
          </div>
        </div>
      </div>

      ${showLearned && learned.length ? `
        <div class="mem-sec">
          <div class="mem-sec-hdr"><span>✨ এজেন্টের শেখা কাস্টম স্কিলসমূহ (Learned Skills · ${learned.length})</span></div>
          <div class="skill-grid">
            ${learned.map((s, idx) => `
              <div class="skill-card">
                <div>
                  <div class="skill-card-head">
                    <code>✨ ${escHtml(s.name)}</code>
                    <span class="badge ok">Learned</span>
                  </div>
                  <p style="margin-top:0.4rem;">${escHtml(s.description || "কাস্টম লার্নড স্কিল")}</p>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;">
                  <span class="skill-params">${(s.files || []).length ? `${s.files.length} extra files` : "SKILL.md"}</span>
                  <button class="btn-sm" data-view-learned="${idx}">📄 দেখুন / এডিট</button>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      ` : currentSkillFilter === "learned" ? `<div class="muted" style="padding:1rem 0;">এখনো কোনো Learned Skill তৈরি হয়নি। ওপরে "➕ নতুন Skill তৈরি করুন" বাটনে ক্লিক করে যোগ করতে পারেন।</div>` : ""}

      ${filteredTools.length ? `
        <div class="mem-sec" style="margin-bottom:0;">
          <div class="mem-sec-hdr">
            <span>🛠️ বিল্ট-ইন টুলস ও স্কিল (${filteredTools.length})</span>
            <small class="muted">ক্লিক করে চ্যাটে ব্যবহার করুন</small>
          </div>
          <div class="skill-grid">
            ${filteredTools.map((t) => {
              const cat = effectiveCat(t);
              const isHigh = t.risk === "high" || t.risk === "confirm";
              const paramsTxt = (t.params || []).length
                ? (t.params || []).map((p) => (t.required || []).includes(p) ? `${p}*` : p).join(", ")
                : "কোনো প্যারামিটার লাগে না";
              return `
                <div class="skill-card">
                  <div>
                    <div class="skill-card-head">
                      <code>${escHtml(t.name)}</code>
                      <div style="display:flex;gap:0.35rem;align-items:center;">
                        <span class="badge">${escHtml(cat)}</span>
                        <span class="badge ${isHigh ? "warn" : "ok"}">${isHigh ? "🔒 অনুমতি" : "⚡ অটো"}</span>
                      </div>
                    </div>
                    <p style="margin-top:0.45rem;">${escHtml(t.description || "Synthia সিস্টেম টুল")}</p>
                  </div>
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;margin-top:0.3rem;">
                    <span class="skill-params" title="Parameters">⚙️ ${escHtml(paramsTxt)}</span>
                    <button class="btn-sm" data-try-skill="${escHtml(t.name)}">▶ টেস্ট</button>
                  </div>
                </div>
              `;
            }).join("")}
          </div>
        </div>
      ` : ""}
    `;

    body.querySelectorAll("[data-skill-cat]").forEach((btn) => {
      btn.addEventListener("click", () => renderSkillsModal(btn.getAttribute("data-skill-cat")));
    });

    let editMode = "create";
    on("#btnToggleCreateSkill", "click", () => {
      const box = $("#createSkillBox");
      if (!box) return;
      editMode = "create";
      box.hidden = !box.hidden;
    });
    on("#btnCancelCreateSkill", "click", () => {
      const box = $("#createSkillBox");
      if (box) box.hidden = true;
    });

    body.querySelectorAll("[data-view-learned]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-view-learned") || "-1", 10);
        const item = learned[idx];
        if (!item) return;
        editMode = "edit";
        const box = $("#createSkillBox");
        if (box) box.hidden = false;
        if ($("#skNameInp")) $("#skNameInp").value = item.name || "";
        if ($("#skDescInp")) $("#skDescInp").value = item.description || "";
        const raw = item.content || "";
        const bodyOnly = raw.startsWith("---") && raw.indexOf("\n---", 3) !== -1
          ? raw.slice(raw.indexOf("\n---", 3) + 4).trim()
          : raw;
        if ($("#skBodyInp")) $("#skBodyInp").value = bodyOnly;
      });
    });

    on("#btnSaveSkill", "click", () => {
      const name = ($("#skNameInp")?.value || "").trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-|-$/g, "");
      const desc = ($("#skDescInp")?.value || "").trim();
      const instructions = ($("#skBodyInp")?.value || "").trim();
      if (!name || !desc || !instructions) {
        signal("warn", "skill", "অনুগ্রহ করে নাম, সংক্ষিপ্ত বিবরণ এবং নির্দেশনা পূরণ করুন");
        return;
      }
      const content = `---\nname: ${name}\ndescription: ${desc}\n---\n\n${instructions}\n`;
      send({ type: "skill_action", action: editMode, name, content });
      if ($("#createSkillBox")) $("#createSkillBox").hidden = true;
    });

    body.querySelectorAll("[data-try-skill]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tname = btn.getAttribute("data-try-skill");
        $("#infoWrap").hidden = true;
        if (input) {
          input.value = `${tname} টুলটি ব্যবহার করে `;
          input.focus();
        }
      });
    });

    $("#infoWrap").hidden = false;
  }

  /* ================= স্কোয়াড মোডাল (Dedicated Squad Modals) ================= */
  const SQUAD_INFO = {
    files: {
      id: "files",
      name: "File Squad",
      role: "ফাইল ও ডিরেক্টরি ম্যানেজার",
      ico: "📁",
      badge: "Files",
      desc: "পিসির যেকোনো ফাইল ও ফোল্ডার খোঁজা, পড়া, তৈরি, এক স্থান থেকে অন্য স্থানে সরানো ও সুরক্ষিত রিসাইকেল বিনে পাঠানো।",
      ready: true,
      actions: [
        { ico: "📂", label: "Downloads ফোল্ডারে কি কি আছে দেখুন", cmd: "Downloads ফোল্ডারে কি কি ফাইল আছে দেখাও" },
        { ico: "🖥️", label: "Desktop ফোল্ডারের ফাইলসমূহ দেখুন", cmd: "Desktop ফোল্ডারের সব ফাইলের তালিকা দেখাও" },
        { ico: "🔍", label: "৫০MB-এর বড় ফাইল খুঁজুন", prompt: "Downloads ফোল্ডারে ৫০ মেগাবাইটের বেশি সাইজের ফাইলগুলো খুঁজে বের করো" },
        { ico: "📝", label: "Desktop-এ নতুন নোট ফাইল তৈরি করুন", prompt: "Desktop-এ notes.txt নামে একটি ফাইল তৈরি করো এবং তাতে লিখো " },
        { ico: "🗑️", label: "রিসাইকেল বিনের স্ট্যাটাস দেখুন", cmd: "রিসাইকেল বিনে কি কি ফাইল আছে দেখাও" },
      ],
    },
    system: {
      id: "system",
      name: "System Squad",
      role: "পিসি ও ওএস কন্ট্রোল",
      ico: "🛡️",
      badge: "PC Control",
      desc: "সিস্টেম রিমোট কন্ট্রোল, ব্যাকগ্রাউন্ড প্রসেস পর্যবেক্ষণ, সিপিইউ, র‍্যাম ও ডিস্ক পারফরম্যান্স মেট্রিক্স এবং অ্যাপ্লিকেশন চালু বা বন্ধ করা।",
      ready: true,
      actions: [
        { ico: "📊", label: "CPU, RAM ও ডিস্ক স্ট্যাটাস চেক করুন", cmd: "পিসির CPU, RAM এবং ডিস্ক স্ট্যাটাস চেক করো" },
        { ico: "📱", label: "বর্তমানে চালু থাকা অ্যাপস ও প্রসেস দেখুন", cmd: "বর্তমানে কোন কোন অ্যাপ ও ব্যাকগ্রাউন্ড প্রসেস চলছে দেখাও" },
        { ico: "🧮", label: "ক্যালকুলেটর অ্যাপ চালু করুন", cmd: "ক্যালকুলেটর অ্যাপ চালু করো" },
        { ico: "🔋", label: "পাওয়ার ও ব্যাটারি রিপোর্ট দেখুন", cmd: "পিসির ব্যাটারি ও পাওয়ার স্ট্যাটাস দেখাও" },
        { ico: "🔒", label: "পিসির স্ক্রিন লক করুন", cmd: "পিসি লক করো" },
      ],
    },
    web: {
      id: "web",
      name: "Browser Squad",
      role: "ওয়েব ব্রাউজিং ও অটমেশন",
      ico: "🧭",
      badge: "Web Browser",
      desc: "ডিফল্ট ব্রাউজারে যেকোনো ওয়েবসাইট ওপেন করা, ইউটিউবে ভিডিও ও গান প্লে করা এবং নির্দিষ্ট ওয়েব লিংক তাৎক্ষণিক ব্রাউজারে পরিদর্শন।",
      ready: true,
      actions: [
        { ico: "▶️", label: "ইউটিউবে গান চালান", prompt: "ইউটিউবে একটি রিল্যাক্সিং ব্যাকগ্রাউন্ড মিউজিক বাজাও" },
        { ico: "🌐", label: "Google-এ সার্চ করুন", prompt: "Google-এ সার্চ করে আমাকে বলো: " },
        { ico: "📰", label: "প্রথম আলো ওয়েবসাইট খুলুন", cmd: "https://www.prothomalo.com ব্রাউজারে খোলো" },
        { ico: "💻", label: "GitHub ওয়েবসাইট খুলুন", cmd: "https://github.com ব্রাউজারে খোলো" },
      ],
    },
    research: {
      id: "research",
      name: "Research Squad",
      role: "ডিপ ওয়েব ও তথ্য অনুসন্ধান",
      ico: "🔎",
      badge: "Deep Search",
      desc: "ইন্টারনেটে সার্চ করে যেকোনো বিষয়ের সাম্প্রতিক তথ্য সংগ্রহ, সম্পূর্ণ ওয়েবপেজের আর্টিকেল পড়ে সারসংক্ষেপ তৈরি ও ফ্যাক্ট চেকিং।",
      ready: true,
      actions: [
        { ico: "🔎", label: "ইন্টারনেট থেকে ডিপ রিসার্চ করুন", prompt: "ইন্টারনেট সার্চ করে বিস্তারিত গবেষণা করো: " },
        { ico: "📑", label: "একটি ওয়েবপেজের মূল সারসংক্ষেপ পড়ুন", prompt: "এই ওয়েবপেজের মূল তথ্যগুলোর সারাংশ দাও: " },
        { ico: "💡", label: "তথ্য যাচাই ও ফ্যাক্ট চেক করুন", prompt: "ইন্টারনেটে তথ্য যাচাই করে বিস্তারিত জানাও: " },
        { ico: "📈", label: "আজকের তাজা টেক নিউজ জানুন", prompt: "সাম্প্রতিক এআই এবং প্রযুক্তি জগতের প্রধান খবরগুলোর সারসংক্ষেপ করো" },
      ],
    },
    voice: {
      id: "voice",
      name: "Voice Squad",
      role: "রিয়েলটাইম ভয়েস ও স্পিচ কন্ট্রোল",
      ico: "🎙️",
      badge: "Speech Engine",
      desc: "Synthia ও Jarvis দুটি স্বতন্ত্র ভয়েস পার্সোনা, ভয়েস অ্যাক্টিভিটি ডিটেকশন (VAD) এবং বাংলা ও ইংরেজি রিয়েলটাইম স্পিচ রেসপন্স।",
      ready: true,
      actions: [
        { ico: "🗣️", label: "বাংলা ভয়েস টেস্ট করুন", cmd: "হ্যালো! আপনি কেমন আছেন? আমি সিনথিয়া, আপনার এআই সহকারী। ভয়েস সিস্টেম সঠিকভাবে কাজ করছে।" },
        { ico: "⚡", label: "ভয়েস স্পিড বা পিচ অ্যাডজাস্ট করুন", prompt: "ভয়েসের গতি বা পিচ পরিবর্তন করতে set_voice_options ব্যবহার করো: " },
      ],
    },
    media: {
      id: "media",
      name: "Studio Media Squad",
      role: "ইমেজ ও মাল্টিমিডিয়া ল্যাব",
      ico: "🎬",
      badge: "Coming Soon",
      desc: "এআই ইমেজ জেনারেশন (FLUX / Imagen), স্মার্ট স্ক্রিনশট অ্যানালাইসিস এবং ভিডিও ও অডিও প্রসেসিং ইঞ্জিন।",
      ready: false,
      roadmap: [
        "🎨 টেক্সট-টু-ইমেজ জেনারেশন (FLUX, Imagen 3, Stable Diffusion)",
        "📸 লাইভ স্ক্রিনশট ও মাল্টিমোডাল ভিশন বিশ্লেষণ",
        "🎵 অডিও ও ব্যাকগ্রাউন্ড সাউন্ডট্র্যাক ক্রিয়েশন",
        "🎬 অটোমেটিক সাবটাইটেল ও ভিডিও ক্লিপ জেনারেশন",
      ],
    },
    remote: {
      id: "remote",
      name: "Remote Mobile App",
      role: "ফোন অ্যাপ ও ওয়াই-ফাই কন্ট্রোল",
      ico: "📡",
      badge: "Ready",
      desc: "একই Wi-Fi নেটওয়ার্কে থাকা আপনার অ্যান্ড্রয়েড ফোন (SynthiaMobile.apk) থেকে ভয়েস ও টেক্সট কমান্ড দিয়ে পিসি নিয়ন্ত্রণ করুন।",
      ready: true,
    },
  };

  function getSquadTools(squadId) {
    const toolsDetail = Array.isArray(window.__toolsDetail) ? window.__toolsDetail : [];
    const allTools = toolsDetail.length
      ? toolsDetail
      : Object.entries(window.__skills || {}).flatMap(([cat, names]) =>
          names.map((n) => ({ name: n, description: "", category: cat, risk: "safe", params: [], required: [] }))
        );
    const effectiveCat = (t) => TOOL_SQUAD[t.name] || t.category || "other";

    if (squadId === "files") {
      return allTools.filter((t) => effectiveCat(t) === "files" || t.category === "files");
    }
    if (squadId === "system") {
      return allTools.filter((t) => effectiveCat(t) === "system" || t.category === "system");
    }
    if (squadId === "web") {
      return allTools.filter((t) => (effectiveCat(t) === "web" || t.category === "web") && effectiveCat(t) !== "research");
    }
    if (squadId === "research") {
      return allTools.filter((t) => effectiveCat(t) === "research" || TOOL_SQUAD[t.name] === "research");
    }
    if (squadId === "voice") {
      return allTools.filter((t) => effectiveCat(t) === "voice" || t.category === "voice");
    }
    return [];
  }

  function renderSquadModal(squadId) {
    const info = SQUAD_INFO[squadId];
    if (!info) {
      renderSkillsModal("all");
      return;
    }
    currentInfoModal = "squad:" + squadId;
    setText("#infoTitle", `${info.ico} ${info.name} — ${info.role}`);

    const tools = getSquadTools(squadId);
    const isReady = info.ready && (tools.length > 0 || squadId === "voice" || squadId === "remote");

    const body = $("#infoBody");
    if (!body) return;

    let html = `
      <div class="squad-hero">
        <div class="squad-hero-left">
          <div class="squad-hero-icon">${info.ico}</div>
          <div>
            <div class="squad-hero-title">
              <span>${escHtml(info.name)}</span>
              ${isReady 
                ? `<span class="badge ok">● Ready · ${tools.length ? tools.length + "টি টুল সক্রিয়" : "সক্রিয়"}</span>`
                : `<span class="badge" style="background:rgba(255,255,255,0.08);color:var(--text-dim);">⏳ Coming Soon</span>`}
            </div>
            <div class="squad-hero-desc">${escHtml(info.desc)}</div>
          </div>
        </div>
      </div>
    `;

    if (squadId === "remote") {
      const mb = window.__mobile || {};
      const ips = Array.isArray(mb.lan_ips) ? mb.lan_ips : [];
      const primary = mb.primary_ip || "127.0.0.1";
      const port = mb.port || 8765;
      const tok = mb.token || TOKEN || "";
      const apkUrl = mb.apk_url || `http://${primary}:${port}/apk`;
      const mobUrl = mb.mobile_url || `http://${primary}:${port}/mobile?token=${encodeURIComponent(tok)}`;
      html += `
        <div class="mem-sec">
          <div class="mem-sec-hdr">
            <span>📱 ফোনে Synthia মোবাইল অ্যাপ কানেক্ট করুন</span>
            <small class="muted">${mb.apk_ready ? "SynthiaMobile.apk প্রস্তুত" : "APK তৈরি হচ্ছে"}</small>
          </div>
          <div style="display:grid;gap:0.75rem;font-size:1.25rem;line-height:1.55;">
            <div><b>Wi-Fi IP Address:</b> <code>${escHtml(primary)}:${port}</code> ${ips.length > 1 ? `<small class="muted">(অন্যান্য: ${escHtml(ips.slice(1).join(", "))})</small>` : ""}</div>
            <div><b>Pair Token:</b> <code style="user-select:all;">${escHtml(tok)}</code></div>
            <div><b>ফোন ব্রাউজার থেকে APK ডাউনলোড লিংক:</b><br/><code style="user-select:all;">${escHtml(apkUrl)}</code></div>
            <div><b>মোবাইল ওয়েব লিংক:</b><br/><code style="user-select:all;">${escHtml(mobUrl)}</code></div>
          </div>
        </div>
      `;
    }

    if (squadId === "voice") {
      const p = voiceState.persona;
      const micOn = !!voiceState.mic_on;
      const muted = !!voiceState.muted;
      html += `
        <div class="mem-sec">
          <div class="mem-sec-hdr">
            <span>🎛️ লাইভ ভয়েস কন্ট্রোল (Synthia & Jarvis)</span>
            <small class="muted">এখানে ক্লিক করে সরাসরি ভয়েস পার্সোনা বা মাইক পরিবর্তন করুন</small>
          </div>
          <div class="squad-voice-box">
            <button class="btn-sm ${p === 'female' ? 'btn-accent' : ''}" id="sqVoiceSynthia">👩 Synthia (Female Voice)</button>
            <button class="btn-sm ${p === 'male' ? 'btn-accent' : ''}" id="sqVoiceJarvis">🤖 Jarvis (Male Voice)</button>
            <button class="btn-sm ${micOn ? 'btn-accent' : ''}" id="sqToggleMic">${micOn ? '🎙️ Mic: On' : '🔇 Mic: Off'}</button>
            <button class="btn-sm ${muted ? 'muted-btn' : ''}" id="sqToggleMute">${muted ? '🔇 Muted' : '🔊 Speaker On'}</button>
          </div>
        </div>
      `;
    }

    if (info.actions && info.actions.length) {
      html += `
        <div class="mem-sec">
          <div class="mem-sec-hdr">
            <span>⚡ ১-ক্লিক কুইক কমান্ড (Quick Actions)</span>
            <small class="muted">ক্লিক করলে সাথে সাথে অ্যাকশন চালু বা ইনপুটে সেট হবে</small>
          </div>
          <div class="squad-actions-grid">
            ${info.actions.map((act, i) => `
              <button class="squad-act-btn" data-act-idx="${i}">
                <span class="act-ico">${act.ico}</span>
                <span class="act-txt">${escHtml(act.label)}</span>
              </button>
            `).join("")}
          </div>
        </div>
      `;
    }

    if (!isReady && info.roadmap) {
      html += `
        <div class="squad-coming-card">
          <div class="c-icon">${info.ico}</div>
          <h3>${escHtml(info.name)} — নির্মাণাধীন রয়েছে</h3>
          <p>${escHtml(info.desc)} এই ফিচারটি পরবর্তী আপডেটে সম্পূর্ণ সক্রিয় হয়ে যুক্ত হবে।</p>
          <div class="squad-roadmap-list">
            ${info.roadmap.map((item) => `
              <div class="squad-roadmap-item">✨ ${escHtml(item)}</div>
            `).join("")}
          </div>
        </div>
      `;
    }

    if (tools.length) {
      html += `
        <div class="mem-sec" style="margin-bottom:0;">
          <div class="mem-sec-hdr">
            <span>🛠️ ${escHtml(info.name)}-এর সক্রিয় টুলস ও ক্ষমতা (${tools.length})</span>
            <small class="muted">ক্লিক করে চ্যাটে সরাসরি কমান্ড দিন</small>
          </div>
          <div class="skill-grid">
            ${tools.map((t) => {
              const isHigh = t.risk === "high" || t.risk === "confirm";
              const paramsTxt = (t.params || []).length
                ? (t.params || []).map((p) => (t.required || []).includes(p) ? `${p}*` : p).join(", ")
                : "কোনো প্যারামিটার লাগে না";
              return `
                <div class="skill-card">
                  <div>
                    <div class="skill-card-head">
                      <code>${escHtml(t.name)}</code>
                      ${isHigh ? '<span class="badge warn">⚠️ অনুমতি লাগবে</span>' : '<span class="badge ok">⚡ স্বয়ংক্রিয়</span>'}
                    </div>
                    <p style="margin-top:0.4rem;">${escHtml(t.description || "এই টুলটির সাহায্যে সিস্টেম স্বয়ংক্রিয়ভাবে কাজ সম্পন্ন করে।")}</p>
                  </div>
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:0.5rem;margin-top:0.6rem;">
                    <span class="skill-params" title="প্যারামিটার: ${escHtml(paramsTxt)}">⚙️ ${escHtml(paramsTxt)}</span>
                    <button class="btn-sm" data-try-squad-tool="${escHtml(t.name)}">▶️ চ্যাটে ব্যবহার</button>
                  </div>
                </div>
              `;
            }).join("")}
          </div>
        </div>
      `;
    }

    html += `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:1.5rem;padding-top:1rem;border-top:1px solid var(--line);flex-wrap:wrap;gap:0.8rem;">
        <small class="muted">💡 টিপস: আপনি চ্যাটে সাধারণ বাংলা বা ইংরেজিতে বললেই Synthia স্বয়ংক্রিয়ভাবে সঠিক স্কোয়াড ও টুল বেছে নেয়।</small>
        <button class="btn-sm" id="btnSquadGoAllSkills">📂 সব স্কিল ডিরেক্টরি (All Skills)</button>
      </div>
    `;

    body.innerHTML = html;

    if (squadId === "voice") {
      on("#sqVoiceSynthia", "click", () => {
        send({ type: "voice_persona", persona: "female" });
        voiceState.persona = "female";
        renderSquadModal("voice");
      });
      on("#sqVoiceJarvis", "click", () => {
        send({ type: "voice_persona", persona: "male" });
        voiceState.persona = "male";
        renderSquadModal("voice");
      });
      on("#sqToggleMic", "click", () => {
        const next = !voiceState.mic_on;
        send({ type: "mic", enabled: next });
        voiceState.mic_on = next;
        renderSquadModal("voice");
      });
      on("#sqToggleMute", "click", () => {
        const next = !voiceState.muted;
        send({ type: "mute", muted: next });
        voiceState.muted = next;
        renderSquadModal("voice");
      });
    }

    if (info.actions && info.actions.length) {
      body.querySelectorAll(".squad-act-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = parseInt(btn.getAttribute("data-act-idx"), 10);
          const act = info.actions[idx];
          if (!act) return;
          $("#infoWrap").hidden = true;
          if (act.cmd) {
            submit(act.cmd);
          } else if (act.prompt) {
            if (input) {
              input.value = act.prompt;
              input.focus();
            }
          }
        });
      });
    }

    body.querySelectorAll("[data-try-squad-tool]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tname = btn.getAttribute("data-try-squad-tool");
        $("#infoWrap").hidden = true;
        if (input) {
          input.value = `${tname} টুলটি ব্যবহার করে `;
          input.focus();
        }
      });
    });

    on("#btnSquadGoAllSkills", "click", () => renderSkillsModal("all"));

    $("#infoWrap").hidden = false;
  }

  function openInfo(k, sub) {
    if (k === "models") { $("#modelsWrap").hidden = false; return; }
    if (k === "memory") { renderMemoryModal(); return; }
    if (k === "skills") { renderSkillsModal(sub || "all"); return; }
    if (k && k.startsWith("squad:")) { renderSquadModal(k.slice(6)); return; }
    currentInfoModal = k || "";
    let title = "", body = "";
    if (k === "help") {
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
    if (b.dataset.open) openInfo(b.dataset.open);
    else if (b.dataset.cmd) submit(b.dataset.cmd);
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
