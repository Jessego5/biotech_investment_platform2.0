"use client";

import { useState } from "react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { notusCard } from "@/lib/readbase/notus-theme";
import type { EvidenceBlock } from "@/lib/readbase/api";

/**
 * What ran, and what each lookup came back with.
 *
 * The collapsible-steps shape is morphic's, where it shows the tool calls
 * behind an answer and folds itself away once the answer arrives. It is a good
 * fit here for a reason it does not have there: an accessor that ran and found
 * nothing is a fact about the corpus, not a gap in the display. The refusal
 * card has always shown this; there is no reason an answer should show less.
 *
 * So the steps are built from tools_used rather than from the evidence, and a
 * lookup with no block against it reads "no rows" instead of being dropped.
 */
export function AccessorSteps({
  tools,
  evidence,
  dropped = 0,
  defaultOpen = false,
}: {
  tools: string[];
  evidence: EvidenceBlock[];
  dropped?: number;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (!tools.length) return null;

  // One row per call, in the order they were made, each matched to the first
  // block it produced. The same accessor can run twice, so a block is claimed
  // once and not offered to the next call of the same name.
  const claimed = new Set<number>();
  const steps = tools.map((tool) => {
    const index = evidence.findIndex((e, i) => e.tool === tool && !claimed.has(i));
    if (index === -1) return { tool, block: undefined };
    claimed.add(index);
    return { tool, block: evidence[index] };
  });
  const withRows = steps.filter((s) => s.block).length;

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className={`${notusCard} overflow-hidden`}
      style={{ borderColor: "var(--n-line)" }}
    >
      <CollapsibleTrigger className="flex w-full items-center gap-3 px-6 py-4 text-left">
        <span
          className="flex h-6 w-6 items-center justify-center rounded-full text-[11px]"
          style={{ background: "var(--n-accent-soft)", color: "var(--n-accent-deep)" }}
        >
          {steps.length}
        </span>
        <span className="text-[15px] font-medium">
          {steps.length === 1 ? "One lookup ran" : `${steps.length} lookups ran`}
        </span>
        <span className="text-[13px]" style={{ color: "var(--n-ink-2)" }}>
          {withRows} returned rows
          {dropped > 0 && (
            <span style={{ color: "var(--warn)" }}>
              {" · "}
              {dropped} citation{dropped === 1 ? "" : "s"} removed
            </span>
          )}
        </span>
        <span className="flex-1" />
        <span className="text-[13px]" style={{ color: "var(--n-ink-2)" }}>
          {open ? "Hide" : "Show"}
        </span>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="border-t" style={{ borderColor: "var(--n-line)" }}>
          {steps.map(({ tool, block }, i) => (
            <div
              key={`${tool}-${i}`}
              className="grid grid-cols-[180px_1fr_auto] items-baseline gap-4 border-b px-6 py-3 text-[13px] last:border-b-0"
              style={{ borderColor: "var(--n-line)" }}
            >
              <span className="tabular-nums">{tool}</span>
              <span style={{ color: "var(--n-ink-2)" }}>
                {block ? `${block.label} · ${block.source}` : "ran and matched nothing"}
              </span>
              <span
                className="tabular-nums"
                style={{ color: block ? "var(--n-accent-deep)" : "var(--n-ink-2)" }}
              >
                {block ? `block ${block.n}` : "no rows"}
              </span>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
