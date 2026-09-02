import { cashCallout } from "@/lib/readbase/moderna";

/**
 * Two figures from different periods and different definitions must not sit on
 * one line as if they agreed. This gets the citation palette because what it is
 * really saying is "this came from somewhere else" — and it says so in words,
 * not by being a different shade of the same thing.
 */
export function CashCallout() {
  return (
    <div
      className="mt-4 grid grid-cols-[1fr_auto] items-center gap-4 border border-line-hi border-l-[3px] border-l-cite-ink bg-cite px-4 py-[14px] dark:border-l-cite dark:bg-transparent"
    >
      <div className="text-[13.5px] leading-[1.5] text-foreground">
        {cashCallout.label}{" "}
        <b className="font-mono text-[17px] font-normal tracking-[-0.01em]">
          {cashCallout.figure}
        </b>
        <p className="mt-[6px] max-w-[46ch] font-mono text-[10px] leading-[1.5] tracking-[0.03em] text-cite-ink dark:text-cite">
          {cashCallout.caveat}
        </p>
      </div>
      <div className="text-right font-mono text-[10px] leading-[1.7] text-cite-ink dark:text-cite">
        {cashCallout.source.map((line) => (
          <div key={line}>{line}</div>
        ))}
      </div>
    </div>
  );
}
