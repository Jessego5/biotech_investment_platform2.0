"use client";

import { motion, useReducedMotion } from "motion/react";
import type { PhaseLevel } from "@/lib/readbase/moderna";

/**
 * The phase ramp is the one legitimate gradient in the product, because the
 * variable under it is ordinal. The bar length encodes the same variable as
 * the colour, so the ramp is never the only channel.
 */
const RAMP: Record<PhaseLevel, { fill: string; pct: number }> = {
  1: { fill: "bg-phase-1", pct: 25 },
  2: { fill: "bg-phase-2", pct: 50 },
  3: { fill: "bg-phase-3", pct: 75 },
  4: { fill: "bg-phase-4", pct: 100 },
};

export function PhaseBar({
  phase,
  label,
  index = 0,
}: {
  phase: PhaseLevel;
  label: string;
  /** Row position, for the stagger. */
  index?: number;
}) {
  const { fill, pct } = RAMP[phase];
  const reduce = useReducedMotion();

  return (
    <span className="inline-flex items-center gap-[7px]">
      <span className="relative block h-[7px] w-[52px] bg-phase-na">
        {/* Fills from zero on first paint, staggered down the table, so the
            ramp is read as a scale rather than as ten separate swatches. */}
        <motion.span
          className={`absolute inset-y-0 left-0 block ${fill}`}
          initial={reduce ? false : { width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{
            duration: 0.42,
            delay: index * 0.03,
            ease: [0.22, 1, 0.36, 1],
          }}
        />
      </span>
      <span className="font-mono text-[10.5px] tracking-[0.03em] text-ink-2">
        {label}
      </span>
    </span>
  );
}
