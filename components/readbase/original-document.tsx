"use client";

/**
 * This is the original document, the second of the two checks, and it is
 * deliberately not the same control as the first. It sits on the recessed plane,
 * below a heavier rule, behind an outlined outbound button rather than a filled
 * one, and the sentence at the bottom exists so nobody has to infer the
 * difference from the styling alone. Rendered under the passage panel.
 */

import { original } from "@/lib/readbase/semaglutide";
import type { OriginalRecord } from "@/lib/readbase/passages";

export function OriginalDocument({ record }: { record?: OriginalRecord }) {
  const source = record
    ? {
        caption: record.caption ?? original.caption,
        url: record.displayUrl,
        href: record.url ?? undefined,
        fields: record.fields,
        action: record.action ?? original.action,
        distinction: record.distinction ?? original.distinction,
      }
    : original;
  return (
    <div className="border-t border-line-hi bg-background px-[26px] pb-5 pt-[18px]">
      <div className="mb-[9px] font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
        {source.caption}
      </div>

      <div className="mb-3 break-all font-mono text-[11px] leading-[1.6] text-primary">
        {source.url}
      </div>

      <dl className="mb-[14px] grid grid-cols-[auto_1fr] gap-x-4 gap-y-[3px]">
        {source.fields.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="font-mono text-[10px] tracking-[0.06em] text-muted-foreground">
              {key}
            </dt>
            <dd className="m-0 font-mono text-[11px] text-ink-2">{value}</dd>
          </div>
        ))}
      </dl>

      <a
        href={source.href}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block border border-ink-2 px-[14px] py-2 font-mono text-[11px] tracking-[0.05em] text-foreground"
      >
        {source.action}
      </a>

      <p className="mt-[14px] max-w-[52ch] text-[13px] leading-[1.55] text-ink-2">
        {source.distinction}
      </p>
    </div>
  );
}
