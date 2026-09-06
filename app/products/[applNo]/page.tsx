/**
 * This is one approved product: the application, the patents listed against it
 * and whatever exclusivity is recorded. Patents are deduplicated and the page
 * says so, because the Orange Book lists one row per dosage form and counting
 * rows reported several times more protection than exists.
 */

import Link from "next/link";
import { NotusChrome } from "@/components/readbase/notus-chrome";
import { NotusSection } from "@/components/readbase/notus-section";
import { StatTiles, type Tile } from "@/components/readbase/stat-tiles";
import { Atom, CalendarClock, Lock, ShieldCheck } from "lucide-react";
import { notusCard, notusPage } from "@/lib/readbase/notus-theme";
import { API_BASE } from "@/lib/readbase/api";

type ProductDetail = {
  appl_no: string;
  trade_name: string | null;
  ingredient: string | null;
  applicant: string | null;
  appl_type: string | null;
  company_ticker: string | null;
  resolved_by: string | null;
  approval_date: string | null;
  products: string[];
  patents: {
    patent_no: string;
    expire_date: string | null;
    drug_substance: boolean;
    drug_product: boolean;
    use_code: string | null;
    delisted: string | null;
    products: number;
  }[];
  patent_rows: number;
  exclusivity: { code: string; expire_date: string | null }[];
};

async function load(applNo: string): Promise<ProductDetail | null> {
  try {
    const res = await fetch(`${API_BASE}/product/${encodeURIComponent(applNo)}`, {
      cache: "no-store",
    });
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}

/**
 * One approved product, and what protects it.
 *
 * Patents and exclusivity are rows here rather than the single word the company
 * page shows. "Protected" is a summary; a patent number with an expiry is a
 * fact, and the two answer different questions.
 */
export default async function ProductPage({
  params,
}: {
  params: Promise<{ applNo: string }>;
}) {
  const { applNo } = await params;
  const p = await load(applNo);

  if (!p?.appl_no) {
    return (
      <div style={notusPage} className="notus min-h-svh">
        <NotusChrome />
        <div className="mx-auto max-w-[900px] px-8 py-10">
          <div className={`${notusCard} px-7 py-6`} style={{ borderColor: "var(--n-line)" }}>
            <h1 className="mb-2 text-[17px] font-medium">No product under that application</h1>
            <p className="text-[15px]" style={{ color: "var(--n-ink-2)" }}>
              Application {applNo} is not in the Orange Book listings held, or the
              API could not be reached.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const soonest = p.patents.find((x) => x.expire_date)?.expire_date ?? null;
  const last = [...p.patents].reverse().find((x) => x.expire_date)?.expire_date ?? null;
  const substance = p.patents.filter((x) => x.drug_substance).length;

  const tiles: Tile[] = [
    {
      icon: ShieldCheck,
      n: String(p.patents.length),
      label: "Patents in force",
      note: `${p.patent_rows} Orange Book rows`,
      source: "FDA Orange Book",
      chip: "var(--p2)",
      glyph: "#020887",
    },
    {
      icon: Atom,
      n: String(substance),
      label: "Composition-of-matter",
      note: substance ? "the strongest claim listed" : "none listed",
      source: "FDA Orange Book",
      chip: "var(--p3)",
      glyph: "#020887",
    },
    {
      icon: CalendarClock,
      n: soonest ?? "–",
      label: "Nearest expiry",
      note: soonest ? "first protection to lapse" : "no dated patent",
      source: "FDA Orange Book",
      chip: "var(--p4)",
      glyph: "#ffffff",
    },
    {
      icon: Lock,
      n: String(p.exclusivity.length),
      label: "Exclusivity periods",
      note: last ? `patents run to ${last}` : "–",
      source: "FDA exclusivity codes",
      chip: "var(--p1)",
      glyph: "#020887",
    },
  ];

  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome current="Browse" />

      <div className="mx-auto max-w-[1180px] px-8 pt-9">
        {p.company_ticker && (
          <Link
            href={`/companies/${p.company_ticker}`}
            className="text-[13px]"
            style={{ color: "var(--n-accent-deep)" }}
          >
            {p.applicant ?? p.company_ticker}
          </Link>
        )}
        <h1 className="mt-2 text-[30px] font-medium tracking-[-0.02em]">
          {p.trade_name ?? p.ingredient}
        </h1>
        <div className="mt-2 pb-7 text-[12px]" style={{ color: "var(--n-ink-2)" }}>
          {[
            p.ingredient,
            `application ${p.appl_no}`,
            p.appl_type ? `type ${p.appl_type}` : null,
            p.approval_date ? `first approved ${p.approval_date}` : null,
            p.products.length
              ? `${p.products.length} product number${p.products.length === 1 ? "" : "s"}`
              : null,
          ]
            .filter(Boolean)
            .map((x, i) => (
              <span key={x as string}>
                {i > 0 && <span className="px-[6px] opacity-60">·</span>}
                {x}
              </span>
            ))}
        </div>
      </div>

      <div className="mx-auto max-w-[1180px] px-8 pb-6">
        <StatTiles tiles={tiles} />
      </div>

      <div className="mx-auto max-w-[1180px] space-y-6 px-8 pb-12">
        <NotusSection
          title="Patents"
          period={`${p.patents.length} distinct · listed as ${p.patent_rows} rows`}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-[14px]">
              <thead>
                <tr style={{ color: "var(--n-ink-2)" }}>
                  {["Patent", "Expires", "Claim", "Use code", "Products"].map((h) => (
                    <th
                      key={h}
                      className="border-b pb-2 text-left text-[13px] font-normal"
                      style={{ borderColor: "var(--n-line)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {p.patents.map((x) => (
                  <tr key={`${x.patent_no}-${x.expire_date}`}>
                    <td className="border-b py-3 tabular-nums" style={{ borderColor: "var(--n-line)" }}>
                      {x.patent_no}
                    </td>
                    <td className="border-b py-3 tabular-nums" style={{ borderColor: "var(--n-line)" }}>
                      {x.expire_date ?? "not stated"}
                    </td>
                    <td className="border-b py-3" style={{ borderColor: "var(--n-line)" }}>
                      {[x.drug_substance && "composition of matter", x.drug_product && "formulation"]
                        .filter(Boolean)
                        .join(" · ") || "method of use only"}
                    </td>
                    <td className="border-b py-3" style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}>
                      {x.use_code ?? "–"}
                    </td>
                    <td className="border-b py-3 tabular-nums" style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}>
                      {x.products}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 max-w-[80ch] text-[12.5px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
            One row per patent, not per patent-and-product-number. The Orange
            Book lists a patent once for each dosage form it covers, so counting
            those rows would report {p.patent_rows} patents where there are{" "}
            {p.patents.length}.
          </p>
        </NotusSection>

        {p.exclusivity.length > 0 && (
          <NotusSection title="Regulatory exclusivity" period="runs on its own clock, separate from the patents">
            <div className="flex flex-wrap gap-2">
              {p.exclusivity.map((e) => (
                <span
                  key={`${e.code}-${e.expire_date}`}
                  className="rounded-full px-[12px] py-[6px] text-[13px]"
                  style={{ background: "var(--n-accent-soft)", color: "var(--n-accent-deep)" }}
                >
                  {e.code}
                  <span className="ml-2 tabular-nums opacity-80">
                    to {e.expire_date ?? "not stated"}
                  </span>
                </span>
              ))}
            </div>
          </NotusSection>
        )}
      </div>
    </div>
  );
}
