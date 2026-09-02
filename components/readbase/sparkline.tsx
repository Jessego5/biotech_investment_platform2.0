"use client";

import { motion, useReducedMotion } from "motion/react";
import type { Series } from "@/lib/readbase/moderna";
import { fiscalYears } from "@/lib/readbase/moderna";

/* Canvas geometry: 470 × 44, plotted between x 5→465 and y 39 (min) → 5 (max). */
const W = 470;
const H = 44;
const X0 = 5;
const X1 = 465;
const Y_MIN = 39;
const Y_MAX = 5;

function plot(values: number[]) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const step = (X1 - X0) / (values.length - 1);
  const points = values.map((v, i) => ({
    x: X0 + i * step,
    y: Y_MIN - ((v - lo) / span) * (Y_MIN - Y_MAX),
  }));
  const zeroY = Y_MIN - ((0 - lo) / span) * (Y_MIN - Y_MAX);
  return { points, zeroY };
}

/**
 * Ten fiscal years. The line is never read on its own — all ten values are
 * printed beneath it in mono, so the sparkline is an aid to the numbers
 * rather than a substitute for them.
 */
export function Sparkline({ series }: { series: Series }) {
  const years = series.years ?? fiscalYears;
  const { points, zeroY } = plot(series.values);
  const reduce = useReducedMotion();
  const peak = points[series.peakIndex];
  const last = points[points.length - 1];

  return (
    <div className="border-b border-border pb-[15px] pt-[14px]">
      <div className="mb-2 flex items-baseline justify-between">
        <span className="text-[13.5px]">
          {series.name}
          <span className="ml-[5px] font-mono text-[9.5px] tracking-[0.06em] text-muted-foreground">
            {series.unit}
          </span>
        </span>
        <span className="font-mono text-[11px] tabular-nums text-ink-2">
          {series.first} <span className="text-muted-foreground">&rarr;</span>{" "}
          <span className="text-foreground">{series.last}</span>
        </span>
      </div>

      {/* Fixed at 470×44 wherever the column allows it, so the artboard width
          renders exactly as drawn; below that it scales down rather than
          overrunning into the neighbouring sparkline. */}
      <svg
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto max-w-full"
        aria-hidden="true"
      >
        {series.zeroRule && (
          <line
            x1={X0}
            y1={zeroY.toFixed(1)}
            x2={X1}
            y2={zeroY.toFixed(1)}
            stroke="var(--line-hi)"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
        )}
        {/* Draws once, the first time it is scrolled into view — not on
            every scroll past. */}
        <motion.polyline
          points={points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={1.25}
          strokeLinejoin="round"
          strokeLinecap="round"
          initial={reduce ? false : { pathLength: 0 }}
          whileInView={{ pathLength: 1 }}
          viewport={{ once: true, amount: 0.4 }}
          transition={{ duration: 0.85, ease: "easeOut" }}
        />
        {/* peak year, named below the line as well as marked on it */}
        <motion.circle
          cx={peak.x.toFixed(1)}
          cy={peak.y.toFixed(1)}
          r={2.6}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={1}
          initial={reduce ? false : { opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, amount: 0.4 }}
          transition={{ duration: 0.25, delay: 0.7 }}
        />
        {/* most recent year */}
        <motion.circle
          cx={last.x.toFixed(1)}
          cy={last.y.toFixed(1)}
          r={2}
          fill="var(--primary)"
          initial={reduce ? false : { opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, amount: 0.4 }}
          transition={{ duration: 0.25, delay: 0.8 }}
        />
      </svg>

      {/* 13px, not 7: preflight makes <svg> a block, so the gap the canvas
          gets from the inline descender has to be stated explicitly. */}
      <div
        className="mt-[13px] grid border-t border-border pt-[6px]"
        style={{ gridTemplateColumns: `repeat(${series.values.length}, minmax(0, 1fr))` }}
      >
        {series.values.map((v, i) => (
          <div key={years[i]} className="flex flex-col items-center gap-[2px]">
            <span className="font-mono text-[8.5px] tracking-[0.02em] text-muted-foreground">
              &rsquo;{String(years[i]).slice(2)}
            </span>
            <span
              className={`font-mono text-[10px] tabular-nums ${
                i === series.peakIndex ? "text-foreground" : "text-ink-2"
              }`}
            >
              {v < 0 ? `(${Math.abs(v).toFixed(1)})` : v.toFixed(1)}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-[5px] font-mono text-[9px] uppercase tracking-[0.07em] text-muted-foreground">
        {series.peakLabel}
      </div>
    </div>
  );
}
