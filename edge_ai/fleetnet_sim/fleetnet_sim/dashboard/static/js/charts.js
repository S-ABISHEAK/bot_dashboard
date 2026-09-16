// Minimal hand-rolled canvas charts -- no chart library, no CDN, matches
// the dashboard's existing zero-external-dependency design (same reason
// layoutRenderer.js draws the warehouse by hand). Just enough for the
// Report tab's timelines: an axis, gridlines, and one series.

function _chartAxes(ctx, w, h, pad, maxY, xLabel, yLabel) {
  ctx.strokeStyle = "#ccc";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t);
  ctx.lineTo(pad.l, h - pad.b);
  ctx.lineTo(w - pad.r, h - pad.b);
  ctx.stroke();

  ctx.fillStyle = "#666";
  ctx.font = "10px sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(String(Math.round(maxY)), pad.l - 4, pad.t + 8);
  ctx.fillText("0", pad.l - 4, h - pad.b);
  if (yLabel) {
    ctx.save();
    ctx.translate(10, (h - pad.b + pad.t) / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText(yLabel, 0, 0);
    ctx.restore();
  }
  if (xLabel) {
    ctx.textAlign = "center";
    ctx.fillText(xLabel, (w - pad.r + pad.l) / 2, h - 4);
  }
}

function drawLineChart(ctx, points, opts = {}) {
  const w = ctx.canvas.width, h = ctx.canvas.height;
  const pad = { l: 32, r: 10, t: 12, b: 20 };
  ctx.clearRect(0, 0, w, h);
  if (!points.length) {
    ctx.fillStyle = "#999"; ctx.font = "12px sans-serif"; ctx.textAlign = "center";
    ctx.fillText("no data", w / 2, h / 2);
    return;
  }
  const xs = points.map((p) => p.t);
  const ys = points.map((p) => p.y);
  const maxX = Math.max(...xs, 1e-6), maxY = Math.max(...ys, 1e-6);
  const sx = (x) => pad.l + (x / maxX) * (w - pad.l - pad.r);
  const sy = (y) => h - pad.b - (y / maxY) * (h - pad.t - pad.b);

  _chartAxes(ctx, w, h, pad, maxY, opts.xLabel, opts.yLabel);

  ctx.strokeStyle = opts.color || "#2a9d8f";
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = sx(p.t), y = sy(p.y);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawBarChart(ctx, points, opts = {}) {
  const w = ctx.canvas.width, h = ctx.canvas.height;
  const pad = { l: 32, r: 10, t: 12, b: 20 };
  ctx.clearRect(0, 0, w, h);
  if (!points.length || points.every((p) => p.y === 0)) {
    ctx.fillStyle = "#999"; ctx.font = "12px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(points.length ? "none recorded" : "no data", w / 2, h / 2);
    return;
  }
  const xs = points.map((p) => p.t);
  const ys = points.map((p) => p.y);
  const maxX = Math.max(...xs, 1e-6), maxY = Math.max(...ys, 1e-6);
  const plotW = w - pad.l - pad.r;
  const barW = Math.max(1, plotW / points.length - 1);
  const sx = (x) => pad.l + (x / maxX) * plotW;
  const sy = (y) => h - pad.b - (y / maxY) * (h - pad.t - pad.b);

  _chartAxes(ctx, w, h, pad, maxY, opts.xLabel, opts.yLabel);

  ctx.fillStyle = opts.color || "#e76f51";
  for (const p of points) {
    const x = sx(p.t), y = sy(p.y);
    ctx.fillRect(x - barW / 2, y, barW, h - pad.b - y);
  }
}
