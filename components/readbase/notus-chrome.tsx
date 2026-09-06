import Link from "next/link";

/**
 * This is the shell: the wordmark and the three links across the top. It used to
 * carry the corpus size on every page, which was three statements of the same
 * figures, since the front page states them as tiles and Browse is where knowing
 * how much there is to search actually helps. Repeating them in the chrome
 * bought nothing and made every route dynamic, because a header that counts the
 * corpus cannot be rendered ahead of time. Pass current to mark the active link.
 */
const NAV: [string, string][] = [
  // the index over everything, rather than one company chosen arbitrarily
  ["/browse", "Browse"],
  ["/ask", "Ask"],
  ["/watchlist", "Watchlist"],
];

export function NotusChrome({ current }: { current?: string }) {
  return (
    <header className="border-b" style={{ borderColor: "var(--n-line)" }}>
      <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-x-8 gap-y-3 px-8 py-4">
        <Link href="/" className="text-[19px] font-semibold tracking-[-0.02em]">
          BioBase
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
      </div>
    </header>
  );
}
