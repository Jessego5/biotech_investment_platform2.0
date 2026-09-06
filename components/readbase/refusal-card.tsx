/**
 * This is a refusal, which is a designed state and not an error state. It gets
 * the same typographic weight as an answer, the same size and face and full
 * contrast, because nothing has gone wrong. It is traceable the same way an
 * answer is, showing which accessors ran and what each returned, then naming
 * what can be done instead.
 *
 * The copy is passed in rather than held here: the fixture Ask screen hands it
 * the written refusal in lib/readbase/vertex, and the live screen hands it the
 * model's own sentence and the accessors that actually ran. One implementation,
 * two registers, the container chrome coming from the caller so the card sits
 * in the canvas or in Notus without being rewritten. The canvas marks a refusal
 * with a rule down the left in accent-ink, never in warn; that rule is part of
 * the chrome and comes in with the rest of it.
 */

import type { AccessorResult } from "@/lib/readbase/types";

export function RefusalCard({
  heading,
  statement,
  queriedCaption,
  queried,
  remedy,
  className = "",
}: {
  heading: string;
  /** One paragraph, or several separated by a blank line. */
  statement: string;
  queriedCaption: string;
  /** Empty when nothing was looked up, in which case the section is dropped. */
  queried: AccessorResult[];
  remedy: string;
  /** Border, ground, rounding and any left rule for the register it sits in. */
  className?: string;
}) {
  return (
    <div className={`px-7 pb-[26px] pt-6 ${className}`}>
      <h4 className="mb-3 font-mono text-[10px] font-normal uppercase tracking-[0.14em] text-accent-deep">
        {heading}
      </h4>

      {statement.split("\n\n").map((para, i) => (
        <p key={i} className="mb-[18px] max-w-[62ch] text-[19px] leading-[1.6]">
          {para}
        </p>
      ))}

      {queried.length > 0 && (
        <div className="border-t border-border pt-[14px]">
          <div className="mb-[9px] font-mono text-[10px] uppercase tracking-[0.1em] text-muted-foreground">
            {queriedCaption}
          </div>
          {queried.map((row, i) => (
            <div
              key={`${row.accessor}-${i}`}
              className="grid grid-cols-[190px_1fr_auto] gap-[14px] py-[5px] font-mono text-[11px] text-ink-2"
            >
              <span>{row.accessor}</span>
              <span className="text-muted-foreground">{row.returned}</span>
              <span className="text-muted-foreground">{row.rows}</span>
            </div>
          ))}
        </div>
      )}

      <p className="mt-4 max-w-[62ch] text-[15px] leading-[1.6] text-ink-2">{remedy}</p>
    </div>
  );
}
