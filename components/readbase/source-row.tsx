"use client";

/**
 * This is one source under an answer, with its two actions, which are
 * deliberately not the same control. "Read passage" is filled and opens the
 * stored text the model was allowed to see, while "sec.gov" is outlined and
 * leaves for the whole document.
 */

import { useInspector } from "@/components/readbase/inspector-provider";
import type { SourceListing } from "@/lib/readbase/types";

export function SourceRow({
  source,
  filingUrl,
  readable = true,
}: {
  source: SourceListing;
  filingUrl?: string;
  /** False when the block computed a figure and has no passage to open. */
  readable?: boolean;
}) {
  const { openCitation } = useInspector();

  return (
    <div className="grid grid-cols-[26px_1fr_auto] items-start gap-4 border-b border-border py-[13px]">
      <span className="rounded-[2px] bg-cite py-[3px] text-center font-mono text-[10.5px] text-cite-ink">
        {source.n}
      </span>
      <span>
        <span className="block text-[15px] leading-[1.45]">{source.document}</span>
        <span className="mt-[5px] block font-mono text-[10.5px] tracking-[0.02em] text-muted-foreground">
          {source.locator}
        </span>
      </span>
      <span className="flex gap-2">
        {readable ? (
          <button
            type="button"
            onClick={(e) => openCitation(`source-${source.n}`, source.n, e.currentTarget, String(source.n))}
            className="whitespace-nowrap bg-primary px-[9px] py-[5px] font-mono text-[10px] tracking-[0.04em] text-primary-foreground"
          >
            Read passage
          </button>
        ) : (
          // a computed figure has no passage behind it; saying so beats a
          // control that opens nothing
          <span className="whitespace-nowrap border border-dashed border-line-hi px-[9px] py-[5px] font-mono text-[10px] tracking-[0.04em] text-muted-foreground">
            no passage
          </span>
        )}
        {filingUrl ? (
          <a
            href={filingUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="whitespace-nowrap border border-line-hi px-[9px] py-[5px] font-mono text-[10px] tracking-[0.04em] text-ink-2"
          >
            sec.gov &#8599;
          </a>
        ) : null}
      </span>
    </div>
  );
}
