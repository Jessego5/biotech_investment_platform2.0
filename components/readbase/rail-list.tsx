/**
 * This renders the rail's two-column rows: a mono date or fiscal year, then what
 * it is. The date carries accent-ink in the canvas for both lists, because it is
 * the handle you navigate by rather than decoration. Used for upcoming readouts
 * and for the filings held.
 */
export function RailList({
  items,
}: {
  items: { when: string; what: string; id: string }[];
}) {
  return (
    <div>
      {items.map((item) => (
        <div
          key={item.when + item.id}
          className="grid grid-cols-[74px_1fr] gap-3 border-b border-border py-[10px] last:border-b-0"
        >
          <span className="font-mono text-[11px] tracking-[0.02em] text-primary">
            {item.when}
          </span>
          <span className="text-[13px] leading-[1.45]">
            {item.what}
            <span className="mt-[3px] block font-mono text-[10px] text-muted-foreground">
              {item.id}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}
