/**
 * This is the live company page: pipeline by phase, the financial series with
 * every value printed, what the company has approved and what protects it, and
 * the trials it leads. Every figure carries the period it covers, and where two
 * figures come from different periods or different definitions the page says so
 * rather than letting them sit on one line as if they agreed. The interventions
 * table merges names the registry itself calls equivalent, so one drug filed
 * under three names is one row. Rendered by app/companies/[ticker], which
 * fetches the company server-side.
 */

import { NotusChrome } from "@/components/readbase/notus-chrome";
import { notusCard, notusPage } from "@/lib/readbase/notus-theme";
import { StatTiles, PhaseDonut, type Tile } from "@/components/readbase/stat-tiles";
import { ChartColumn, FileText, FlaskConical, Pill } from "lucide-react";
import { NotusSection as Section } from "@/components/readbase/notus-section";
import { PhaseBar } from "@/components/readbase/phase-bar";
import { Sparkline } from "@/components/readbase/sparkline";
import { RailList } from "@/components/readbase/rail-list";
import { PeriodLabel } from "@/components/readbase/period-label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { API_BASE } from "@/lib/readbase/api";
import {
  currencyName,
  money,
  phaseLabel,
  phaseLevel,
  protectionState,
  toSeries,
  type CompanyResponse,
} from "@/lib/readbase/company";

const STATE_STYLE: Record<string, string> = {
  protected: "bg-accent-deep text-primary-foreground",
  "approved-unlisted": "border border-line-hi text-ink-2",
  "no-product": "border border-dashed border-line-hi text-muted-foreground",
};

async function load(ticker: string): Promise<CompanyResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/company/${ticker.toUpperCase()}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function LiveCompany({ ticker }: { ticker: string }) {
  const data = await load(ticker);

  if (!data?.ticker) {
    return (
      <div style={notusPage} className="notus min-h-svh">
        <NotusChrome current="Companies" />
        <div className="px-[30px] py-[26px]">
          <div className={`${notusCard} max-w-[62ch] px-7 pb-7 pt-6`} style={{ borderColor: "var(--n-line)" }}>
            <h4 className="mb-2 text-[17px] font-medium">
              Nothing held for this ticker
            </h4>
            <p className="text-[15px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
              {ticker.toUpperCase()} is not one of the issuers in this corpus, or
              the API could not be reached.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const history = data.financial_history ?? {};
  const series = [
    toSeries("Total revenue", history.revenue),
    toSeries("Research and development", history.rd_expense),
    toSeries("Net income / (loss)", history.net_income, { zeroRule: true }),
    toSeries("Cash and equivalents, at year end", history.cash),
  ].filter(Boolean);

  const byPhase = Object.entries(
    Object.entries(data.pipeline?.by_phase ?? {}).reduce<Record<string, number>>(
      (acc, [phase, n]) => {
        const label = phaseLabel(phase);
        acc[label] = (acc[label] ?? 0) + n;
        return acc;
      },
      {},
    ),
  )
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);

  const rd = toSeries("R&D", data.financial_history?.rd_expense);
  const tiles: Tile[] = [
    {
      icon: FlaskConical,
      n: String(data.pipeline?.total_trials ?? 0),
      label: "Registered trials",
      note: `${byPhase[0]?.[1] ?? 0} in ${byPhase[0]?.[0] ?? "–"}`,
      source: "ClinicalTrials.gov",
      chip: "var(--p1)",
      glyph: "#020887",
    },
    {
      icon: Pill,
      n: String((data.approved_products ?? []).length),
      label: "Approved products",
      note: data.protection?.state ?? "–",
      source: "FDA Orange Book",
      chip: "var(--p2)",
      glyph: "#020887",
    },
    {
      icon: ChartColumn,
      n: rd ? rd.last.replace(/^FY\d+\s/, "") : "–",
      label: "Research and development",
      // the currency named, not left as three letters: this tile is the first
      // figure on the page and often the only one a reader looks at
      note: rd
        ? [`FY${rd.years![rd.years!.length - 1]}`,
           rd.currency && rd.currency !== "USD"
             ? currencyName(rd.currency)
             : null].filter(Boolean).join(" · ")
        : "–",
      source: "SEC XBRL company facts",
      chip: "var(--p3)",
      glyph: "#020887",
    },
    {
      icon: FileText,
      n: String((data.filings ?? []).length),
      label: "Annual reports held",
      note: (data.filings ?? []).length
        ? `FY${data.filings[data.filings.length - 1].fiscal_year}–FY${data.filings[0].fiscal_year}`
        : "–",
      source: "SEC EDGAR",
      chip: "var(--p4)",
      glyph: "#ffffff",
    },
  ];

  const protection = data.protection;
  const state = protectionState(protection?.state);
  const products = data.approved_products ?? [];
  const filings = data.filings ?? [];
  // the registry spells the same bucket more than one way, "N/A" and "NA" are
  // one absence, not two, so they are merged on the label they display under
  const interventions = data.interventions ?? [];

  return (
    <div id="top" style={notusPage} className="notus min-h-svh">
      <NotusChrome current="Companies" />

      <div className="mx-auto max-w-[1180px] px-8 pt-9">
        <div className="flex flex-wrap items-baseline gap-[14px]">
          <h1 className="text-[30px] font-medium tracking-[-0.02em]">{data.name}</h1>
          <span
            className="rounded-full px-[10px] py-[4px] font-mono text-[12px]"
            style={{ background: "var(--n-accent-soft)", color: "var(--n-accent-deep)" }}
          >
            {data.ticker}
          </span>
        </div>
        <div className="mt-2 pb-7 font-mono text-[11px]" style={{ color: "var(--n-ink-2)" }}>
          {[
            data.cik ? `CIK ${data.cik}` : null,
            `${filings.length} annual report${filings.length === 1 ? "" : "s"} held`,
            `${data.pipeline?.total_trials ?? 0} registered trials`,
            `${products.length} approved product${products.length === 1 ? "" : "s"}`,
          ]
            .filter(Boolean)
            .map((item, i) => (
              <span key={item as string}>
                {i > 0 && <span className="px-[6px] opacity-60">·</span>}
                {item}
              </span>
            ))}
        </div>
      </div>

      <div className="mx-auto max-w-[1180px] px-8 pb-6">
        <StatTiles tiles={tiles} />
      </div>

      <div className="mx-auto grid max-w-[1180px] grid-cols-1 gap-6 px-8 pb-12 lg:grid-cols-[1fr_340px]">
        <div className="min-w-0 space-y-6">
          <Section
            id="phases"
            title="Trials by phase"
            period="ClinicalTrials.gov · lead and collaborator"
          >
            <PhaseDonut slices={byPhase.map(([label, n]) => ({ label, n }))} />
          </Section>

          {/* Approved products, then trials. Deliberately two sections: the
              database records what is marketed and what is being studied, and
              has no record of the programme in between. Presenting trials as a
              programme pipeline would be inferring the thing that is missing. */}
          <Section
            id="approved"
            title="Approved products"
            period="FDA Orange Book and Purple Book · earliest approval per product"
          >
            {products.length ? (
              <Table className="w-full min-w-[640px] caption-bottom border-collapse text-[13.5px]">
                <TableHeader>
                  <TableRow className="border-b border-border">
                    {["Product", "Ingredient", "Status", "Approved", "Applications"].map(
                      (h, i) => (
                        <TableHead
                          key={h}
                          className={`h-auto whitespace-normal border-b border-border px-0 pb-[7px] pr-[10px] align-middle font-mono text-[9.5px] font-normal uppercase tracking-[0.11em] text-muted-foreground ${
                            i === 4 ? "pr-0 text-right" : "text-left"
                          }`}
                        >
                          {h}
                        </TableHead>
                      ),
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {products.map((p) => (
                    <TableRow key={p.trade_name ?? p.ingredient} className="border-b border-border">
                      <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-middle">
                        <span className="font-mono text-[12px]">{p.trade_name}</span>
                      </TableCell>
                      <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-middle text-[13.5px]">
                        {p.ingredient}
                      </TableCell>
                      <TableCell className="px-0 py-2 pr-[10px] align-middle">
                        <PhaseBar phase={4} label="Approved" />
                      </TableCell>
                      <TableCell className="px-0 py-2 pr-[10px] align-middle font-mono text-[12px] tabular-nums">
                        {p.approval_date ?? "–"}
                      </TableCell>
                      <TableCell className="px-0 py-2 text-right align-middle font-mono text-[12px] tabular-nums">
                        {p.applications.length}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="max-w-[62ch] text-[14px] leading-[1.6] text-ink-2">
                Nothing approved. Most issuers in this corpus have no marketed
                product, which is a fact about the company rather than a gap in
                the data.
              </p>
            )}
          </Section>

          <Section
            id="interventions"
            title="Interventions studied"
            period={`${Math.min(12, interventions.length)} of ${interventions.length} · furthest phase first · lead-sponsored trials`}
          >
            {interventions.length ? (
              <>
                <Table className="w-full min-w-[640px] caption-bottom border-collapse text-[13.5px]">
                  <TableHeader>
                    <TableRow className="border-b border-border">
                      {["Intervention", "Indications", "Furthest phase", "Lead trial", "Trials"].map(
                        (h, i) => (
                          <TableHead
                            key={h}
                            className={`h-auto whitespace-normal border-b border-border px-0 pb-[7px] pr-[10px] align-middle font-mono text-[9.5px] font-normal uppercase tracking-[0.11em] text-muted-foreground ${
                              i === 4 ? "pr-0 text-right" : "text-left"
                            }`}
                          >
                            {h}
                          </TableHead>
                        ),
                      )}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {interventions.slice(0, 12).map((iv) => (
                      <TableRow key={iv.name} className="border-b border-border">
                        <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-middle">
                          <span className="font-mono text-[12px]">{iv.name}</span>
                          {iv.approved_as && (
                            <span className="mt-[2px] block font-mono text-[10px] text-muted-foreground">
                              marketed as {iv.approved_as}
                            </span>
                          )}
                          {iv.also_known_as?.length > 0 && (
                            <span className="mt-[2px] block max-w-[34ch] font-mono text-[10px] leading-[1.5] text-muted-foreground">
                              also filed as {iv.also_known_as.join(", ")}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-middle text-[13.5px]">
                          {iv.conditions.join(", ") || "–"}
                        </TableCell>
                        <TableCell className="px-0 py-2 pr-[10px] align-middle">
                          {phaseLevel(iv.phase) ? (
                            <PhaseBar
                              phase={phaseLevel(iv.phase)!}
                              label={phaseLabel(iv.phase)}
                            />
                          ) : (
                            <span className="font-mono text-[10.5px] text-muted-foreground">
                              {phaseLabel(iv.phase)}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="px-0 py-2 pr-[10px] align-middle font-mono text-[12px] tabular-nums">
                          {iv.lead_nct ?? "–"}
                        </TableCell>
                        <TableCell className="px-0 py-2 text-right align-middle font-mono text-[12px] tabular-nums">
                          {iv.trials}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <div className="mt-3 max-w-[80ch] space-y-2 font-mono text-[10px] leading-[1.6] text-muted-foreground">
                  <p>
                    Grouped by the name the registry gives it, and cut to the
                    twelve furthest along. The count in the heading says how
                    many there are, so a short table is not read as a short
                    pipeline. Names are merged only where the registry states they are the
                    same thing. Ivacaftor is filed as IVA and VX-770, and
                    ClinicalTrials.gov says so, so those rows are one, and the
                    names it absorbed are listed under it, because a count that
                    quietly combined three things cannot be checked. Where a
                    sponsor never filled that field in, one drug can still
                    appear twice, and it is left as two rows rather than guessed
                    into one.
                  </p>
                  <p>
                    An arm is also not always the sponsor&rsquo;s own candidate.
                    A comparator, a combination partner or a device arm is
                    listed the same way, and the registry does not say who owns
                    what. Where a name matches an approved product&rsquo;s
                    ingredient, the FDA states that link and it is shown.
                  </p>
                </div>
              </>
            ) : (
              <p className="max-w-[62ch] text-[14px] leading-[1.6] text-ink-2">
                No trial held for this company records what it tested.
              </p>
            )}
          </Section>

          <Section
            id="trials"
            title="Registered trials"
            period={`${Math.min(20, (data.trials ?? []).length)} of ${data.pipeline?.total_trials ?? 0} studies · ClinicalTrials.gov`}
          >
            <div className="mb-4 flex flex-wrap gap-x-5 gap-y-2">
              {byPhase.map(([label, n]) => (
                <span key={label} className="inline-flex items-baseline gap-2">
                  {phaseLevel(label) ? (
                    <PhaseBar phase={phaseLevel(label)!} label={label} />
                  ) : (
                    <span className="font-mono text-[10.5px] text-muted-foreground">
                      {label}
                    </span>
                  )}
                  <span className="font-mono text-[12px] tabular-nums">{n}</span>
                </span>
              ))}
            </div>

            <Table className="w-full min-w-[640px] caption-bottom border-collapse text-[13.5px]">
              <TableHeader>
                <TableRow className="border-b border-border">
                  {["Study", "Condition", "Phase", "Status", "Completion"].map((h) => (
                    <TableHead
                      key={h}
                      className="h-auto whitespace-normal border-b border-border px-0 pb-[7px] pr-[10px] text-left align-middle font-mono text-[9.5px] font-normal uppercase tracking-[0.11em] text-muted-foreground"
                    >
                      {h}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data.trials ?? []).map((t) => (
                  <TableRow key={t.nct_id} className="border-b border-border">
                    <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-top">
                      <a
                        href={`https://clinicaltrials.gov/study/${t.nct_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-mono text-[12px] text-primary"
                      >
                        {t.nct_id}
                      </a>
                      <span className="mt-[2px] block max-w-[46ch] font-mono text-[10px] leading-[1.5] text-muted-foreground">
                        {t.title}
                      </span>
                    </TableCell>
                    <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-top text-[13.5px]">
                      {t.conditions || "–"}
                    </TableCell>
                    <TableCell className="px-0 py-2 pr-[10px] align-top">
                      {phaseLevel(t.phase) ? (
                        <PhaseBar phase={phaseLevel(t.phase)!} label={phaseLabel(t.phase)} />
                      ) : (
                        <span className="font-mono text-[10.5px] text-muted-foreground">
                          {phaseLabel(t.phase)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-top font-mono text-[10.5px] text-ink-2">
                      {t.status?.replace(/_/g, " ").toLowerCase()}
                    </TableCell>
                    <TableCell className="px-0 py-2 align-top font-mono text-[12px] tabular-nums">
                      {t.completion_date ?? "–"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>

          {series.length > 0 && (
            <Section
              id="financials"
              title="Financial trend"
              period="10-K consolidated statements · SEC XBRL company facts · US$"
            >
              <div className="grid grid-cols-2 gap-x-[34px]">
                {series.map((s) => (
                  <Sparkline key={s!.name} series={s!} />
                ))}
              </div>
              <p className="mt-4 max-w-[70ch] font-mono text-[10px] leading-[1.6] text-muted-foreground">
                Cash here is cash and equivalents as reported, not cash plus
                investments. The two are different definitions, and the series
                shows the one the filing states.
              </p>
            </Section>
          )}
        </div>

        <aside className="space-y-6">
          <Section id="patents" title="Patent protection" period="Orange Book · Purple Book">
            <div className="border-b border-border py-[11px] last:border-b-0">
              <div className="flex flex-wrap items-baseline justify-between gap-x-[10px] gap-y-[6px] text-[13.5px]">
                <span>{data.ticker}</span>
                <span
                  className={`whitespace-nowrap px-[6px] py-[2px] font-mono text-[9.5px] uppercase tracking-[0.08em] ${STATE_STYLE[state]}`}
                >
                  {protection?.state ?? "no approved product"}
                </span>
              </div>
              <div className="mt-[5px] font-mono text-[10.5px] leading-[1.6] text-ink-2">
                {(protection?.evidence ?? []).map((line) => (
                  <p key={line} className="mb-[6px] last:mb-0">
                    {line}
                  </p>
                ))}
                {state === "approved-unlisted" && (
                  <em className="not-italic text-muted-foreground">
                    Absence in our tables is not evidence of absence in fact
                  </em>
                )}
              </div>
            </div>
          </Section>

          {data.readouts?.length > 0 && (
            <Section id="readouts" title="Upcoming readouts" period="primary completion dates">
              <RailList
                items={data.readouts.slice(0, 6).map((r) => ({
                  when: r.completion_date?.slice(0, 7) ?? "–",
                  what: r.title,
                  id: `${r.nct_id} · ${phaseLabel(r.phase)}`,
                }))}
              />
            </Section>
          )}

          <Section id="filings" title="Filings held" period="five years, per company">
            <RailList
              items={filings.map((f) => ({
                when: f.fiscal_year ? `FY${f.fiscal_year}` : f.filed,
                what: `${f.form} · filed ${f.filed}`,
                id: `${f.accession}${f.sections.length ? ` · ${f.sections.length} sections stored` : ""}`,
              }))}
            />
          </Section>
        </aside>
      </div>

      <footer className="border-t border-border px-[30px] py-4">
        <PeriodLabel className="whitespace-normal">
          Live from the BioBase corpus · figures as the filings and registry
          state them
        </PeriodLabel>
      </footer>
    </div>
  );
}

export { money };
