import { patentStates, type ProtectionState } from "@/lib/readbase/moderna";

/**
 * The three states differ in kind, not just in colour — filled, outlined,
 * dashed — so the distinction survives greyscale and colour blindness.
 */
const STATE_STYLE: Record<ProtectionState, string> = {
  protected: "bg-accent-deep text-primary-foreground",
  "approved-unlisted": "border border-line-hi text-ink-2",
  "no-product": "border border-dashed border-line-hi text-muted-foreground",
};

export function PatentStates() {
  return (
    <div>
      {patentStates.map((p) => (
        <div key={p.product} className="border-b border-border py-[11px] last:border-b-0">
          <div className="flex flex-wrap items-baseline justify-between gap-x-[10px] gap-y-[6px] text-[13.5px]">
            <span>{p.product}</span>
            <span
              className={`whitespace-nowrap px-[6px] py-[2px] font-mono text-[9.5px] uppercase tracking-[0.08em] ${STATE_STYLE[p.state]}`}
            >
              {p.stateLabel}
            </span>
          </div>
          <div className="mt-[5px] font-mono text-[10.5px] leading-[1.6] text-ink-2">
            {p.detail}
            {p.note && (
              <>
                <br />
                <em className="not-italic text-muted-foreground">{p.note}</em>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
