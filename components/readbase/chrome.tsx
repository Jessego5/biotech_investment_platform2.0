import { API_BASE } from "@/lib/readbase/api";

/** The wordmark. The D carries the one piece of colour in the chrome. */
export function Wordmark() {
  return (
    <div className="font-mono text-[13px] font-semibold tracking-[0.26em] text-foreground">
      R<span className="text-primary">D</span>B
    </div>
  );
}

/**
 * What the corpus actually holds, counted at request time.
 *
 * This line was a constant, and the constant drifted: it claimed a trial count
 * the database had never had. A figure describing the data has to come from
 * the data.
 */
async function corpusLine(): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/stats`, { cache: "no-store" });
    if (!res.ok) return "corpus size unavailable";
    const s = await res.json();
    const n = (v: number) => v.toLocaleString("en-US");
    return [
      `${n(s.companies)} companies`,
      `${n(s.filings)} annual reports`,
      // the held count, not the lead-sponsored subset: this line says what the
      // corpus contains, not what any one company is running
      `${n(s.trials_total ?? s.trials)} trials`,
    ].join(" · ");
  } catch {
    // the chrome is not the place to fail loudly, but it must not assert a
    // number it could not read
    return "corpus size unavailable";
  }
}

/**
 * Top bar, 52px. `crumb` is the path; segments are separated by the muted
 * slash the canvas uses rather than by a glyph inside the strings.
 */
export async function Chrome({ crumb }: { crumb: string[] }) {
  const corpus = await corpusLine();
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
