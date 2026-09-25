/* ============================================================
   FleetNet Dashboard — front-end controller
   The Python engine is authoritative; this only views + controls.
   ============================================================ */
"use strict";

const STATUS_COLORS = {
  active: "#047857", waiting: "#B45309", rerouting: "#C2410C",
  charging: "#B45309", "comms-lost": "#0E7490", idle: "#64748b",
  parked: "#5B6B85", error: "#DC2626", stranded: "#DC2626",
};

const S = {
  ws: null,
  layout: null,
  frames: [],              // benchmark: paired {stack, stopwait, cmp}; else {stack}
  view: "live",            // 'live' | 'replay'
  replayCursor: 0,
  replayPlaying: false,
  speed: 1,
  running: false,
  benchmark: false,
  armed: null,             // null | 'box' | 'zone'
  dragStart: null,

  editMode: false,
  editTool: "blocked",
  editBuffer: null,
  editPainting: false,
  editHover: null,
  editLayoutId: null,      // saved-library id a re-Apply should update in place, or null = new
  savedLayouts: [],
};

const TOOL_FIELD = { blocked: "blocked", pickup: "pickups", dropoff: "dropoffs",
                     charger: "chargers", depot: "depot" };

const $ = (id) => document.getElementById(id);
const lerp = (a, b, t) => a + (b - a) * t;
const clamp01 = (x) => Math.max(0, Math.min(1, x));

let _toastTimer = null;
function toast(msg, ms = 2600) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  requestAnimationFrame(() => el.classList.add("show"));
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => { el.hidden = true; }, 200);
  }, ms);
}

/* ============================================================ Arena
   One canvas + its own draw state.  Instantiated once for the stack and,
   in benchmark mode, once more for the stop-and-wait baseline.
   ============================================================ */
class Arena {
  constructor(canvasId, bannerId) {
    this.cv = $(canvasId);
    this.ctx = this.cv.getContext("2d");
    this.bannerEl = bannerId ? $(bannerId) : null;
    this.CELL = 12;
    this.DPR = 1;
    this.layout = null;
    this.rackRects = [];
    this.prev = null;
    this.cur = null;
    this.curAt = 0;
    this.interval = 100;
    this.dashPhase = 0;
    this.heat = false;
  }

  setLayout(layout) {
    this.layout = layout;
    this.prev = this.cur = null;
    this.buildRacks();
    this.size();
  }

  buildRacks() {
    const { w, h, obstacles } = this.layout;
    const grid = Array.from({ length: h }, () => new Uint8Array(w));
    for (const [x, y] of obstacles) grid[y][x] = 1;
    const rects = [];
    for (let y = 1; y < h - 1; y++) {
      let x = 1;
      while (x < w - 1) {
        if (grid[y][x]) {
          let x2 = x;
          while (x2 < w - 1 && grid[y][x2]) x2++;
          rects.push({ x, y, w: x2 - x, h: 1 });
          x = x2;
        } else x++;
      }
    }
    this.rackRects = rects;
  }

  size() {
    if (!this.layout) return;
    const shell = this.cv.parentElement;
    const cssW = shell.clientWidth;
    if (!cssW) return;
    const cssH = cssW * (this.layout.h / this.layout.w);
    this.DPR = Math.min(2, window.devicePixelRatio || 1);
    this.cv.width = Math.round(cssW * this.DPR);
    this.cv.height = Math.round(cssH * this.DPR);
    this.cv.style.height = cssH + "px";
    this.CELL = this.cv.width / this.layout.w;
  }

  px(cx) { return cx * this.CELL; }

  /* live: EMA the inter-frame interval so motion interpolates smoothly */
  pushFrame(f) {
    const now = performance.now();
    if (this.cur) this.interval = this.interval * 0.7 + Math.min(400, now - this.curAt) * 0.3;
    this.prev = this.cur || f;
    this.cur = f;
    this.curAt = now;
  }

  drawLive() {
    if (!this.layout || !this.cur) return;
    const t = clamp01((performance.now() - this.curAt) / this.interval);
    this._render(this.prev, this.cur, t);
  }

  drawReplay(A, B, t) {
    if (!this.layout || !B) return;
    this._render(A || B, B, t);
  }

  _render(A, B, t) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.cv.width, this.cv.height);
    this._floor();
    if (this.heat) this._heat(B);
    this._depot();
    this._stations();
    this._deadZones(B);
    this._obstacles(B);
    this._paths(B);
    this._robots(A, B, t);
    if (this.bannerEl) this.bannerEl.hidden = B.dashboard;
  }

  _floor(rects = this.rackRects) {
    const { w, h } = this.layout, ctx = this.ctx;
    ctx.fillStyle = "#F1F4F8";
    ctx.fillRect(0, 0, this.cv.width, this.cv.height);
    ctx.strokeStyle = "#E2E7EF"; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0; x <= w; x += 2) { ctx.moveTo(this.px(x), 0); ctx.lineTo(this.px(x), this.px(h)); }
    for (let y = 0; y <= h; y += 2) { ctx.moveTo(0, this.px(y)); ctx.lineTo(this.px(w), this.px(y)); }
    ctx.stroke();
    ctx.strokeStyle = "#64748B"; ctx.lineWidth = Math.max(2, this.CELL * 0.5);
    ctx.strokeRect(this.px(0.5), this.px(0.5), this.px(w - 1), this.px(h - 1));
    for (const r of rects) {
      this._roundRect(this.px(r.x) + 1, this.px(r.y) + 1, this.px(r.w) - 2, this.px(r.h) - 2, 3);
      ctx.fillStyle = "#CBD5E1"; ctx.fill();
      ctx.fillStyle = "#94A3B8"; ctx.fillRect(this.px(r.x) + 1, this.px(r.y) + 1, this.px(r.w) - 2, 2);
    }
  }

  _heat(f) {
    const ctx = this.ctx;
    ctx.save();
    for (const rb of f.robots) {
      if (!rb.alive) continue;
      const g = ctx.createRadialGradient(this.px(rb.pos[0] + 0.5), this.px(rb.pos[1] + 0.5), 0,
        this.px(rb.pos[0] + 0.5), this.px(rb.pos[1] + 0.5), this.CELL * 3);
      g.addColorStop(0, "rgba(245,158,11,.16)");
      g.addColorStop(1, "rgba(245,158,11,0)");
      ctx.fillStyle = g;
      ctx.fillRect(this.px(rb.pos[0] - 2.5), this.px(rb.pos[1] - 2.5), this.CELL * 6, this.CELL * 6);
    }
    ctx.restore();
  }

  _depot(d = this.layout.depot) {
    if (!d || !d.length) return;
    const ctx = this.ctx, C = this.CELL;
    const xs = d.map(p => p[0]), ys = d.map(p => p[1]);
    const x0 = Math.min(...xs), y0 = Math.min(...ys);
    const w = Math.max(...xs) - x0 + 1, h = Math.max(...ys) - y0 + 1;
    const bx = this.px(x0 - 0.18), by = this.px(y0 - 0.18);
    const bw = this.px(w + 0.36), bh = this.px(h + 0.36);
    ctx.fillStyle = "rgba(148,163,184,.07)";
    ctx.fillRect(bx, by, bw, bh);
    ctx.strokeStyle = "rgba(148,163,184,.5)"; ctx.lineWidth = 1.1;
    ctx.setLineDash([5, 3]); ctx.strokeRect(bx, by, bw, bh); ctx.setLineDash([]);
    ctx.fillStyle = "#475569";
    ctx.font = `600 ${Math.max(8, C * 0.4)}px Inter, system-ui, sans-serif`;
    ctx.textAlign = "left"; ctx.textBaseline = "bottom";
    ctx.fillText("STANDBY DEPOT", bx, by - 2);
    d.forEach(([sx, sy], i) => {
      this._roundRect(this.px(sx) + C * 0.15, this.px(sy) + C * 0.15, C * 0.7, C * 0.7, 3);
      ctx.strokeStyle = "#64748B"; ctx.lineWidth = 1.1; ctx.stroke();
      ctx.fillStyle = "rgba(100,116,139,.12)"; ctx.fill();
      ctx.fillStyle = "#475569";
      ctx.font = `${C * 0.34}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(String(i + 1), this.px(sx + 0.5), this.px(sy + 0.56));
    });
  }

  _stations(pickups = this.layout.pickups, dropoffs = this.layout.dropoffs,
            chargers = this.layout.chargers) {
    const ctx = this.ctx, C = this.CELL;
    const mark = (list, color) => {
      for (const [x, y] of list) {
        this._roundRect(this.px(x) + C * 0.12, this.px(y) + C * 0.12, C * 0.76, C * 0.76, 3);
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
        ctx.fillStyle = color + "22"; ctx.fill();
      }
    };
    mark(pickups, "#16A34A");
    mark(dropoffs, "#2563EB");
    for (const [x, y] of chargers) {
      this._roundRect(this.px(x) + C * 0.12, this.px(y) + C * 0.12, C * 0.76, C * 0.76, 3);
      ctx.fillStyle = "#f59e0b"; ctx.fill();
      ctx.fillStyle = "#241a05"; ctx.font = `${C * 0.6}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("⚡", this.px(x + 0.5), this.px(y + 0.58));
    }
  }

  _deadZones(f) {
    const ctx = this.ctx, C = this.CELL;
    for (const [x, y, w, h] of f.dead_zones) {
      ctx.fillStyle = "rgba(245,158,11,.09)";
      ctx.fillRect(this.px(x), this.px(y), this.px(w), this.px(h));
      ctx.strokeStyle = "rgba(245,158,11,.7)"; ctx.lineWidth = 1.4;
      ctx.setLineDash([6, 4]); ctx.strokeRect(this.px(x), this.px(y), this.px(w), this.px(h)); ctx.setLineDash([]);
      ctx.fillStyle = "#92400E"; ctx.font = `600 ${Math.max(9, C * 0.5)}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "left"; ctx.textBaseline = "top";
      ctx.fillText("WI-FI DEAD ZONE", this.px(x) + 4, this.px(y) + 4);
    }
  }

  _obstacles(f) {
    const ctx = this.ctx, C = this.CELL;
    for (const [x, y] of f.obstacles) {
      this._roundRect(this.px(x) + C * 0.14, this.px(y) + C * 0.14, C * 0.72, C * 0.72, 3);
      ctx.fillStyle = "#ef4444"; ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = `700 ${C * 0.5}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("!", this.px(x + 0.5), this.px(y + 0.55));
    }
  }

  /* ------------------------------------------------------------ editor */
  drawEditorFrame(buf, hoverCell, hoverTool) {
    if (!this.layout || !buf) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.cv.width, this.cv.height);
    this._floor([]);                       // grid + border only, no old racks
    this._depot(buf.depot);
    this._stations(buf.pickups, buf.dropoffs, buf.chargers);
    this._editBlocked(buf.blocked);
    if (hoverCell) this._paintCursor(hoverCell, hoverTool);
  }

  _editBlocked(cells) {
    const ctx = this.ctx, C = this.CELL;
    for (const [x, y] of cells) {
      this._roundRect(this.px(x) + 1, this.px(y) + 1, C - 2, C - 2, 2);
      ctx.fillStyle = "#CBD5E1"; ctx.fill();
      ctx.strokeStyle = "#94A3B8"; ctx.lineWidth = 1; ctx.stroke();
    }
  }

  _paintCursor([x, y], tool) {
    const ctx = this.ctx, C = this.CELL;
    const colors = { blocked: "#3B82F6", pickup: "#16A34A", dropoff: "#2563EB",
                     charger: "#f59e0b", depot: "#64748B", erase: "#ef4444" };
    ctx.strokeStyle = colors[tool] || "#3B82F6";
    ctx.lineWidth = 2;
    ctx.strokeRect(this.px(x) + 1, this.px(y) + 1, C - 2, C - 2);
  }

  _paths(f) {
    const ctx = this.ctx, C = this.CELL;
    this.dashPhase = (this.dashPhase + 0.4) % 16;
    for (const rb of f.robots) {
      if (!rb.path || rb.path.length < 2) continue;
      ctx.strokeStyle = rb.color + "88"; ctx.lineWidth = Math.max(1.5, C * 0.14);
      ctx.lineJoin = "round"; ctx.lineCap = "round";
      ctx.setLineDash([C * 0.5, C * 0.4]); ctx.lineDashOffset = -this.dashPhase;
      ctx.beginPath();
      ctx.moveTo(this.px(rb.path[0][0] + 0.5), this.px(rb.path[0][1] + 0.5));
      for (const [x, y] of rb.path) ctx.lineTo(this.px(x + 0.5), this.px(y + 0.5));
      ctx.stroke(); ctx.setLineDash([]);
    }
  }

  _robots(A, B, t) {
    const ctx = this.ctx, C = this.CELL;
    const byId = {};
    if (A) for (const r of A.robots) byId[r.id] = r;
    for (const rb of B.robots) {
      const a = byId[rb.id] || rb;
      const x = this.px(lerp(a.pos[0], rb.pos[0], t));
      const y = this.px(lerp(a.pos[1], rb.pos[1], t));
      const s = STATUS_COLORS[rb.mode] || "#64748b";
      const rad = C * 0.36;

      if (rb.mode === "comms-lost") {
        ctx.strokeStyle = s + "55"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(x, y, C * 1.6, 0, 7); ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(x, y, rad + 3, 0, 7);
      ctx.strokeStyle = s; ctx.lineWidth = 2.4; ctx.stroke();

      ctx.beginPath(); ctx.arc(x, y, rad, 0, 7);
      ctx.fillStyle = rb.alive ? rb.color : "#94A3B8"; ctx.fill();
      ctx.strokeStyle = "#1E293B"; ctx.lineWidth = 1.5; ctx.stroke();

      ctx.fillStyle = "#fff"; ctx.font = `700 ${C * 0.42}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(rb.name.split("-")[1], x, y + 0.5);
    }
  }

  _roundRect(x, y, w, h, r) {
    const ctx = this.ctx;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
}

let arenaStack = null;
let arenaStopwait = null;

function ensureStopwaitArena() {
  if (!arenaStopwait) arenaStopwait = new Arena("mapStopwait", "mapBannerStopwait");
  return arenaStopwait;
}

/* ---------------------------------------------------------------- socket */
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  S.ws = new WebSocket(`${proto}://${location.host}/ws`);
  S.ws.onopen = () => {};
  S.ws.onclose = () => { setTimeout(connect, 1200); };
  S.ws.onmessage = (e) => dispatch(JSON.parse(e.data));
}

function dispatch(msg) {
  if (msg.type === "layout") onLayout(msg);
  else if (msg.type === "frame") onFrame(msg.data);
  else if (msg.type === "status") onStatus(msg);
  else if (msg.type === "export") onExport(msg);
}

/* ---------------------------------------------------------------- layout */
function onLayout(msg) {
  S.layout = msg.data;
  S.benchmark = !!msg.benchmark;
  S.frames = [];
  S.view = "live"; S.replayCursor = 0; S.replayPlaying = false;
  setLiveBtn();
  S.speed = msg.speed || 1; markSpeed();

  arenaStack.setLayout(msg.data);
  if (S.benchmark) ensureStopwaitArena().setLayout(msg.data);
  applyBenchLayout();

  const cfg = msg.data.config;
  $("cfgRobots").value = cfg.n_robots;
  $("cfgTasks").value = cfg.n_tasks;
  $("cfgSeed").value = cfg.seed;
  $("cfgRobots").max = msg.data.max_robots;
  $("cfgTasks").max = msg.data.max_tasks;
  $("benchToggle").checked = S.benchmark;
  $("arenaTitleStack").textContent = S.benchmark
    ? "Fleet Map — 5-Layer Stack" : "Fleet Map — Warehouse Layout";
}

function applyBenchLayout() {
  document.querySelectorAll(".bench-only").forEach((el) => { el.hidden = !S.benchmark; });
  $("content").classList.toggle("benchmark", S.benchmark);
  requestAnimationFrame(() => {
    arenaStack.size();
    if (S.benchmark && arenaStopwait) arenaStopwait.size();
  });
}

/* ---------------------------------------------------------------- frames */
const FRAME_CAP = () => (S.benchmark ? 4000 : 6000);

function onFrame(d) {
  arenaStack.pushFrame(d.stack);
  if (S.benchmark && d.stopwait) ensureStopwaitArena().pushFrame(d.stopwait);

  S.frames.push(d);
  if (S.frames.length > FRAME_CAP()) S.frames.shift();

  $("scrub").max = S.frames.length - 1;
  if (S.view === "live") {
    $("scrub").value = S.frames.length - 1;
    renderPanels(d.stack);
    if (S.benchmark && d.cmp) renderScoreboard(d.cmp);
  }
  $("replayHint").textContent = `${S.frames.length} frames buffered`;
}

function onStatus(msg) {
  if ("running" in msg) { S.running = msg.running; setSimStatus(msg.running); }
  if ("speed" in msg && msg.speed) { S.speed = msg.speed; markSpeed(); }
  if (msg.note) $("replayHint").textContent = msg.note;
}

function setSimStatus(running) {
  $("btnStart").querySelector(".lbl").textContent = running ? "Pause" : "Start";
  $("btnStart").classList.toggle("is-running", running);
  $("simStatusPill").classList.toggle("paused", !running);
  $("simStatusTitle").textContent = running ? "Simulation Running" : "Simulation Paused";
  $("simStatusSub").textContent = running ? "Fleet operating normally" : "Press Start to begin";
}

/* ---------------------------------------------------------------- draw loop */
function draw() {
  requestAnimationFrame(draw);
  if (!S.layout) return;

  if (S.editMode) {
    arenaStack.drawEditorFrame(S.editBuffer, S.editHover, S.editTool);
    return;
  }
  if (!arenaStack.cur) return;

  if (S.view === "replay" && S.frames.length) {
    if (S.replayPlaying) {
      S.replayCursor += (S.speed * (16.7 / Math.max(1, arenaStack.interval)));
      if (S.replayCursor >= S.frames.length - 1) {
        S.replayCursor = S.frames.length - 1;
        S.replayPlaying = false;
        $("btnReplayPlay").textContent = "Play";
      }
      $("scrub").value = Math.round(S.replayCursor);
    }
    const i = Math.floor(S.replayCursor);
    const A = S.frames[i];
    const B = S.frames[Math.min(i + 1, S.frames.length - 1)];
    const t = S.replayCursor - i;
    const shown = S.frames[Math.round(S.replayCursor)] || S.frames[0];
    renderPanels(shown.stack);
    if (S.benchmark && shown.cmp) renderScoreboard(shown.cmp);
    arenaStack.drawReplay(A && A.stack, B && B.stack, t);
    if (S.benchmark && arenaStopwait) arenaStopwait.drawReplay(A && A.stopwait, B && B.stopwait, t);
  } else {
    arenaStack.drawLive();
    if (S.benchmark && arenaStopwait) arenaStopwait.drawLive();
  }
}

window.addEventListener("resize", () => {
  if (arenaStack) arenaStack.size();
  if (arenaStopwait) arenaStopwait.size();
});

/* ---------------------------------------------------------------- panels */
function renderPanels(f) {
  if (!f) return;
  const k = f.kpi;
  $("simTime").textContent = `t = ${f.sim_time_s.toFixed(1)} s`;
  S.hasProgress = k.completed > 0 || k.active_tasks > 0;

  renderFleetHealth(f);
  renderRobots(f);
  renderCoordination(f);
  renderFleetLog(f);
  renderSystemHealth(f);
  renderTaskProgress(f);
  renderTaskAllocation(f);
  renderSummary(f);
  populateSelects(f);
}

function renderFleetHealth(f) {
  const k = f.kpi, c = k.count;
  const online = f.robots.filter(r => r.alive).length;
  const faulted = (c.error || 0) + (c.stranded || 0);
  const chip = (color, label, n) =>
    `<span class="fh-chip"><i class="dot" style="background:${color}"></i>${label} — ${n}</span>`;
  const avgTime = k.avg_completion_s == null ? "—" : `${k.avg_completion_s}s`;
  $("fleetHealth").innerHTML = `
    <div class="fh-group">
      <div class="fh-label">Robots Online</div>
      <div class="fh-big">${online}/${f.robots.length}</div>
      <div class="fh-breakdown">
        ${chip("#047857", "Active", c.active)}
        ${chip("#64748B", "Idle", c.idle)}
        ${chip("#B45309", "Charging", c.charging)}
        ${chip("#DC2626", "Faulted", faulted)}
      </div>
    </div>
    <div class="fh-group">
      <div class="fh-label">Tasks</div>
      <div class="fh-big">${k.completed}/${k.total}</div>
      <div class="fh-sub">${k.active_tasks} active · ${k.queued_tasks} queued</div>
    </div>
    <div class="fh-group">
      <div class="fh-label">Avg Task Time</div>
      <div class="fh-big">${avgTime}</div>
      <div class="fh-sub"></div>
    </div>
    <div class="fh-group">
      <div class="fh-label">Safety</div>
      <div class="fh-big">${k.avoided}<small> resolved</small></div>
      <div class="fh-sub">0 collisions · ${k.near_miss} near-misses</div>
    </div>`;
}

function renderCoordination(f) {
  const a = f.activity, k = f.kpi;
  const row = (icon, label, val, tip, mesh) => `
    <div class="act${mesh ? " mesh" : ""}" title="${tip}">
      <div class="ic"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke-width="2">${ACT_ICONS[icon]}</svg></div>
      <div class="body"><div class="k">${label}</div><div class="v">${val}</div></div>
    </div>`;
  $("coordBody").innerHTML =
    row("orca", "Robots avoiding each other", a.avoiding_now,
        "NH-ORCA: reciprocal local collision avoidance between nearby robots.") +
    row("route", "Rerouting now", (f.kpi.count.rerouting || 0),
        "D* Lite: replanning a robot's route around a new obstacle.") +
    row("check", "Conflicts resolved (total)", k.avoided,
        "Avoidance manoeuvres the fleet has completed without a collision.") +
    row("mesh", "Deadlock time", `${k.deadlock_robot_s.toFixed(1)}s`,
        "Total robot-seconds spent unable to make progress.", true);
}

function renderSystemHealth(f) {
  const row = (label, iconPath, status, text) => `
    <div class="sh-row">
      <span class="lbl"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke-width="2">${iconPath}</svg>${label}</span>
      <span class="sh-status ${status}"><span class="dot"></span>${text}</span>
    </div>`;
  const wsOk = S.ws && S.ws.readyState === 1;
  $("syshealth").innerHTML =
    row("Backend", '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>', "ok", "Healthy") +
    row("Simulation", '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/>',
        S.running ? "ok" : "warn", S.running ? "Running" : "Paused") +
    row("WebSocket", '<path d="M5 12.5a10 10 0 0114 0M8.5 16a5 5 0 017 0M12 19.5v.1"/>',
        wsOk ? "ok" : "bad", wsOk ? "Connected" : "Reconnecting") +
    row("Mesh", '<circle cx="12" cy="12" r="9"/><path d="M8 12h8M12 8v8"/>',
        f.activity.in_dead_zone > 0 ? "warn" : "ok",
        `${f.activity.connected}/${f.activity.connected + f.activity.in_dead_zone} online`);
}

function renderTaskProgress(f) {
  const order = { active: 0, blocked: 1, queued: 2, done: 3 };
  const rows = [...f.tasks].sort((a, b) => order[a.status] - order[b.status] || a.id - b.id).slice(0, 30);
  const tb = $("taskProgressBody");
  tb.innerHTML = "";
  for (const t of rows) {
    const pct = t.status === "done" ? 100 : t.status === "active" ? 55 : 0;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>#${t.id}</td>
      <td><span class="tstatus ${t.status}">${t.status}</span></td>
      <td>${t.rerouted ? '<span class="reroute-tag">RE-ROUTED</span>' : "—"}</td>
      <td>${t.assignee_name ? t.assignee_name.split("-")[1] : "—"}</td>
      <td><div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div></td>`;
    tb.appendChild(tr);
  }
  const k = f.kpi;
  $("taskProgressHint").textContent =
    `${k.queued_tasks} queued · ${k.active_tasks} active · ${k.completed}/${k.total} done`;
}

function renderTaskAllocation(f) {
  const box = $("taskAllocBody");
  const hint = $("taskAllocHint");
  const auc = f.activity.last_auction_detail;
  if (!auc || !auc.assignments.length) {
    box.innerHTML = `<p class="hint">No ACBBA auction has run yet — one fires whenever a robot is idle and a task is queued.</p>`;
    hint.textContent = "";
    return;
  }
  hint.textContent = `t${auc.tick} · ${auc.assignments.length} task(s) awarded`;
  box.innerHTML = auc.assignments.map(a => {
    const rows = a.bids.map((b, i) => `
      <tr class="${b.robot === a.winner ? "won" : ""}">
        <td>${b.robot}${b.robot === a.winner ? ' <span class="win-tag">WINNER</span>' : ""}</td>
        <td class="mono">${b.bid.toFixed(1)}</td>
        <td>${i === 0 ? "highest time-discounted score" : ""}</td>
      </tr>`).join("");
    return `
      <div class="auction-card">
        <div class="auction-card-hd">
          Task #${a.task_id} <span class="mono">(${a.pickup.join(",")}) → (${a.dropoff.join(",")})</span>
        </div>
        <table class="tasktable">
          <thead><tr><th>Robot</th><th>ACBBA bid</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }).join("");
}

function renderRobots(f) {
  const g = $("robotGrid");
  g.innerHTML = "";
  for (const rb of f.robots) {
    const cls = "s-" + rb.mode;
    const bcol = rb.battery < 20 ? "#DC2626" : rb.battery < 45 ? "#B45309" : "#047857";
    const el = document.createElement("div");
    el.className = `rcard st ${cls}`;
    el.innerHTML = `
      <div class="rcard-hd">
        <div class="rcard-id"><span class="chip" style="background:${rb.color}">${rb.name.split("-")[1]}</span>${rb.name}</div>
        <span class="badge st ${cls}">${rb.mode}</span>
      </div>
      <dl class="rcard-rows">
        <dt>Task</dt><dd>${rb.task_label}</dd>
        <dt>Location</dt><dd>${rb.aisle} · ${rb.bay}</dd>
        <dt>ETA</dt><dd>${rb.eta_s == null ? "—" : `${rb.eta_s}s`}</dd>
        <dt>Speed</dt><dd>${rb.speed_mps.toFixed(2)} m/s</dd>
        <dt>Link</dt><dd>${rb.connected ? "online" : "LOST"}</dd>
      </dl>
      <div class="batt">
        <div class="batt-track"><div class="batt-fill" style="width:${rb.battery}%;background:${bcol}"></div></div>
        <div class="batt-meta"><span>battery</span><span>${rb.battery.toFixed(0)}%</span></div>
      </div>`;
    g.appendChild(el);
  }
  $("fleetHint").textContent = `${f.robots.length} AMRs · priority ${f.activity.priority_order.map(n => n.split("-")[1]).join(" › ")}`;
}

function fmtSimClock(t) {
  const s = Math.max(0, Math.floor(t)), m = Math.floor(s / 60), sec = s % 60;
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function flogLineClass(msg) {
  if (/⚠|FAULT|BLOCKED/.test(msg)) return "warn";
  if (/back online|back in service|resuming|restored|rejoins|docked at charger/.test(msg)) return "ok";
  if (/ACBBA|task \d+ ->/.test(msg)) return "info";
  if (/dead zone|CONNECTIVITY_LOST/.test(msg)) return "cyan";
  return "";
}
const FLOG_ICONS = { warn: "⚠", info: "◆", ok: "✓", cyan: "⇄", "": "•" };
const FLOG_CATEGORY = { warn: "SAFETY", ok: "RECOVERY", info: "TASK", cyan: "COMMS", "": "SYSTEM" };

function flogRobotFor(msg, robots) {
  const m = msg.match(/^(AMR-\d+)\b/) || msg.match(/-> ?(AMR-\d+)\b/);
  if (!m) return null;
  return robots.find((r) => r.name === m[1]) || null;
}

function renderFleetLog(f) {
  const body = $("fleetLogBody");
  if (!S.flogSeen) S.flogSeen = new Set();
  if (f.sim_time_s < S.flogLastT) { body.innerHTML = ""; S.flogSeen.clear(); }
  S.flogLastT = f.sim_time_s;

  for (const e of f.events) {
    const key = `${e.t}|${e.msg}`;
    if (S.flogSeen.has(key)) continue;
    S.flogSeen.add(key);
    const cls = flogLineClass(e.msg);
    const rb = flogRobotFor(e.msg, f.robots);
    const who = rb
      ? `<span class="flog-who"><i class="dot" style="background:${rb.color}"></i>${rb.name}</span>`
      : `<span class="flog-who fleet"><i class="dot"></i>FLEET</span>`;
    const line = document.createElement("div");
    line.className = `flog-line${cls ? " " + cls : ""}`;
    line.innerHTML =
      `<span class="t">${fmtSimClock(e.t)}</span>` +
      `<span class="ic">${FLOG_ICONS[cls]}</span>` +
      `<span class="flog-cat">${FLOG_CATEGORY[cls]}</span>` +
      who +
      `<span class="m">${escapeHtml(e.msg)}</span>`;
    body.appendChild(line);
  }
  while (body.children.length > 200) body.removeChild(body.firstChild);
  body.scrollTop = body.scrollHeight;

  $("fleetLogHint").textContent = f.events.length
    ? `live feed · last at ${fmtSimClock(f.events[f.events.length - 1].t)}` : "live feed";
}

const ACT_ICONS = {
  route: '<path d="M4 20l6-14 4 8 3-5 3 11"/>',
  orca: '<circle cx="12" cy="12" r="9"/><path d="M12 3v9l6 3"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  mesh: '<path d="M5 12.5a10 10 0 0114 0M8.5 16a5 5 0 017 0M12 19.5v.1"/>',
};

function renderSummary(f) {
  const k = f.kpi, c = k.count;
  const item = (kk, vv, frac) => `<div class="sitem"><div class="k">${kk}</div><div class="v">${vv}</div>${frac != null ? `<div class="track"><i style="width:${frac}%"></i></div>` : ""}</div>`;
  $("summary").innerHTML =
    item("Fleet Utilisation", `${(k.fleet_util * 100).toFixed(0)}%`, k.fleet_util * 100) +
    item("Avg Battery", `${k.avg_battery.toFixed(0)}%`, k.avg_battery) +
    item("Active", c.active) + item("Idle", c.idle) +
    item("Parked", c.parked) +
    item("Charging", c.charging) + item("Re-routing", c.rerouting) +
    item("Waiting", c.waiting) + item("Stranded", c.stranded) +
    item("Faulted", c.error);
}

let _selSig = "";
function populateSelects(f) {
  const sig = f.robots.map(r => r.id + (r.alive ? "1" : "0")).join(",");
  if (sig === _selSig || document.activeElement === $("qaFailSel")) return;
  _selSig = sig;
  const cur = $("qaFailSel").value;
  $("qaFailSel").innerHTML = f.robots.map(r =>
    `<option value="${r.id}">${r.name}${r.alive ? "" : " · down"}</option>`).join("");
  if (cur) $("qaFailSel").value = cur;
}

/* ---------------------------------------------------------------- scoreboard */
function renderScoreboard(cmp) {
  const el = $("scoreboard");
  el.innerHTML = cmp.rows.map((r) => {
    const win = r.winner === "stack" ? "win-stack"
      : r.winner === "stopwait" ? "win-stopwait"
      : r.winner === "none" ? "win-context" : "win-tie";
    return `<div class="sitem ${win}">
        <div class="k">${r.label}</div>
        <div class="v"><span class="v-stack">${r.stack}</span><span class="vs">vs</span><span class="v-base">${r.stopwait}</span></div>
      </div>`;
  }).join("");
  const [w, l] = cmp.score;
  const cap = cmp.capped ? " · tick cap reached" : "";
  $("verdictHint").textContent =
    cmp.verdict === "stack" ? `5-layer stack wins ${w}–${l}${cap}`
    : cmp.verdict === "stopwait" ? `stop-and-wait wins ${l}–${w}${cap}`
    : `tied ${w}–${l}${cap}`;
}

/* ---------------------------------------------------------------- controls */
const post = (url, body) => fetch(url, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body || {}),
});

$("btnApply").onclick = () => post("/api/config", {
  n_robots: +$("cfgRobots").value, n_tasks: +$("cfgTasks").value, seed: +$("cfgSeed").value,
});
$("btnStart").onclick = () => post("/api/control", { action: S.running ? "pause" : "start" });
$("btnStep").onclick = () => post("/api/control", { action: "step" });
$("btnReset").onclick = () => {
  if (S.hasProgress && !confirm("Reset simulation? Current progress will be lost.")) return;
  post("/api/control", { action: "reset" });
};
$("benchToggle").onchange = (e) => post("/api/benchmark", { on: e.target.checked });

$("speedSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  post("/api/control", { action: "speed", value: +b.dataset.v });
});
function markSpeed() {
  [...$("speedSeg").children].forEach(b => b.classList.toggle("on", +b.dataset.v === S.speed));
}

function arm(mode) {
  S.armed = S.armed === mode ? null : mode;
  document.querySelectorAll('[data-arm="box"]').forEach(b => b.classList.toggle("armed", S.armed === "box"));
  document.querySelectorAll('[data-arm="zone"]').forEach(b => b.classList.toggle("armed", S.armed === "zone"));
  const h = $("armHint");
  if (S.armed === "box") { h.hidden = false; h.textContent = "click a cell, or drag a rectangle, to drop a block"; }
  else if (S.armed === "zone") { h.hidden = false; h.textContent = "drag a rectangle for a Wi-Fi dead zone"; }
  else h.hidden = true;
}
$("qaClearBoxes").onclick = () => post("/api/event", { kind: "clear_obstacles" });
$("qaClearZones").onclick = () => post("/api/event", { kind: "clear_zones" });
$("qaFail").onclick = () => {
  const opt = $("qaFailSel").selectedOptions[0];
  const name = opt ? opt.textContent : "the selected robot";
  if (!confirm(`Fail ${name}? Its task will be re-auctioned to another robot.`)) return;
  post("/api/event", { kind: "robot_fail", payload: +$("qaFailSel").value });
};
$("qaRecover").onclick = () => post("/api/event", { kind: "robot_recover", payload: +$("qaFailSel").value });
$("btnKill").onclick = () => {
  if (!confirm("Simulate dashboard failure? The fleet will keep operating with no central coordinator.")) return;
  post("/api/event", { kind: "dashboard_kill" });
};

/* ---------------------------------------------------------------- drawers */
function openDrawer(id) {
  document.querySelectorAll(".drawer.open").forEach(d => d.classList.remove("open"));
  const d = $(id);
  if (d) d.classList.add("open");
  $("drawerBackdrop").classList.add("open");
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("on", b.dataset.drawer === id));
}
function closeDrawers() {
  document.querySelectorAll(".drawer.open").forEach(d => d.classList.remove("open"));
  $("drawerBackdrop").classList.remove("open");
  document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("on", b.dataset.nav === "operate"));
}
document.querySelectorAll("[data-drawer]").forEach(b => b.addEventListener("click", () => openDrawer(b.dataset.drawer)));
document.querySelectorAll("[data-close-drawer]").forEach(b => b.addEventListener("click", closeDrawers));
$("drawerBackdrop").addEventListener("click", closeDrawers);
document.querySelector('[data-nav="operate"]').addEventListener("click", closeDrawers);

/* mobile sidebar (narrow widths only — .menu-toggle is hidden otherwise) */
function toggleSidebar(open) {
  $("sidebar").classList.toggle("open", open);
  $("sidebarScrim").classList.toggle("open", open);
}
$("btnMenuToggle").onclick = () => toggleSidebar(!$("sidebar").classList.contains("open"));
$("sidebarScrim").addEventListener("click", () => toggleSidebar(false));
$("sidenav").querySelectorAll("button").forEach(b => b.addEventListener("click", () => toggleSidebar(false)));

/* ---------------------------------------------------------------- quick actions */
$("qaDropBox").onclick = () => arm("box");
$("qaDeadZone").onclick = () => arm("zone");
$("qaMore").onclick = () => openDrawer("demonstrateDrawer");

$("heatToggle").onchange = (e) => {
  arenaStack.heat = e.target.checked;
  if (arenaStopwait) arenaStopwait.heat = e.target.checked;
};

/* canvas → cell interactions (always target the stack canvas; the server
   fans the event out to both sims) */
function cellFromEvent(e) {
  const r = arenaStack.cv.getBoundingClientRect();
  const x = Math.floor((e.clientX - r.left) / r.width * S.layout.w);
  const y = Math.floor((e.clientY - r.top) / r.height * S.layout.h);
  return [x, y];
}
function bindArenaInput(cv) {
  cv.addEventListener("mousedown", (e) => {
    if (!S.layout || S.editMode) return;
    if (S.armed === "box" || S.armed === "zone") S.dragStart = cellFromEvent(e);
  });
  cv.addEventListener("mouseup", (e) => {
    if (S.editMode) return;
    if (!S.dragStart || (S.armed !== "box" && S.armed !== "zone")) return;
    const [x0, y0] = S.dragStart, [x1, y1] = cellFromEvent(e);
    const x = Math.min(x0, x1), y = Math.min(y0, y1);
    if (S.armed === "zone") {
      const w = Math.max(1, Math.abs(x1 - x0)), h = Math.max(1, Math.abs(y1 - y0));
      post("/api/event", { kind: "dead_zone", payload: [x, y, w, h] });
    } else {
      const w = Math.abs(x1 - x0) + 1, h = Math.abs(y1 - y0) + 1;
      post("/api/event", { kind: "obstacle", payload: [x, y, w, h] });
    }
    S.dragStart = null; arm(null);
  });
}

/* replay */
$("scrub").addEventListener("input", (e) => {
  S.view = "replay"; S.replayPlaying = false;
  S.replayCursor = +e.target.value;
  $("btnReplayPlay").textContent = "Play";
  setLiveBtn();
});
$("btnReplayPlay").onclick = () => {
  if (S.frames.length < 2) return;
  S.view = "replay";
  S.replayPlaying = !S.replayPlaying;
  if (S.replayCursor >= S.frames.length - 1) S.replayCursor = 0;
  $("btnReplayPlay").textContent = S.replayPlaying ? "Pause" : "Play";
  setLiveBtn();
};
$("btnLive").onclick = () => {
  S.view = "live"; S.replayPlaying = false;
  $("btnReplayPlay").textContent = "Play";
  $("scrub").value = S.frames.length - 1;
  setLiveBtn();
};
function setLiveBtn() { $("btnLive").classList.toggle("on", S.view === "live"); }

/* export */
$("btnExport").onclick = () => { post("/api/export"); };
function onExport(m) {
  const row = $("exportRow");
  if (m.status === "running") {
    row.hidden = false;
    $("exportBar").style.width = (m.pct || 0) + "%";
    $("exportLabel").textContent = `rendering ${m.pct || 0}%`;
  } else if (m.status === "done") {
    row.hidden = true;
    const v = $("video");
    v.hidden = false; v.src = m.url;
    const dl = $("videoDl"); dl.hidden = false; dl.href = m.url;
    $("replayHint").textContent = "MP4 ready ↓";
  } else if (m.status === "error") {
    row.hidden = false;
    $("exportLabel").textContent = "export failed: " + (m.msg || "");
  }
}

/* ---------------------------------------------------------------- layout editor */
const cellKey = (x, y) => `${x},${y}`;

function blankEditBuffer() {
  return { blocked: [], pickups: [], dropoffs: [], chargers: [], depot: [], _owner: new Map() };
}

function layoutToBuffer(layout) {
  const buf = blankEditBuffer();
  if (!layout) return buf;
  for (const field of ["blocked", "pickups", "dropoffs", "chargers", "depot"]) {
    for (const [x, y] of (layout[field] || [])) {
      buf[field].push([x, y]);
      buf._owner.set(cellKey(x, y), field);
    }
  }
  return buf;
}

function bufferToLayout(buf) {
  return {
    schema: "fleetnet.custom_layout.v1",
    blocked: buf.blocked, pickups: buf.pickups, dropoffs: buf.dropoffs,
    chargers: buf.chargers, depot: buf.depot,
  };
}

function removeFromField(arr, x, y) {
  const i = arr.findIndex(([cx, cy]) => cx === x && cy === y);
  if (i >= 0) arr.splice(i, 1);
}

function bufferSet(buf, x, y, field) {
  const k = cellKey(x, y);
  const prev = buf._owner.get(k);
  if (prev === field) return;
  if (prev) removeFromField(buf[prev], x, y);
  if (field) { buf[field].push([x, y]); buf._owner.set(k, field); }
  else buf._owner.delete(k);
}

function paintAt(x, y) {
  const buf = S.editBuffer;
  if (!buf || !S.layout) return;
  if (x <= 0 || y <= 0 || x >= S.layout.w - 1 || y >= S.layout.h - 1) return;   // border is always a wall
  const tool = S.editTool;
  if (tool === "erase") {
    bufferSet(buf, x, y, null);
  } else if (tool === "blocked") {
    bufferSet(buf, x, y, "blocked");
  } else {
    const field = TOOL_FIELD[tool];
    const k = cellKey(x, y);
    bufferSet(buf, x, y, buf._owner.get(k) === field ? null : field);   // click-toggle
  }
  updatePaletteCounts();
}

function updatePaletteCounts() {
  const b = S.editBuffer;
  if (!b) return;
  $("paletteCounts").textContent =
    `Racks ${b.blocked.length} · Pickups ${b.pickups.length} · Dropoffs ${b.dropoffs.length} `
    + `· Chargers ${b.chargers.length} · Depot ${b.depot.length}`;
}

function renderLayoutErrors(errors) {
  $("layoutErrorsPanel").hidden = false;
  const ul = $("layoutErrors");
  if (!errors.length) {
    $("layoutStatusHint").textContent = "valid";
    ul.innerHTML = '<li><span class="m" style="color:var(--ok)">✓ layout is valid — ready to Apply</span></li>';
  } else {
    $("layoutStatusHint").textContent = `${errors.length} issue(s)`;
    ul.innerHTML = errors.map(e => `<li><span class="m" style="color:var(--err)">${e}</span></li>`).join("");
  }
}

function clearLayoutErrors() {
  $("layoutErrorsPanel").hidden = true;
  $("layoutErrors").innerHTML = "";
}

function seedEditBuffer(layoutOrNull) {
  S.editBuffer = layoutToBuffer(layoutOrNull);
  updatePaletteCounts();
}

async function enterEditMode() {
  let current = null;
  S.editLayoutId = null;
  try {
    const r = await fetch("/api/layout").then(r => r.json());
    current = r.custom_layout;
    S.editLayoutId = r.layout_id || null;
  } catch { /* fall through to a blank buffer */ }
  seedEditBuffer(current);
  S.editMode = true;
  S.editPainting = false;
  S.editHover = null;
  if (S.running) post("/api/control", { action: "pause" });
  closeDrawers();
  $("btnEditLayout").classList.add("armed");
  $("btnEditLayout").querySelector(".lbl").textContent = "Exit Editor";
  $("quickActionsRow").hidden = true;
  $("layoutToolbarRow").hidden = false;
  $("topActionsTitle").textContent = "Editing Layout";
  $("saveAsRow").hidden = false;
  $("arenaTitleStack").textContent = "Layout Editor — paint racks & stations";
  clearLayoutErrors();
  fetchAndRenderSavedLayouts();
}

function exitEditMode() {
  S.editMode = false;
  S.editBuffer = null;
  S.editPainting = false;
  S.editHover = null;
  $("btnEditLayout").classList.remove("armed");
  $("btnEditLayout").querySelector(".lbl").textContent = "Custom Layout";
  $("quickActionsRow").hidden = false;
  $("layoutToolbarRow").hidden = true;
  $("topActionsTitle").textContent = "Quick Actions";
  $("saveAsRow").hidden = true;
  clearLayoutErrors();
  $("arenaTitleStack").textContent = S.benchmark
    ? "Fleet Map — 5-Layer Stack" : "Fleet Map — Warehouse Layout";
}

$("btnEditLayout").onclick = () => { S.editMode ? exitEditMode() : enterEditMode(); };

$("btnResetLayout").onclick = async () => {
  if (!confirm("Reset to the default warehouse layout? This discards any custom layout.")) return;
  await post("/api/layout/clear");
  if (S.editMode) exitEditMode();
};

$("paletteSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  S.editTool = b.dataset.tool;
  [...$("paletteSeg").children].forEach(x => x.classList.toggle("on", x === b));
});

$("btnLayoutImport").onclick = () => $("layoutImportInput").click();

$("layoutImportInput").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const raw = await file.arrayBuffer();
  const res = await fetch("/api/layout/import-pgm", { method: "POST", body: raw }).then(r => r.json());
  if (!res.ok) { renderLayoutErrors(res.errors); return; }
  if (!S.editMode) await enterEditMode();
  S.editLayoutId = null;  // a freshly imported image is not any existing saved layout
  seedEditBuffer(res.layout);
  clearLayoutErrors();
};

$("btnLayoutValidate").onclick = async () => {
  const res = await post("/api/layout/validate", bufferToLayout(S.editBuffer)).then(r => r.json());
  renderLayoutErrors(res.errors);
};

$("btnLayoutApply").onclick = async () => {
  const res = await post("/api/layout", {
    layout: bufferToLayout(S.editBuffer),
    layout_id: S.editLayoutId,
    n_robots: +$("cfgRobots").value, n_tasks: +$("cfgTasks").value, seed: +$("cfgSeed").value,
  }).then(r => r.json());
  if (res.ok) {
    // Apply always saves (new layouts get an auto-generated name; editing a
    // loaded one updates it in place) - toast so it's clear nothing needs a
    // separate Save As click, then let the operator rename it if they want.
    toast(`Saved to library as "${res.layout_name}"`);
    exitEditMode();
  } else {
    renderLayoutErrors(res.errors);
  }
};

$("btnLayoutClearCanvas").onclick = () => {
  if (!confirm("Clear the entire canvas?")) return;
  S.editBuffer = blankEditBuffer();
  clearLayoutErrors();
  updatePaletteCounts();
};

$("btnLayoutCancel").onclick = () => {
  if (!confirm("Discard changes and exit the editor?")) return;
  exitEditMode();
};

/* ---------------------------------------------------------------- saved layouts */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtUpdated(iso) {
  return (iso || "").replace("T", " ").replace("Z", "").slice(0, 16);
}

function renderSavedLayouts(list) {
  S.savedLayouts = list;
  const tb = $("savedLayoutsBody");
  tb.innerHTML = "";
  for (const r of list) {
    const n = escapeHtml(r.name);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${n}</td>
      <td>${fmtUpdated(r.updated_at)}</td>
      <td>
        <button class="btn" data-act="load" data-id="${r.id}" data-name="${n}">Load</button>
        <button class="btn btn-primary" data-act="apply" data-id="${r.id}" data-name="${n}">Apply</button>
        <button class="btn" data-act="export" data-id="${r.id}" data-name="${n}">Export</button>
        <button class="btn" data-act="rename" data-id="${r.id}" data-name="${n}">Rename</button>
        <button class="btn btn-danger" data-act="delete" data-id="${r.id}" data-name="${n}">Delete</button>
      </td>`;
    tb.appendChild(tr);
  }
  $("savedLayoutsHint").textContent = `${list.length} saved`;
}

async function fetchAndRenderSavedLayouts() {
  try {
    const res = await fetch("/api/layouts").then(r => r.json());
    renderSavedLayouts(res.layouts || []);
  } catch { /* leave the list as-is on a transient fetch failure */ }
}

async function loadSavedLayoutIntoEditor(id, name) {
  if (S.editMode && !confirm(`Discard current unsaved edits and load "${name}"?`)) return;
  const res = await fetch(`/api/layouts/${id}`).then(r => r.json());
  if (!res.ok) { alert(res.error || "failed to load layout"); return; }
  if (!S.editMode) await enterEditMode();
  S.editLayoutId = id;  // re-applying will update this same saved record, not fork a copy
  seedEditBuffer(res.layout.layout);
  clearLayoutErrors();
}

async function applySavedLayout(id) {
  const res = await post(`/api/layouts/${id}/apply`, {
    n_robots: +$("cfgRobots").value, n_tasks: +$("cfgTasks").value, seed: +$("cfgSeed").value,
  }).then(r => r.json());
  if (!res.ok) alert((res.errors || [res.error]).join("\n"));
}

async function renameSavedLayout(id, currentName) {
  const name = prompt("Rename layout:", currentName);
  if (name == null) return;
  const trimmed = name.trim();
  if (!trimmed || trimmed === currentName) return;
  const res = await post(`/api/layouts/${id}/rename`, { name: trimmed }).then(r => r.json());
  if (res.ok) fetchAndRenderSavedLayouts();
  else alert(res.errors.join("\n"));
}

async function deleteSavedLayout(id, name) {
  if (!confirm(`Delete saved layout "${name}"? This cannot be undone.`)) return;
  const res = await fetch(`/api/layouts/${id}`, { method: "DELETE" }).then(r => r.json());
  if (res.ok) fetchAndRenderSavedLayouts();
  else alert(res.error || "delete failed");
}

$("savedLayoutsBody").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  const { act, id, name } = b.dataset;
  if (act === "load") loadSavedLayoutIntoEditor(id, name);
  else if (act === "apply") applySavedLayout(id);
  else if (act === "export") window.open(`/api/layouts/${id}/export`, "_blank");
  else if (act === "rename") renameSavedLayout(id, name);
  else if (act === "delete") deleteSavedLayout(id, name);
});

$("btnImportLayoutJson").onclick = () => $("layoutJsonImportInput").click();

$("layoutJsonImportInput").onchange = async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const raw = await file.text();
  const res = await fetch("/api/layouts/import", { method: "POST", body: raw }).then(r => r.json());
  if (!res.ok) { alert((res.errors || ["import failed"]).join("\n")); return; }
  fetchAndRenderSavedLayouts();
};

$("btnSaveCurrentLayout").onclick = async () => {
  const name = prompt("Save the currently running layout as:");
  if (name == null) return;
  const trimmed = name.trim();
  if (!trimmed) return;
  const current = await fetch("/api/layout").then(r => r.json());
  const res = await post("/api/layouts", { name: trimmed, layout: current.custom_layout }).then(r => r.json());
  if (res.ok) fetchAndRenderSavedLayouts();
  else alert(res.errors.join("\n"));
};

$("btnSaveAsLayout").onclick = async () => {
  const name = $("saveAsName").value.trim();
  if (!name) { renderLayoutErrors(["a name is required"]); return; }
  const res = await post("/api/layouts", { name, layout: bufferToLayout(S.editBuffer) }).then(r => r.json());
  if (res.ok) {
    $("saveAsName").value = "";
    clearLayoutErrors();
    fetchAndRenderSavedLayouts();
  } else {
    renderLayoutErrors(res.errors);
  }
};

function bindEditInput(cv) {
  cv.addEventListener("mousedown", (e) => {
    if (!S.editMode) return;
    const [x, y] = cellFromEvent(e);
    S.editPainting = true;
    paintAt(x, y);
  });
  cv.addEventListener("mousemove", (e) => {
    if (!S.editMode) return;
    const [x, y] = cellFromEvent(e);
    S.editHover = [x, y];
    if (S.editPainting && (S.editTool === "blocked" || S.editTool === "erase")) paintAt(x, y);
  });
  cv.addEventListener("mouseleave", () => { S.editHover = null; });
  window.addEventListener("mouseup", () => { S.editPainting = false; });
}

/* ---------------------------------------------------------------- keyboard shortcuts
   Space=Start/Pause, S=Step, R=Reset (still confirmed), Esc=close drawer /
   exit armed tool / exit layout editor. Every shortcut has a visible button
   equivalent — never the only way to operate. Inert while typing. */
document.addEventListener("keydown", (e) => {
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "select" || tag === "textarea") return;
  if (e.code === "Space") { e.preventDefault(); $("btnStart").click(); }
  else if (e.key === "s" || e.key === "S") { $("btnStep").click(); }
  else if (e.key === "r" || e.key === "R") { $("btnReset").click(); }
  else if (e.key === "Escape") {
    if (S.editMode) $("btnLayoutCancel").click();
    else if (S.armed) arm(S.armed);
    else closeDrawers();
  }
});

/* clock */
setInterval(() => {
  $("clock").textContent = new Date().toLocaleTimeString([], { hour12: false });
}, 1000);

/* ---------------------------------------------------------------- boot */
arenaStack = new Arena("mapStack", "mapBannerStack");
bindArenaInput(arenaStack.cv);
bindEditInput(arenaStack.cv);
connect();
fetchAndRenderSavedLayouts();
requestAnimationFrame(draw);
