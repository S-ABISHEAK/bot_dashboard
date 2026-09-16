// Watch tab: live playback while a simulation runs, and post-hoc replay
// once it's finished -- both driven by the exact same polling contract
// (GET /api/runs/{run_id}/frames?since_tick=), per the plan. Visuals
// mirror the existing Python GIF replay (fleetnet_sim/replay/renderer.py):
// robots colored by task_state with a fading trail, conflict pairs as a
// gold line, congestion-detour robots as a magenta star.

const TASK_STATE_COLORS = {
  IDLE: "#adb5bd", TO_PICKUP: "#e63946", PICKING: "#f4a261",
  TO_DROPOFF: "#2a9d8f", DROPPING: "#264653",
};
const TRAIL_LENGTH = 15;
const POLL_INTERVAL_MS = 400;
const PLAYBACK_FPS = 10;

const SimView = {
  runId: null,
  layout: null,
  transform: null,
  frameQueue: [],
  history: {},
  lastTick: 0,
  pollTimer: null,
  animTimer: null,

  async watch(runId) {
    this.stop();
    this.runId = runId;
    this.frameQueue = [];
    this.history = {};
    this.lastTick = 0;

    document.getElementById("watchStatus").textContent = "loading…";
    document.getElementById("watchReplayFromStartBtn").disabled = true;

    const run = await Api.getRun(runId);
    this.layout = await Api.getLayout(run.layout_id);

    const bg = document.getElementById("watchBgCanvas");
    this.transform = computeViewTransform(this.layout.geometry.footprint, bg.width, bg.height);
    drawLayout(bg.getContext("2d"), this.layout, this.transform, { showGraph: false, showExclusions: true, showBottlenecks: false });

    document.getElementById("watchFgCanvas").getContext("2d").clearRect(0, 0, bg.width, bg.height);

    this._poll();
    this.animTimer = setInterval(() => this._drainQueue(), 1000 / PLAYBACK_FPS);
  },

  replayFromStart() {
    if (!this.runId) return;
    this.watch(this.runId);
  },

  stop() {
    if (this.pollTimer) clearTimeout(this.pollTimer);
    if (this.animTimer) clearInterval(this.animTimer);
    this.pollTimer = null;
    this.animTimer = null;
  },

  async _poll() {
    try {
      const resp = await Api.getFrames(this.runId, this.lastTick, 200);
      this.lastTick = resp.last_tick;
      for (const frame of resp.frames) this.frameQueue.push(frame);

      if (resp.run_status === "running" || resp.run_status === "queued") {
        document.getElementById("watchStatus").textContent = `running (tick ${resp.last_tick}${resp.final_tick ? " / " + resp.final_tick : ""})…`;
        this.pollTimer = setTimeout(() => this._poll(), POLL_INTERVAL_MS);
      } else {
        document.getElementById("watchStatus").textContent = `${resp.run_status} at tick ${resp.last_tick}`;
        document.getElementById("watchReplayFromStartBtn").disabled = false;
        // one last poll in case frames landed between the previous poll and status flip
        if (this.frameQueue.length === 0 && resp.frames.length === 0) this.pollTimer = null;
      }
    } catch (err) {
      document.getElementById("watchStatus").textContent = `error: ${err.message}`;
    }
  },

  _drainQueue() {
    const frame = this.frameQueue.shift();
    if (!frame) return;
    this._drawFrame(frame);
  },

  _drawFrame(frame) {
    const canvas = document.getElementById("watchFgCanvas");
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const posById = {};
    for (const r of frame.robots) {
      posById[r.robot_id] = [r.x, r.y];
      if (!this.history[r.robot_id]) this.history[r.robot_id] = [];
      const h = this.history[r.robot_id];
      h.push([r.x, r.y]);
      if (h.length > TRAIL_LENGTH) h.shift();
    }

    // trails
    for (const r of frame.robots) {
      const h = this.history[r.robot_id];
      if (h.length < 2) continue;
      ctx.strokeStyle = TASK_STATE_COLORS[r.task_state] || "black";
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      h.forEach(([x, y], i) => {
        const [cx, cy] = this.transform.toCanvas(x, y);
        if (i === 0) ctx.moveTo(cx, cy); else ctx.lineTo(cx, cy);
      });
      ctx.stroke();
      ctx.globalAlpha = 1.0;
    }

    // robots
    for (const r of frame.robots) {
      const [cx, cy] = this.transform.toCanvas(r.x, r.y);
      ctx.beginPath();
      ctx.arc(cx, cy, 5, 0, 2 * Math.PI);
      ctx.fillStyle = TASK_STATE_COLORS[r.task_state] || "black";
      ctx.fill();
      ctx.strokeStyle = "black"; ctx.lineWidth = 0.5; ctx.stroke();
    }

    // conflicts
    ctx.strokeStyle = "gold"; ctx.lineWidth = 2.5;
    for (const [a, b] of frame.conflict_edges || []) {
      if (!posById[a] || !posById[b]) continue;
      const [x1, y1] = this.transform.toCanvas(...posById[a]);
      const [x2, y2] = this.transform.toCanvas(...posById[b]);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    }

    // congestion detours
    for (const rid of frame.detour_robot_ids || []) {
      if (!posById[rid]) continue;
      const [cx, cy] = this.transform.toCanvas(...posById[rid]);
      drawStar(ctx, cx, cy, 8, "magenta");
    }

    // readout
    ctx.fillStyle = "black";
    ctx.font = "13px monospace";
    ctx.fillText(`t=${frame.simulation_time?.toFixed(1)}s  tick=${frame.tick}  robots=${frame.robots.length}`, 8, 16);
  },
};

function drawStar(ctx, cx, cy, r, color) {
  ctx.beginPath();
  for (let i = 0; i < 10; i++) {
    const angle = (Math.PI / 5) * i - Math.PI / 2;
    const radius = i % 2 === 0 ? r : r / 2.5;
    const x = cx + radius * Math.cos(angle);
    const y = cy + radius * Math.sin(angle);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.strokeStyle = "black"; ctx.lineWidth = 0.5; ctx.stroke();
}
