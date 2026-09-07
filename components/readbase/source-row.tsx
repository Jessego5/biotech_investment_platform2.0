"use client";

/**
 * This is one source under an answer, with its two actions, which are
 * deliberately not the same control. The filled one opens what the model was
 * allowed to see, while "sec.gov" is outlined and leaves for the whole
 * document.
 *
 * What the filled control opens depends on what the lookup was. A block cut
 * from a filing opens its stored passage; a block that ranked or filtered rows
 * has no document behind it and opens the rows themselves, which is a table and
 * says so rather than calling itself a passage. Only a block with neither says
 * there is nothing to open.
 */

import { useInspector } from "@/components/readbase/inspector-provider";
import { hostOf } from "@/lib/readbase/api";
import type { SourceListing } from "@/lib/readbase/types";

export function SourceRow({
  source,
  filingUrl,
  links,
  reads = "passage",
  cited = true,
}: {
  source: SourceListing;
  /** One outbound document, the canvas shape. */
  filingUrl?: string;
  /** Or several, where a lookup rested on more than one source. */
  links?: { url: string }[];
  /** The stored passage behind a document, the rows a lookup computed from,
   *  or null when the block left nothing to open. */
  reads?: "passage" | "rows" | null;
  /** False for a lookup the answer never cited. Its number is still the block
   *  number, but it is not a citation, and the warm chip means a mark a reader
   *  can go and find in the prose. */
  cited?: boolean;
}) {
  const { openCitation } = useInspector();

  return (
    <div className="grid grid-cols-[26px_1fr_auto] items-start gap-4 border-b border-border py-[13px]">
      <span
        className={`rounded-[2px] py-[3px] text-center font-mono text-[10.5px] ${
          cited
            ? "bg-cite text-cite-ink"
            : "border border-dashed border-line-hi text-muted-foreground"
        }`}
      >
        {source.n}
      </span>
      <span>
        <span className="block text-[15px] leading-[1.45]">{source.document}</span>
        <span className="mt-[5px] block font-mono text-[10.5px] tracking-[0.02em] text-muted-foreground">
          {source.locator}
        </span>
      </span>
      <span className="flex gap-2">
        {reads ? (
          <button
            type="button"
            onClick={(e) => openCitation(`source-${source.n}`, source.n, e.currentTarget, String(source.n))}
            className="whitespace-nowrap bg-primary px-[9px] py-[5px] font-mono text-[10px] tracking-[0.04em] text-primary-foreground"
          >
            {reads === "rows" ? "Read rows" : "Read passage"}
          </button>
        ) : (
          // nothing stored and no rows to show either; saying so beats a
          // control that opens nothing
          <span className="whitespace-nowrap border border-dashed border-line-hi px-[9px] py-[5px] font-mono text-[10px] tracking-[0.04em] text-muted-foreground">
            no passage
          </span>
        )}
        {/* every source this block rests on, each named by where it goes. One
            for a filing, two for a lookup that read the figures and the
            registry, none for a computed block with no document behind it. */}
        {(links?.length ? links : filingUrl ? [{ url: filingUrl }] : []).map(
          (link) => (
            <a
              key={link.url}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              className="whitespace-nowrap border border-line-hi px-[9px] py-[5px] font-mono text-[10px] tracking-[0.04em] text-ink-2"
            >
              {hostOf(link.url)} &#8599;
            </a>
          ),
        )}

      </span>
    </div>
  );
}
