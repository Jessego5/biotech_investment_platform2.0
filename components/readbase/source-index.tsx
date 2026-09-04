"use client";

import { useInspector } from "@/components/readbase/inspector-provider";
import { extentFor } from "@/lib/readbase/semaglutide";
import type { Source } from "@/lib/readbase/types";

/**
 * Every source the answer stands on, including the ones not currently open.
 * The count is the point: four sources, and you can see all four without
 * opening anything. Rows open the same panel the chips do.
 */
export function SourceIndex({ sources }: { sources: Source[] }) {
  const { open, openCitation, hovered, setHovered } = useInspector();

  return (
    <div className="mt-auto border-t border-border pb-[18px] pt-[14px]">
      <div className="mb-[10px] font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        Sources this answer stands on
      </div>
      {sources.map((s) => {
        const current = s.n === open?.source;
        // Hovering a citation in the prose lights its row here, and vice
        // versa. No motion — the brief is explicit that this is a colour
        // change, not an animation.
        const lit = current || s.n === hovered;
        return (
          <button
            key={s.n}
            type="button"
            onClick={(e) => openCitation(`source-${s.n}`, s.n, e.currentTarget, String(s.n))}
            onMouseEnter={() => setHovered(s.n)}
            onMouseLeave={() => setHovered(null)}
            data-active={lit || undefined}
            className={`grid w-full grid-cols-[22px_1fr_auto] items-baseline gap-[14px] border-t border-border text-left first:border-t-0 ${
              lit ? "-mx-3 w-[calc(100%+1.5rem)] bg-tint px-3 py-[7px]" : "py-[7px]"
            }`}
          >
            <span className="rounded-[2px] bg-cite py-[3px] text-center font-mono text-[10.5px] text-cite-ink">
              {s.n}
            </span>
            <span className="font-mono text-[11px] leading-[1.5] text-ink-2">
              <b className="font-normal text-foreground">{s.document}</b> · {s.locator}
            </span>
            <span className="whitespace-nowrap font-mono text-[9.5px] tracking-[0.06em] text-muted-foreground">
              {current ? "open" : extentFor(s.n)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
