"use client";

/**
 * These are the rows of a year-over-year diff: the group heads with their
 * counts, one row per change, and the inline text diff. Only changed rows are
 * rendered and only changed rows stagger in, so the eye goes to the change
 * rather than to the animation. Used by the what-changed screens.
 */

import { motion, useReducedMotion } from "motion/react";
import type { DiffRow as Row, Mark, TextDiffPart } from "@/lib/readbase/diff";

const MARK_GLYPH: Record<Mark, string> = { plus: "+", minus: "−", eq: "≈" };
const MARK_COLOUR: Record<Mark, string> = {
  plus: "text-good",
  minus: "text-warn",
  eq: "text-muted-foreground",
};
const DELTA_COLOUR = {
  up: "text-good",
  dn: "text-warn",
  na: "text-muted-foreground",
} as const;

export function DiffGroupHead({ heading, count }: { heading: string; count: string }) {
  return (
    <div className="mb-[2px] flex items-baseline gap-3 border-b border-line-hi pb-[7px]">
      <h3 className="m-0 text-[15px] font-normal">{heading}</h3>
      <span className="font-mono text-[10.5px] text-muted-foreground">{count}</span>
    </div>
  );
}

export function DiffRow({ row, index = 0 }: { row: Row; index?: number }) {
  const reduce = useReducedMotion();
  // The rows stagger so the eye travels down the changes. Every row this view
  // produces is a change, there is no "unchanged, shown for context" row in
  // the model, so there is nothing here to filter on. If such a row is ever
  // added it should render without the stagger.

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 4 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.6 }}
      transition={{ duration: 0.3, delay: index * 0.04, ease: "easeOut" }}
      className="grid grid-cols-[20px_1fr_150px_150px_96px] items-baseline gap-4 border-b border-border py-[11px]"
    >
      <span className={`text-center font-mono text-[12px] leading-none ${MARK_COLOUR[row.mark]}`}>
        {MARK_GLYPH[row.mark]}
      </span>
      <span className="text-[14px] leading-[1.45]">
        {row.label}
        <span className="mt-[3px] block font-mono text-[10px] text-muted-foreground">
          {row.sub}
        </span>
      </span>
      <span className="font-mono text-[12.5px] tabular-nums text-ink-2">{row.before}</span>
      <span className="font-mono text-[12.5px] tabular-nums">{row.after}</span>
      <span className={`text-right font-mono text-[12px] tabular-nums ${DELTA_COLOUR[row.direction]}`}>
        {row.delta}
      </span>
    </motion.div>
  );
}

export function DiffGroup({
  heading,
  count,
  rows,
}: {
  heading: string;
  count: string;
  rows: Row[];
}) {
  return (
    <div className="mb-[26px]">
      <DiffGroupHead heading={heading} count={count} />
      {rows.map((row, i) => (
        <DiffRow key={row.label} row={row} index={i} />
      ))}
    </div>
  );
}

/**
 * A rewritten passage, shown as a diff rather than as two blocks of prose, so
 * the eye lands on the words that actually moved. Additions carry the tint and
 * an underline rule; removals go muted and struck through.
 */
export function TextDiff({ parts }: { parts: TextDiffPart[] }) {
  return (
    <p className="mt-[6px] max-w-[92ch] text-[14px] leading-[1.62]">
      {parts.map((part, i) => {
        if (part.kind === "ins") {
          return (
            <ins
              key={i}
              className="bg-tint no-underline"
              style={{ boxShadow: "0 1px 0 var(--accent-mid)" }}
            >
              {part.text}
            </ins>
          );
        }
        if (part.kind === "del") {
          return (
            <del key={i} className="text-muted-foreground line-through">
              {part.text}
            </del>
          );
        }
        return <span key={i}>{part.text}</span>;
      })}
    </p>
  );
}
