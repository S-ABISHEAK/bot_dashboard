/* ============================================================
   FleetNet Dashboard — front-end controller
   The Python engine is authoritative; this only views + controls.
   ============================================================ */
"use strict";

const STATUS_COLORS = {
  active: "#22c55e", waiting: "#f59e0b", rerouting: "#fb923c",
  charging: "#ef4444", "comms-lost": "#a855f7", idle: "#64748b",
  parked: "#8b95a5", error: "#ef4444", stranded: "#f43f5e",
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
};

const $ = (id) => document.getElementById(id);
const lerp = (a, b, t) => a + (b - a) * t;
const clamp01 = (x) => Math.max(0, Math.min(1, x));
const fmtEta = (s) => (s == null ? "—" : s >= 60 ? `${(s / 60).toFixed(1)}m` : `${s.toFixed(0)}s`);

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

  _floor() {
    const { w, h } = this.layout, ctx = this.ctx;
    ctx.fillStyle = "#0a0f18";
    ctx.fillRect(0, 0, this.cv.width, this.cv.height);
    ctx.strokeStyle = "#121a28"; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0; x <= w; x += 2) { ctx.moveTo(this.px(x), 0); ctx.lineTo(this.px(x), this.px(h)); }
    for (let y = 0; y <= h; y += 2) { ctx.moveTo(0, this.px(y)); ctx.lineTo(this.px(w), this.px(y)); }
    ctx.stroke();
    ctx.strokeStyle = "#2b3a52"; ctx.lineWidth = Math.max(2, this.CELL * 0.5);
    ctx.strokeRect(this.px(0.5), this.px(0.5), this.px(w - 1), this.px(h - 1));
    for (const r of this.rackRects) {
      this._roundRect(this.px(r.x) + 1, this.px(r.y) + 1, this.px(r.w) - 2, this.px(r.h) - 2, 3);
      ctx.fillStyle = "#1a2434"; ctx.fill();
      ctx.fillStyle = "#222f43"; ctx.fillRect(this.px(r.x) + 1, this.px(r.y) + 1, this.px(r.w) - 2, 2);
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

  _depot() {
    const d = this.layout.depot;
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
    ctx.fillStyle = "#9aa5b4";
    ctx.font = `600 ${Math.max(8, C * 0.4)}px Inter, system-ui, sans-serif`;
    ctx.textAlign = "left"; ctx.textBaseline = "bottom";
    ctx.fillText("STANDBY DEPOT", bx, by - 2);
    d.forEach(([sx, sy], i) => {
      this._roundRect(this.px(sx) + C * 0.15, this.px(sy) + C * 0.15, C * 0.7, C * 0.7, 3);
      ctx.strokeStyle = "#94a3b8"; ctx.lineWidth = 1.1; ctx.stroke();
      ctx.fillStyle = "rgba(148,163,184,.09)"; ctx.fill();
      ctx.fillStyle = "#8b95a5";
      ctx.font = `${C * 0.34}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(String(i + 1), this.px(sx + 0.5), this.px(sy + 0.56));
    });
  }

  _stations() {
    const ctx = this.ctx, C = this.CELL;
    const mark = (list, color) => {
      for (const [x, y] of list) {
        this._roundRect(this.px(x) + C * 0.12, this.px(y) + C * 0.12, C * 0.76, C * 0.76, 3);
        ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
        ctx.fillStyle = color + "22"; ctx.fill();
      }
    };
    mark(this.layout.pickups, "#22c55e");
    mark(this.layout.dropoffs, "#4f8cff");
    for (const [x, y] of this.layout.chargers) {
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
      ctx.fillStyle = "#f2c072"; ctx.font = `600 ${Math.max(9, C * 0.5)}px Inter, system-ui, sans-serif`;
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
      const x = this.px(lerp(a.pos[0], rb.pos[0], t) + 0.5);
      const y = this.px(lerp(a.pos[1], rb.pos[1], t) + 0.5);
      const s = STATUS_COLORS[rb.mode] || "#64748b";
      const rad = C * 0.36;

      if (rb.mode === "comms-lost") {
        ctx.strokeStyle = s + "55"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(x, y, C * 1.6, 0, 7); ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(x, y, rad + 3, 0, 7);
      ctx.strokeStyle = s; ctx.lineWidth = 2.4; ctx.stroke();

      ctx.beginPath(); ctx.arc(x, y, rad, 0, 7);
      ctx.fillStyle = rb.alive ? rb.color : "#3a4152"; ctx.fill();
      ctx.strokeStyle = "#0b1220"; ctx.lineWidth = 1.5; ctx.stroke();

      ctx.fillStyle = "#fff"; ctx.font = `700 ${C * 0.42}px Inter, system-ui, sans-serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText(rb.name.split("-")[1], x, y + 0.5);

      ctx.fillStyle = "#cdd6e4"; ctx.font = `500 ${Math.max(8, C * 0.4)}px Inter, system-ui, sans-serif`;
      ctx.textBaseline = "top";
      ctx.fillText(rb.name, x, y + rad + 5);
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
  S.ws.onopen = () => setConn(true);
  S.ws.onclose = () => { setConn(false); setTimeout(connect, 1200); };
  S.ws.onmessage = (e) => dispatch(JSON.parse(e.data));
}

function dispatch(msg) {
  if (msg.type === "layout") onLayout(msg);
  else if (msg.type === "frame") onFrame(msg.data);
  else if (msg.type === "status") onStatus(msg);
  else if (msg.type === "export") onExport(msg);
}

function setConn(ok) {
  const c = $("conn");
  c.className = "conn " + (ok ? "online" : "offline");
  c.querySelector("span").textContent = ok ? "connected" : "reconnecting…";
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
  if ("running" in msg) { S.running = msg.running; $("btnStart").textContent = msg.running ? "Pause" : "Start"; }
  if ("speed" in msg && msg.speed) { S.speed = msg.speed; markSpeed(); }
  if (msg.note) $("replayHint").textContent = msg.note;
}

/* ---------------------------------------------------------------- draw loop */
function draw() {
  requestAnimationFrame(draw);
  if (!S.layout || !arenaStack.cur) return;

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
  $("kpiRobots").textContent = f.robots.length;
  $("kpiActive").textContent = k.active_tasks;
  $("kpiDone").textContent = `${k.completed}/${k.total}`;
  $("kpiAvg").textContent = k.avg_completion_s == null ? "—" : `${k.avg_completion_s}s`;
  $("kpiConf").textContent = k.conflicts;
  $("kpiAvoid").textContent = k.avoided;
  $("simTime").textContent = `t = ${f.sim_time_s.toFixed(1)} s`;

  renderRobots(f);
  renderTasks(f);
  renderActivity(f);
  renderSummary(f);
  renderEvents(f);
  populateSelects(f);
}

function renderRobots(f) {
  const g = $("robotGrid");
  g.innerHTML = "";
  for (const rb of f.robots) {
    const cls = "s-" + rb.mode;
    const bcol = rb.battery < 20 ? "#ef4444" : rb.battery < 45 ? "#f59e0b" : "#22c55e";
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
        <dt>Speed</dt><dd>${rb.speed_mps.toFixed(2)} m/s</dd>
        <dt>Heartbeat</dt><dd>${rb.heartbeat_s.toFixed(1)}s ago</dd>
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

function renderTasks(f) {
  const order = { active: 0, blocked: 1, queued: 2, done: 3 };
  const rows = [...f.tasks].sort((a, b) => order[a.status] - order[b.status] || a.id - b.id);
  const tb = $("taskBody");
  tb.innerHTML = "";
  for (const t of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>#${t.id}</td>
      <td><span class="tstatus ${t.status}">${t.status}</span></td>
      <td>${t.assignee_name ? t.assignee_name.split("-")[1] : "—"}</td>
      <td>${t.status === "active" ? fmtEta(t.eta_s) : "—"}</td>
      <td>${t.rerouted ? '<span class="reroute-tag">RE-ROUTED</span>' : "—"}</td>`;
    tb.appendChild(tr);
  }
  const q = f.tasks.filter(t => t.status === "queued").length;
  const a = f.tasks.filter(t => t.status === "active").length;
  const d = f.tasks.filter(t => t.status === "done").length;
  const b = f.tasks.filter(t => t.status === "blocked").length;
  $("taskHint").textContent =
    `${q} queued · ${a} active · ${d} done` + (b ? ` · ${b} blocked` : "");
}

function renderActivity(f) {
  const a = f.activity;
  $("activity").innerHTML = `
    <div class="act"><div class="k">D* Lite replans (tick / total)</div><div class="v">${a.astar_replans_tick} / ${a.astar_replans}</div></div>
    <div class="act"><div class="k">MD-PIBT priority pushes / tick</div><div class="v">${a.pibt_pushes_tick}</div></div>
    <div class="act"><div class="k">Robots avoiding now</div><div class="v">${a.avoiding_now}</div></div>
    <div class="act"><div class="k">Mesh online / lost</div><div class="v">${a.connected} / ${a.in_dead_zone}</div></div>
    <div class="act"><div class="k">Body near-misses</div><div class="v">${f.kpi.near_miss}</div></div>
    <div class="act"><div class="k">Last ACBBA auction</div><div class="v small">${a.last_auction}</div></div>`;
}

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

function renderEvents(f) {
  const ul = $("eventLog");
  ul.innerHTML = "";
  for (const e of [...f.events].reverse()) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="t">t${e.t.toFixed(0)}</span><span class="m">${e.msg}</span>`;
    ul.appendChild(li);
  }
}

let _selSig = "";
function populateSelects(f) {
  const sig = f.robots.map(r => r.id + (r.alive ? "1" : "0")).join(",");
  if (sig === _selSig || document.activeElement === $("failSel")) return;
  _selSig = sig;
  const cur = $("failSel").value;
  $("failSel").innerHTML = f.robots.map(r =>
    `<option value="${r.id}">${r.name}${r.alive ? "" : " · down"}</option>`).join("");
  if (cur) $("failSel").value = cur;
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
$("btnReset").onclick = () => post("/api/control", { action: "reset" });
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
  $("btnBox").classList.toggle("armed", S.armed === "box");
  $("btnZone").classList.toggle("armed", S.armed === "zone");
  const h = $("armHint");
  if (S.armed === "box") { h.hidden = false; h.textContent = "click a cell, or drag a rectangle, to drop a block"; }
  else if (S.armed === "zone") { h.hidden = false; h.textContent = "drag a rectangle for a Wi-Fi dead zone"; }
  else h.hidden = true;
}
$("btnBox").onclick = () => arm("box");
$("btnZone").onclick = () => arm("zone");
$("btnClearBoxes").onclick = () => post("/api/event", { kind: "clear_obstacles" });
$("btnClearZones").onclick = () => post("/api/event", { kind: "clear_zones" });
$("btnFail").onclick = () => post("/api/event", { kind: "robot_fail", payload: +$("failSel").value });
$("btnRecover").onclick = () => post("/api/event", { kind: "robot_recover", payload: +$("failSel").value });
$("btnKill").onclick = () => post("/api/event", { kind: "dashboard_kill" });

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
    if (!S.layout) return;
    if (S.armed === "box" || S.armed === "zone") S.dragStart = cellFromEvent(e);
  });
  cv.addEventListener("mouseup", (e) => {
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

/* clock */
setInterval(() => {
  $("clock").textContent = new Date().toLocaleTimeString([], { hour12: false });
}, 1000);

/* ---------------------------------------------------------------- boot */
arenaStack = new Arena("mapStack", "mapBannerStack");
bindArenaInput(arenaStack.cv);
connect();
requestAnimationFrame(draw);
