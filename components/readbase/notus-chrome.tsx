import Link from "next/link";
import { API_BASE } from "@/lib/readbase/api";

/**
 * The shell, in the Notus register.
 *
 * The corpus line is still counted at request time rather than written into
 * the page — the register changed, what the interface is allowed to assert
 * did not. If the API cannot be reached it says so instead of showing a
 * number it could not read.
 */
async function corpusLine(): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/stats`, { cache: "no-store" });
    if (!res.ok) return "corpus size unavailable";
    const s = await res.json();
    const n = (v: number) => v.toLocaleString("en-US");
    return `${n(s.companies)} companies · ${n(s.filings)} annual reports · ${n(
      s.trials_total ?? s.trials,
    )} trials`;
  } catch {
    return "corpus size unavailable";
  }
}

const NAV: [string, string][] = [
  ["/companies/VRTX", "Companies"],
  ["/ask", "Ask"],
  ["/watchlist", "Watchlist"],
];

export async function NotusChrome({ current }: { current?: string }) {
  const corpus = await corpusLine();

  return (
    <header className="border-b" style={{ borderColor: "var(--n-line)" }}>
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-x-8 gap-y-3 px-8 py-4">
        <Link href="/" className="text-[19px] font-semibold tracking-[-0.02em]">
          Readbase
        </Link>
        <nav className="flex gap-6 text-[14px]" style={{ color: "var(--n-ink-2)" }}>
          {NAV.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              style={label === current ? { color: "var(--n-accent-deep)" } : undefined}
            >
              {label}
            </Link>
          ))}
        </nav>
        <div className="flex-1" />
        <span className="font-mono text-[10.5px]" style={{ color: "var(--n-ink-2)" }}>
          {corpus}
        </span>
      </div>
    </header>
  );
}
