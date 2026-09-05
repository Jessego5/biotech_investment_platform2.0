import Link from "next/link";
import { NotusChrome } from "@/components/readbase/notus-chrome";
import { notusPage } from "@/lib/readbase/notus-theme";
import { StatTiles, type Tile } from "@/components/readbase/stat-tiles";
import { ChartColumn, FileText, FlaskConical, Pill } from "lucide-react";
import { API_BASE } from "@/lib/readbase/api";

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

type Stats = {
  companies: number;
  filings: number;
  trials: number;
  trials_total: number;
  registry_trials: number;
  approved_products: number;
  financial_facts: number;
};

async function stats(): Promise<Stats | null> {
  try {
    const res = await fetch(`${API_BASE}/stats`, { cache: "no-store" });
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}

/**
 * What the corpus holds, and where each part of it came from.
 *
 * The four steps run pale to indigo in the same order the company page uses,
 * and each one still keys to a source: ClinicalTrials.gov, the Orange Book,
 * SEC XBRL facts, EDGAR. Four tiles, four sources, so the ramp and the key
 * agree instead of one having to give way to the other.
 *
 * Counted at request time. These are the figures the product is built on, and
 * typing them in by hand is how the banner drifted twice.
 */
function corpusTiles(s: Stats): Tile[] {
  // a field the API does not send yet is a dash, not a crash. /stats has grown
  // three times, and each time a page built against the newer shape would have
  // thrown on the older one — server-side, so the whole page went with it
  const n = (v?: number) => (typeof v === "number" ? v.toLocaleString("en-US") : "—");
  return [
    {
      icon: FlaskConical,
      n: n(s.trials_total),
      label: "Registered trials",
      note: `${n(s.trials)} lead-sponsored`,
      source: "ClinicalTrials.gov",
      chip: "var(--p1)",
      glyph: "#020887",
    },
    {
      icon: Pill,
      n: n(s.approved_products),
      label: "Approved products",
      note: "distinct applications",
      source: "FDA Orange Book",
      chip: "var(--p2)",
      glyph: "#020887",
    },
    {
      icon: ChartColumn,
      n: n(s.financial_facts),
      label: "Reported figures",
      note: "ten years, per metric",
      source: "SEC XBRL company facts",
      chip: "var(--p3)",
      glyph: "#020887",
    },
    {
      icon: FileText,
      n: n(s.filings),
      label: "Annual reports",
      note: "five years per company",
      source: "SEC EDGAR",
      chip: "var(--p4)",
      glyph: "#ffffff",
    },
  ];
}

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

export default async function Home() {
  const s = await stats();
  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome />

      <div className="mx-auto max-w-[1180px] px-8 pb-4 pt-16 text-center">
        {/* Not "every US biotech": 107 of these file 20-F as foreign private
            issuers, so the universe is defined by filing with the SEC rather
            than by country. And not simply "every filer" either — the rule is
            every SEC filer with a ticker that leads its own clinical trials and
            files real financials, which is the claim worth making because it
            says the list was not curated. */}
        <div className="mb-3 text-[14px]" style={{ color: "var(--n-accent)" }}>
          Every SEC filer that leads its own clinical trials
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

      {s && (
        <div className="mx-auto max-w-[1180px] px-8 pb-2 pt-6">
          <StatTiles tiles={corpusTiles(s)} />
          <p
            className="mt-3 text-center text-[12.5px]"
            style={{ color: "var(--n-ink-2)" }}
          >
            Counted now, not written into the page. The colour on each tile is
            the source the figure came from, and it means the same thing on
            every other screen.
          </p>
        </div>
      )}

      <div className="mx-auto max-w-[900px] px-8 pb-16 pt-10">
        {LIVE.map(([href, title, note]) => (
          <Row key={href} href={href} title={title} note={note} />
        ))}
      </div>
    </div>
  );
}
