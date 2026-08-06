"use strict";

const COLORS = {
  green: "#16c784", red: "#ea3943", sma20: "#f0a020", sma50: "#4c9be8", sma200: "#c678dd",
  bb: "rgba(139,152,169,0.7)", rsi: "#eab308", macd: "#22d3ee", macdSignal: "#f472b6",
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

/* ---- Candlestick-grafiek op de detailpagina (lightweight-charts v5) ---- */
let detailChart = null;
let currentRange = "6mo";
const indicatorState = { bb: false, rsi: false, macd: false };
const MAIN_H = 340, OSC_H = 150;

async function renderChart(symbol, range) {
  const el = document.getElementById("chart");
  if (!el || typeof LightweightCharts === "undefined") return;
  const LWC = LightweightCharts;
  if (detailChart) { detailChart.remove(); detailChart = null; }

  const activeOsc = (indicatorState.rsi ? 1 : 0) + (indicatorState.macd ? 1 : 0);
  el.style.height = (MAIN_H + activeOsc * OSC_H) + "px";

  const chart = LWC.createChart(el, {
    autoSize: true,
    layout: { background: { type: (LWC.ColorType && LWC.ColorType.Solid) || "solid", color: "transparent" }, textColor: COLORS.text },
    grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
    rightPriceScale: { borderColor: COLORS.border },
    timeScale: { borderColor: COLORS.border, timeVisible: range === "1d" || range === "5d" },
    crosshair: { mode: LWC.CrosshairMode.Normal },
  });
  detailChart = chart;

  const line = (arr, color, pane, width) => {
    if (!arr || !arr.length) return null;
    const s = chart.addSeries(LWC.LineSeries,
      { color, lineWidth: width || 1.5, priceLineVisible: false, lastValueVisible: false }, pane);
    s.setData(arr);
    return s;
  };

  const candles = chart.addSeries(LWC.CandlestickSeries, {
    upColor: COLORS.green, downColor: COLORS.red,
    wickUpColor: COLORS.green, wickDownColor: COLORS.red, borderVisible: false,
  }, 0);

  let data;
  try {
    data = await fetchPrices(symbol, range);
  } catch (e) {
    el.innerHTML = '<p class="muted">Kon de koersdata niet laden.</p>';
    return;
  }
  candles.setData(data.candles);

  // Pane 0: SMA's + (optioneel) Bollinger Banden
  line(data.sma20, COLORS.sma20, 0);
  line(data.sma50, COLORS.sma50, 0);
  line(data.sma200, COLORS.sma200, 0);
  if (indicatorState.bb) {
    line(data.bb_upper, COLORS.bb, 0, 1);
    line(data.bb_middle, COLORS.bb, 0, 1);
    line(data.bb_lower, COLORS.bb, 0, 1);
  }

  // Onderliggende panes: RSI en/of MACD
  let pane = 1;
  if (indicatorState.rsi && data.rsi.length) {
    const s = line(data.rsi, COLORS.rsi, pane);
    if (s) {
      s.createPriceLine({ price: 70, color: "rgba(234,57,67,0.5)", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "70" });
      s.createPriceLine({ price: 30, color: "rgba(22,199,132,0.5)", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: "30" });
    }
    pane++;
  }
  if (indicatorState.macd && data.macd.length) {
    const h = chart.addSeries(LWC.HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
    h.setData(data.macd_hist);
    line(data.macd, COLORS.macd, pane);
    line(data.macd_signal, COLORS.macdSignal, pane);
    pane++;
  }

  // Hoofd-pane groter houden dan de indicator-strookjes
  const panes = chart.panes ? chart.panes() : [];
  if (panes[0] && panes[0].setStretchFactor) {
    panes[0].setStretchFactor(MAIN_H);
    for (let i = 1; i < panes.length; i++) {
      if (panes[i].setStretchFactor) panes[i].setStretchFactor(OSC_H);
    }
  }

  chart.timeScale().fitContent();
  renderEntry(document.getElementById("entry-badge"), data.entry);
  updateLegend();
}

function updateLegend() {
  document.querySelectorAll(".leg-ind").forEach((el) => {
    el.hidden = !indicatorState[el.dataset.ind];
  });
}

function initDetailChart() {
  const el = document.getElementById("chart");
  if (!el) return;
  const symbol = el.dataset.symbol;

  const rangeBtns = document.querySelectorAll(".range-filter button");
  rangeBtns.forEach((btn) => btn.addEventListener("click", () => {
    rangeBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentRange = btn.dataset.range;
    renderChart(symbol, currentRange);
  }));

  const indBtns = document.querySelectorAll(".indicator-filter button");
  indBtns.forEach((btn) => btn.addEventListener("click", () => {
    const k = btn.dataset.ind;
    indicatorState[k] = !indicatorState[k];
    btn.classList.toggle("active", indicatorState[k]);
    renderChart(symbol, currentRange);
  }));

  const active = document.querySelector(".range-filter button.active");
  currentRange = active ? active.dataset.range : "6mo";
  renderChart(symbol, currentRange);
}

document.addEventListener("DOMContentLoaded", () => {
  loadRows();
  initDetailChart();
});
