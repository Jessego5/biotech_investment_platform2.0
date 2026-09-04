import Link from "next/link";
import { NotusChrome } from "@/components/readbase/notus-chrome";
import { notusPage } from "@/lib/readbase/notus-theme";

/**
 * The landing page.
 *
 * It used to list the design demos and the canvas fixtures as well. That was
 * scaffolding from when the artboards were the deliverable and there was no
 * live app to link to, and it should not have survived the corpus arriving:
 * the fixtures carry invented accession numbers and filing text, and a product
 * whose whole claim is traceability cannot offer those from its front door.
 * They still exist, and they now say what they are on the page itself.
 */
const LIVE: [string, string, string][] = [
  [
    "/browse",
    "Browse",
    "Everything held, searchable by name, ticker, brand or accession — companies, approved products, annual reports and trials.",
  ],
  [
    "/ask",
    "Ask",
    "A question against the corpus, answered only from what the accessors return, with the lookups behind it shown.",
  ],
  [
    "/watchlist",
    "Watchlist",
    "A row per company: next readout, nearest loss of protection, how long the money lasts. Kept in this browser.",
  ],
];

function Row({ href, title, note }: { href: string; title: string; note: string }) {
  return (
    <Link
      href={href}
      className="grid grid-cols-1 gap-1 border-b py-4 sm:grid-cols-[220px_1fr] sm:gap-4"
      style={{ borderColor: "var(--n-line)" }}
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
            href="/browse"
            className="rounded-full border bg-white px-6 py-3 text-[15px] font-medium"
            style={{ borderColor: "var(--n-accent)", color: "var(--n-accent-deep)" }}
          >
            Browse the corpus
          </Link>
        </div>
      </div>

      <div className="mx-auto max-w-[900px] px-8 pb-16 pt-10">
        {LIVE.map(([href, title, note]) => (
          <Row key={href} href={href} title={title} note={note} />
        ))}
      </div>
    </div>
  );
}
