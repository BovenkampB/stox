"use strict";

const COLORS = {
  green: "#16c784", red: "#ea3943", sma20: "#f0a020", sma50: "#4c9be8",
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

async function loadSparklines() {
  const canvases = document.querySelectorAll("canvas.spark");
  for (const canvas of canvases) {
    try {
      const data = await fetchPrices(canvas.dataset.symbol, "1mo");
      drawSparkline(canvas, data.candles.map(c => c.close));
    } catch (_) { /* stil falen */ }
  }
}

/* ---- Candlestick-grafiek op de detailpagina ---- */
async function loadChart() {
  const el = document.getElementById("chart");
  if (!el || typeof LightweightCharts === "undefined") return;

  const chart = LightweightCharts.createChart(el, {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: COLORS.text },
    grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
    rightPriceScale: { borderColor: COLORS.border },
    timeScale: { borderColor: COLORS.border },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });

  const candles = chart.addCandlestickSeries({
    upColor: COLORS.green, downColor: COLORS.red,
    wickUpColor: COLORS.green, wickDownColor: COLORS.red, borderVisible: false,
  });
  const sma20 = chart.addLineSeries({ color: COLORS.sma20, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
  const sma50 = chart.addLineSeries({ color: COLORS.sma50, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });

  try {
    const data = await fetchPrices(el.dataset.symbol, "6mo");
    candles.setData(data.candles);
    sma20.setData(data.sma20);
    sma50.setData(data.sma50);
    chart.timeScale().fitContent();
  } catch (e) {
    el.innerHTML = '<p class="muted">Kon de koersdata niet laden.</p>';
  }
}

document.addEventListener("DOMContentLoaded", () => {
  loadSparklines();
  loadChart();
});
