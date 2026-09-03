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
      <span className="text-[15px] font-medium">{title}</span>
      <span className="text-[14px] leading-[1.5]" style={{ color: "var(--n-ink-2)" }}>
        {note}
        <span className="mt-[3px] block text-[11px] opacity-70">{href}</span>
      </span>
    </Link>
  );
}

export default function Home() {
  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome />
      {/* the hero the register is built around: an eyebrow, one large line with
          the emphasis on the word carrying the claim, then the two actions */}
      <div className="mx-auto max-w-[1180px] px-8 pb-4 pt-16 text-center">
        <div className="mb-3 text-[14px]" style={{ color: "var(--n-accent)" }}>
          Grounded question answering over biotech&rsquo;s primary sources
        </div>
        <h1 className="mx-auto mb-5 max-w-[17ch] text-[52px] font-medium leading-[1.06] tracking-[-0.03em]">
          Every figure traced to its{" "}
          <span style={{ color: "var(--n-accent)" }}>filing</span>
        </h1>
        <p
          className="mx-auto mb-8 max-w-[54ch] text-[16px] leading-[1.6]"
          style={{ color: "var(--n-ink-2)" }}
        >
          Every figure carries the period it covers and the document it came
          from, and the interface is built so both can be checked rather than
          taken on trust.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Link
            href="/ask"
            className="rounded-full px-6 py-3 text-[15px] font-medium text-white"
            style={{ background: "var(--n-accent-deep)" }}
          >
            Ask a question
          </Link>
          <Link
            href="/companies/VRTX"
            className="rounded-full border bg-white px-6 py-3 text-[15px] font-medium"
            style={{ borderColor: "var(--n-accent)", color: "var(--n-accent-deep)" }}
          >
            Browse companies
          </Link>
        </div>
      </div>

      <div className="mx-auto max-w-[900px] px-8 pb-16 pt-10">
        <div
          className="mb-3 text-[12px] font-medium uppercase tracking-[0.12em]"
          style={{ color: "var(--n-ink-2)" }}
        >
          Live
        </div>
        {LIVE.map(([href, title, note]) => (
          <Row key={href} href={href} title={title} note={note} />
        ))}

        <div className="mb-3 mt-10 text-[12px] font-medium uppercase tracking-[0.12em]" style={{ color: "var(--n-ink-2)" }}>
          Exploration
        </div>
        {EXPLORATIONS.map(([href, title, note]) => (
          <Row key={href} href={href} title={title} note={note} />
        ))}

        <div className="mb-3 mt-10 text-[12px] font-medium uppercase tracking-[0.12em]" style={{ color: "var(--n-ink-2)" }}>
          Fixtures — the artboards as drawn
        </div>
        {FIXTURES.map(([href, title, note]) => (
          <Row key={href} href={href} title={title} note={note} />
        ))}
      </div>
    </div>
  );
}
