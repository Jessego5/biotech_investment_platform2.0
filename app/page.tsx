import Link from "next/link";
import { NotusChrome } from "@/components/readbase/notus-chrome";
import { notusPage } from "@/lib/readbase/notus-theme";

const LIVE: [string, string, string][] = [
  ["/ask", "Ask", "A question against the corpus, answered only from what the accessors return."],
  ["/companies/VRTX", "Company", "Any of the issuers held. VRTX, MRNA, ABBV — the ticker is the route."],
  ["/watchlist", "Watchlist", "A row per company: next readout, nearest loss of protection, how long the money lasts. Kept in this browser."],
];

const EXPLORATIONS: [string, string, string][] = [
  ["/demos", "Design demos", "The same content in four registers — the canvas as built, Tufte sidenotes, an editorial paper, and the Notus template in green."],
];

const FIXTURES: [string, string, string][] = [
  ["/ask/semaglutide", "Source inspector", "The signature screen: what we read, and the document it was cut from."],
  ["/ask/fixture", "Ask, as drawn", "Kept for the refusal card, which needs a question the corpus cannot answer."],
  ["/companies/fixture", "Company, as drawn", "The programme table the corpus cannot yet produce."],
  ["/companies/fixture/what-changed", "What changed", "Both provenance states, including the comparison that is withheld."],
];

function Row({ href, title, note }: { href: string; title: string; note: string }) {
  return (
    <Link
      href={href}
      className="grid grid-cols-[190px_1fr] items-baseline gap-4 border-b border-border py-[13px]"
    >
      <span className="text-[15px]">{title}</span>
      <span className="text-[14px] leading-[1.5] text-ink-2">
        {note}
        <span className="mt-[3px] block font-mono text-[10px] text-muted-foreground">
          {href}
        </span>
      </span>
    </Link>
  );
}

export default function Home() {
  return (
    <div style={notusPage} className="min-h-svh">
      <NotusChrome />
      <div className="mx-auto max-w-[788px] px-8 py-[46px]">
        <p className="mb-[34px] max-w-[62ch] text-[19px] leading-[1.6]">
          Grounded question answering over biotech&rsquo;s primary sources. Every
          figure carries the period it covers and the document it came from, and
          the interface is built so both can be checked rather than taken on
          trust.
        </p>

        <div className="mb-[10px] font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          Live
        </div>
        {LIVE.map(([href, title, note]) => (
          <Row key={href} href={href} title={title} note={note} />
        ))}

        <div className="mb-[10px] mt-[34px] font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          Exploration
        </div>
        {EXPLORATIONS.map(([href, title, note]) => (
          <Row key={href} href={href} title={title} note={note} />
        ))}

        <div className="mb-[10px] mt-[34px] font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
          Fixtures — the artboards as drawn
        </div>
        {FIXTURES.map(([href, title, note]) => (
          <Row key={href} href={href} title={title} note={note} />
        ))}
      </div>
    </div>
  );
}
