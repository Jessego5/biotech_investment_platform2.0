/**
 * This is a refusal, which is a designed state and not an error state. It gets
 * the same typographic weight as an answer, the same size and face and full
 * contrast, and its left rule is accent-ink and never warn, because nothing has
 * gone wrong. It is traceable the same way an answer is, showing which accessors
 * ran, what each returned and the row counts, then naming what can be done
 * instead. Rendered on the fixture Ask screen from the copy in lib/readbase/vertex.
 */

import { refusal } from "@/lib/readbase/vertex";

export function RefusalCard() {
  return (
    <div className="mt-11 border border-border border-l-[3px] border-l-primary bg-secondary px-7 pb-[26px] pt-6">
      <h4 className="mb-3 font-mono text-[10px] font-normal uppercase tracking-[0.14em] text-accent-deep">
        {refusal.heading}
      </h4>

      <p className="mb-[18px] max-w-[62ch] text-[19px] leading-[1.6]">
        {refusal.statement}
      </p>

      <div className="border-t border-border pt-[14px]">
        <div className="mb-[9px] font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
          {refusal.queriedCaption}
        </div>
        {refusal.queried.map((row) => (
          <div
            key={row.accessor}
            className="grid grid-cols-[190px_1fr_auto] gap-[14px] py-[5px] font-mono text-[11px] text-ink-2"
          >
            <span>{row.accessor}</span>
            <span className="text-muted-foreground">{row.returned}</span>
            <span className="text-muted-foreground">{row.rows}</span>
          </div>
        ))}
      </div>

      <p className="mt-4 max-w-[62ch] text-[15px] leading-[1.6] text-ink-2">
        {refusal.remedy}
      </p>
    </div>
  );
}
