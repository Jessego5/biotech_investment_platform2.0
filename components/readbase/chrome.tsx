import { corpus } from "@/lib/readbase/moderna";

/** The wordmark. The D carries the one piece of colour in the chrome. */
export function Wordmark() {
  return (
    <div className="font-mono text-[13px] font-semibold tracking-[0.26em] text-foreground">
      R<span className="text-primary">D</span>B
    </div>
  );
}

/**
 * Top bar, 52px. `crumb` is the path; segments are separated by the muted
 * slash the canvas uses rather than by a glyph inside the strings.
 */
export function Chrome({ crumb }: { crumb: string[] }) {
  return (
    <div className="flex h-[52px] items-center gap-[22px] border-b border-border bg-secondary px-[22px]">
      <Wordmark />
      <div className="font-mono text-[11.5px] tracking-[0.02em] text-ink-2">
        {crumb.map((segment, i) => (
          <span key={segment}>
            {i > 0 && <span className="px-[7px] text-muted-foreground">/</span>}
            {segment}
          </span>
        ))}
      </div>
      <div className="flex-1" />
      <div className="font-mono text-[10.5px] tracking-[0.06em] text-muted-foreground">
        {corpus}
      </div>
    </div>
  );
}
