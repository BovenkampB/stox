"use strict";

const COLORS = {
  green: "#16c784", red: "#ea3943", sma20: "#f0a020", sma50: "#4c9be8", sma200: "#c678dd",
  text: "#8b98a9", grid: "rgba(38,48,64,0.5)", border: "#263040",
};

async function fetchPrices(symbol, range) {
  const res = await fetch(`/api/prices/${encodeURIComponent(symbol)}?range=${range}`);
  if (!res.ok) throw new Error("prices " + res.status);
  return res.json();
}

/* ---- Sparklines op het overzicht (lazy, falen stil) ---- */
function drawSparkline(canvas, closes) {
  if (!closes.length) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width, h = canvas.height;
  canvas.width = w * dpr; canvas.height = h * dpr;
  canvas.style.width = w + "px"; canvas.style.height = h + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const min = Math.min(...closes), max = Math.max(...closes);
  const span = (max - min) || 1;
  const up = closes[closes.length - 1] >= closes[0];
  ctx.strokeStyle = up ? COLORS.green : COLORS.red;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  closes.forEach((v, i) => {
    const x = (i / (closes.length - 1)) * (w - 2) + 1;
    const y = h - 3 - ((v - min) / span) * (h - 6);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

const ENTRY_LABEL = {
  klein: "lichte terugval", flink: "flinke terugval", groot: "grote terugval",
};

function renderEntry(el, entry) {
  if (!el) return;
  if (entry === undefined || entry === null) return;  // laat badge ongewijzigd (bv. intraday)
  if (entry.level === "none") {
    el.textContent = "—";
    el.className = "entry-val muted";
    el.title = "dicht bij de recente top";
    return;
  }
  el.textContent = `${entry.drawdown_pct.toFixed(0)}% t.o.v. top`;
  el.className = "entry-val entry-" + entry.level;
  el.title = ENTRY_LABEL[entry.level] +
    " — koers staat onder de top van de afgelopen maanden (objectief, geen advies)";
}

async function loadRows() {
  const canvases = document.querySelectorAll("canvas.spark");
  for (const canvas of canvases) {
    const row = canvas.closest("tr");
    try {
      const data = await fetchPrices(canvas.dataset.symbol, "6mo");
      drawSparkline(canvas, data.candles.map(c => c.close));
      if (row) renderEntry(row.querySelector(".entry-val"), data.entry);
    } catch (_) {
      const el = row && row.querySelector(".entry-val");
      if (el) { el.textContent = "—"; el.className = "entry-val muted"; }
    }
  }
}

/* ---- Candlestick-grafiek op de detailpagina ---- */
let detailChart = null;

async function renderChart(symbol, range) {
  const el = document.getElementById("chart");
  if (!el || typeof LightweightCharts === "undefined") return;
  if (detailChart) { detailChart.remove(); detailChart = null; }

  const chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: COLORS.text },
    grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
    rightPriceScale: { borderColor: COLORS.border },
    timeScale: { borderColor: COLORS.border, timeVisible: range === "1d" || range === "5d" },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });
  detailChart = chart;

  const candles = chart.addCandlestickSeries({
    upColor: COLORS.green, downColor: COLORS.red,
    wickUpColor: COLORS.green, wickDownColor: COLORS.red, borderVisible: false,
  });

  const addSMA = (arr, color) => {
    if (!arr || !arr.length) return;
    const s = chart.addLineSeries({ color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
    s.setData(arr);
  };

  try {
    const data = await fetchPrices(symbol, range);
    candles.setData(data.candles);
    addSMA(data.sma20, COLORS.sma20);
    addSMA(data.sma50, COLORS.sma50);
    addSMA(data.sma200, COLORS.sma200);
    chart.timeScale().fitContent();
    renderEntry(document.getElementById("entry-badge"), data.entry);
  } catch (e) {
    el.innerHTML = '<p class="muted">Kon de koersdata niet laden.</p>';
  }
}

function initDetailChart() {
  const el = document.getElementById("chart");
  if (!el) return;
  const symbol = el.dataset.symbol;
  const buttons = document.querySelectorAll(".range-filter button");
  buttons.forEach((btn) => btn.addEventListener("click", () => {
    buttons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderChart(symbol, btn.dataset.range);
  }));
  const active = document.querySelector(".range-filter button.active");
  renderChart(symbol, active ? active.dataset.range : "6mo");
}

document.addEventListener("DOMContentLoaded", () => {
  loadRows();
  initDetailChart();
});
