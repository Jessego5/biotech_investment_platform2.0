import Link from "next/link";
import { NotusChrome } from "@/components/readbase/notus-chrome";
import { NotusSection } from "@/components/readbase/notus-section";
import { notusCard, notusPage } from "@/lib/readbase/notus-theme";
import { API_BASE } from "@/lib/readbase/api";
import { FilingSections } from "@/components/readbase/filing-sections";

type FilingDetail = {
  accession: string;
  form: string;
  filed: string;
  fiscal_year: number | null;
  period_end: string | null;
  document: string;
  text_chars: number | null;
  company: { ticker: string; name: string; cik: string | null };
  url: string | null;
  sections: { section: string; passages: number; first_chunk_id: number | null }[];
};

async function load(accession: string): Promise<FilingDetail | null> {
  try {
    const res = await fetch(`${API_BASE}/filing/${encodeURIComponent(accession)}`, {
      cache: "no-store",
    });
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}

/**
 * One annual report, as the corpus holds it.
 *
 * The section list is the point of this page. A filing here is not the
 * document — it is the part of the document that was kept — and naming which
 * sections were stored, and how many passages each became, is what stops an
 * answer drawn from one section reading as drawn from the whole filing.
 */
export default async function FilingPage({
  params,
}: {
  params: Promise<{ accession: string }>;
}) {
  const { accession } = await params;
  const f = await load(accession);

  if (!f?.accession) {
    return (
      <div style={notusPage} className="notus min-h-svh">
        <NotusChrome />
        <div className="mx-auto max-w-[900px] px-8 py-10">
          <div className={`${notusCard} px-7 py-6`} style={{ borderColor: "var(--n-line)" }}>
            <h1 className="mb-2 text-[17px] font-medium">No filing under that accession</h1>
            <p className="text-[15px]" style={{ color: "var(--n-ink-2)" }}>
              {accession} is not one of the 3,614 annual reports held, or the API
              could not be reached.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const stored = f.sections.reduce((a, s) => a + s.passages, 0);

  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome current="Browse" />

      <div className="mx-auto max-w-[900px] px-8 pt-9">
        <Link
          href={`/companies/${f.company.ticker}`}
          className="text-[13px]"
          style={{ color: "var(--n-accent-deep)" }}
        >
          {f.company.name}
        </Link>
        <h1 className="mt-2 text-[30px] font-medium tracking-[-0.02em]">
          {f.company.ticker} {f.form}
          {f.fiscal_year ? ` · FY${f.fiscal_year}` : ""}
        </h1>
        <div className="mt-2 pb-7 text-[12px]" style={{ color: "var(--n-ink-2)" }}>
          {[
            `filed ${f.filed}`,
            f.period_end ? `period ended ${f.period_end}` : null,
            `accession ${f.accession}`,
            f.company.cik ? `CIK ${f.company.cik}` : null,
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

      <div className="mx-auto max-w-[900px] space-y-6 px-8 pb-12">
        <NotusSection
          title="What was stored"
          period={`${stored} passages across ${f.sections.length} sections`}
        >
          <FilingSections sections={f.sections} />

          <p className="mt-4 max-w-[74ch] text-[12.5px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
            Only these sections were kept. The filing itself runs to{" "}
            {f.text_chars?.toLocaleString() ?? "an unrecorded number of"} characters,
            so an answer drawn from what is here is drawn from part of the
            document and not the whole of it.
          </p>
        </NotusSection>

        <NotusSection title="The original document" period="SEC EDGAR">
          <p className="mb-4 break-all text-[13px]" style={{ color: "var(--n-accent-deep)" }}>
            {f.url ?? "no EDGAR link — this company has no CIK recorded"}
          </p>
          {f.url && (
            <a
              href={f.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block rounded-full px-5 py-[10px] text-[14px] font-medium text-white"
              style={{ background: "var(--n-accent-deep)" }}
            >
              Open filing on sec.gov ↗
            </a>
          )}
          <p className="mt-4 max-w-[74ch] text-[13px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
            These are not the same thing. What is listed above is the text this
            system was allowed to read. The filing is the complete document it
            was cut from — go there to check that the cut was fair.
          </p>
        </NotusSection>
      </div>
    </div>
  );
}
