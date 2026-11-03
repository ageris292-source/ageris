"use client";

import { useEffect, useRef } from "react";

/**
 * The page background, after GridNova's control-room backdrop: a slowly
 * drifting grid, copper and verdigris "market pulses" that travel along the
 * grid lines, and a faint candlestick skyline on the horizon.
 *
 * Purely decorative (aria-hidden), pointer-events none. Pulses stop when the
 * tab is hidden and are not drawn at all with prefers-reduced-motion.
 */

const CELL = 64;
const MAX_PULSES = 9;

type Pulse = { x: number; y: number; dx: number; dy: number; life: number; max: number; alt: boolean };

function cssTriplet(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function GridBackdrop() {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;

    let w = 0;
    let h = 0;
    let raf = 0;
    let last = performance.now();
    const pulses: Pulse[] = [];
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const resize = () => {
      w = window.innerWidth;
      h = window.innerHeight;
      el.width = Math.round(w * dpr);
      el.height = Math.round(h * dpr);
      el.style.width = `${w}px`;
      el.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const spawn = () => {
      const horizontal = Math.random() < 0.6;
      const cols = Math.ceil(w / CELL);
      const rows = Math.ceil(h / CELL);
      const speed = 70 + Math.random() * 90; // px per second
      const dir = Math.random() < 0.5 ? 1 : -1;
      const max = 2.5 + Math.random() * 3;
      pulses.push(
        horizontal
          ? { x: dir > 0 ? -40 : w + 40, y: Math.floor(Math.random() * rows) * CELL, dx: dir * speed, dy: 0, life: 0, max, alt: Math.random() < 0.45 }
          : { x: Math.floor(Math.random() * cols) * CELL, y: dir > 0 ? -40 : h + 40, dx: 0, dy: dir * speed, life: 0, max, alt: Math.random() < 0.45 },
      );
    };

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      ctx.clearRect(0, 0, w, h);
      if (pulses.length < MAX_PULSES && Math.random() < dt * 1.6) spawn();
      const copper = cssTriplet("--bg-pulse", "176, 92, 32");
      const green = cssTriplet("--bg-pulse-2", "22, 110, 98");
      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i];
        p.life += dt;
        p.x += p.dx * dt;
        p.y += p.dy * dt;
        if (p.life > p.max || p.x < -80 || p.x > w + 80 || p.y < -80 || p.y > h + 80) {
          pulses.splice(i, 1);
          continue;
        }
        const fade = Math.min(1, p.life / 0.6, (p.max - p.life) / 0.8);
        const rgb = p.alt ? green : copper;
        const len = 90;
        const tx = p.x - Math.sign(p.dx) * len;
        const ty = p.y - Math.sign(p.dy) * len;
        const g = ctx.createLinearGradient(tx, ty, p.x, p.y);
        g.addColorStop(0, `rgba(${rgb}, 0)`);
        g.addColorStop(1, `rgba(${rgb}, ${0.55 * fade})`);
        ctx.strokeStyle = g;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        ctx.fillStyle = `rgba(${rgb}, ${0.8 * fade})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.8, 0, Math.PI * 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(frame);
    };

    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };

    resize();
    raf = requestAnimationFrame(frame);
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div aria-hidden className="grid-backdrop pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="grid-backdrop__lines" />
      <canvas ref={canvas} className="absolute inset-0" />
      <CandleSkyline />
    </div>
  );
}

/** A faint row of candlesticks on the horizon: the markets' skyline. */
function CandleSkyline() {
  // Deterministic pseudo-random walk so the skyline is stable between renders.
  const candles: { x: number; open: number; close: number; high: number; low: number }[] = [];
  let level = 60;
  let seed = 7;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  for (let i = 0; i < 72; i++) {
    const open = level;
    const close = Math.max(18, Math.min(110, open + (rand() - 0.47) * 22));
    const high = Math.max(open, close) + rand() * 10;
    const low = Math.min(open, close) - rand() * 10;
    candles.push({ x: i * 20 + 6, open, close, high, low });
    level = close;
  }
  return (
    <svg
      className="absolute inset-x-0 bottom-0 h-[22vh] w-full opacity-[0.16] dark:opacity-[0.22]"
      viewBox="0 0 1440 140"
      preserveAspectRatio="none"
    >
      {candles.map((c) => {
        const up = c.close >= c.open;
        const top = 140 - Math.max(c.open, c.close);
        const height = Math.max(2, Math.abs(c.close - c.open));
        return (
          <g key={c.x} fill={up ? "var(--accent)" : "var(--copper)"} stroke={up ? "var(--accent)" : "var(--copper)"}>
            <line x1={c.x + 4} x2={c.x + 4} y1={140 - c.high} y2={140 - c.low} strokeWidth={1.2} />
            <rect x={c.x} y={top} width={8} height={height} rx={1} />
          </g>
        );
      })}
    </svg>
  );
}
