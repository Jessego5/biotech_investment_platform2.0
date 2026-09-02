import { Chrome } from "@/components/readbase/chrome";
import { Section } from "@/components/readbase/section";
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
      <div className="min-h-svh bg-card text-foreground">
        <Chrome crumb={["companies", ticker.toUpperCase()]} />
        <div className="px-[30px] py-[26px]">
          <div className="max-w-[62ch] border border-border border-l-[3px] border-l-primary bg-secondary px-7 pb-[26px] pt-6">
            <h4 className="mb-3 font-mono text-[10px] font-normal uppercase tracking-[0.14em] text-accent-deep">
              Nothing held for this ticker
            </h4>
            <p className="text-[19px] leading-[1.6]">
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

  const protection = data.protection;
  const state = protectionState(protection?.state);
  const products = data.approved_products ?? [];
  const filings = data.filings ?? [];
  // the registry spells the same bucket more than one way — "N/A" and "NA" are
  // one absence, not two — so they are merged on the label they display under
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

  return (
    <div id="top" className="min-h-svh bg-card text-foreground">
      <Chrome crumb={["companies", data.name]} />

      <div className="border-b border-border bg-secondary px-[30px] pt-6">
        <div className="flex items-baseline gap-[14px]">
          <h2 className="text-[27px] font-normal tracking-[-0.01em]">{data.name}</h2>
          <span className="bg-foreground px-[7px] py-[3px] font-mono text-[12px] tracking-[0.08em] text-card">
            {data.ticker}
          </span>
        </div>
        <div className="mt-2 pb-[18px] font-mono text-[11px] text-ink-2">
          {[
            data.cik ? `CIK ${data.cik}` : null,
            `${filings.length} annual report${filings.length === 1 ? "" : "s"} held`,
            `${data.pipeline?.total_trials ?? 0} registered trials`,
            `${products.length} approved product${products.length === 1 ? "" : "s"}`,
          ]
            .filter(Boolean)
            .map((item, i) => (
              <span key={item as string}>
                {i > 0 && <span className="px-[6px] text-muted-foreground">·</span>}
                {item}
              </span>
            ))}
        </div>
      </div>

      <div className="grid grid-cols-[1fr_1px_356px]">
        <div className="px-[30px] pb-[34px] pt-[26px]">
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
              <Table className="w-full caption-bottom border-collapse text-[13.5px]">
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
                        {p.approval_date ?? "—"}
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
            id="trials"
            title="Registered trials"
            period={`${data.pipeline?.total_trials ?? 0} studies · ClinicalTrials.gov · 20 most recent shown`}
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

            <Table className="w-full caption-bottom border-collapse text-[13.5px]">
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
                      {t.conditions || "—"}
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
                      {t.completion_date ?? "—"}
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
                investments — the two are different definitions and the series
                shows the one the filing states.
              </p>
            </Section>
          )}
        </div>

        <div className="bg-border" />

        <aside className="bg-secondary px-6 pb-[34px] pt-[26px]">
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
                  when: r.completion_date?.slice(0, 7) ?? "—",
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
        <PeriodLabel>
          Live from the Readbase corpus · figures as the filings and registry
          state them
        </PeriodLabel>
      </footer>
    </div>
  );
}

export { money };
