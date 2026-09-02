import { Chrome } from "@/components/readbase/chrome";
import { Section } from "@/components/readbase/section";
import { PhaseBar } from "@/components/readbase/phase-bar";
import { Sparkline } from "@/components/readbase/sparkline";
import { CashCallout } from "@/components/readbase/cash-callout";
import { PatentStates } from "@/components/readbase/patent-state";
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
import {
  company,
  filingsHeld,
  financials,
  financialsPeriod,
  pipeline,
  pipelineAsOf,
  readouts,
} from "@/lib/readbase/moderna";

/**
 * Everything this page holds is on this page, so the tabs move to a section
 * rather than swapping a view. "Trials" has no section of its own — the trial
 * counts live in the pipeline table — so it is marked as having nowhere to go
 * instead of looking like the five that do.
 */
const TABS: { label: string; target?: string }[] = [
  { label: "Overview", target: "top" },
  { label: "Pipeline", target: "pipeline" },
  { label: "Financials", target: "financials" },
  { label: "Trials" },
  { label: "Patents", target: "patents" },
  { label: "Filings", target: "filings" },
];

/**
 * Artboard 3 as drawn, on the Moderna fixture. The live company page is at
 * /companies/[ticker]; this is kept as the canvas reference, and because its
 * programme table shows a shape the corpus cannot yet produce.
 */
export default function CompanyFixturePage() {
  return (
    <div id="top" className="min-h-full bg-card text-foreground scroll-mt-0">
      <Chrome crumb={["companies", "fixture", company.name]} />

      {/* ------------------------------------------------------------ head */}
      <div className="border-b border-border bg-secondary px-[30px] pt-6">
        <div className="flex items-baseline gap-[14px]">
          <h2 className="text-[27px] font-normal tracking-[-0.01em]">{company.name}</h2>
          <span className="bg-foreground px-[7px] py-[3px] font-mono text-[12px] tracking-[0.08em] text-card">
            {company.ticker}
          </span>
        </div>

        <div className="mt-2 font-mono text-[11px] text-ink-2">
          {[
            `CIK ${company.cik}`,
            company.location,
            company.fiscalYearEnd,
            company.filingsHeld,
            company.registeredTrials,
          ].map((item, i) => (
            <span key={item}>
              {i > 0 && <span className="px-[6px] text-muted-foreground">·</span>}
              {item}
            </span>
          ))}
        </div>

        <div className="mt-[18px] flex gap-[26px]">
          {TABS.map((tab, i) =>
            tab.target ? (
              <a
                key={tab.label}
                href={`#${tab.target}`}
                className={`border-b-2 pb-[11px] font-mono text-[11px] uppercase tracking-[0.1em] ${
                  i === 0
                    ? "border-accent-mid text-foreground"
                    : "border-transparent text-muted-foreground"
                }`}
              >
                {tab.label}
              </a>
            ) : (
              <span
                key={tab.label}
                aria-disabled="true"
                title="No separate trials view — trial counts are in the pipeline table"
                className="border-b-2 border-dashed border-line-hi pb-[11px] font-mono text-[11px] uppercase tracking-[0.1em] text-muted-foreground"
              >
                {tab.label}
              </span>
            ),
          )}
        </div>
      </div>

      {/* ------------------------------------------------------------ body */}
      <div className="grid grid-cols-[1fr_1px_356px]">
        <div className="px-[30px] pb-[34px] pt-[26px]">
          <Section id="pipeline" title="Pipeline by phase" period={pipelineAsOf}>
            <Table className="w-full caption-bottom border-collapse text-[13.5px]">
              <TableHeader>
                <TableRow className="border-b border-border">
                  {[
                    { label: "Programme", w: "w-[186px]", num: false },
                    { label: "Indication", w: "", num: false },
                    { label: "Phase", w: "w-[150px]", num: false },
                    { label: "Approved / lead trial", w: "w-[130px]", num: false },
                    { label: "Trials", w: "w-[64px]", num: true },
                  ].map((h) => (
                    <TableHead
                      key={h.label}
                      className={`h-auto whitespace-normal border-b border-border px-0 pb-[7px] pr-[10px] align-middle font-mono text-[9.5px] font-normal uppercase tracking-[0.11em] text-muted-foreground ${
                        h.num ? "pr-0 text-right" : "text-left"
                      } ${h.w}`}
                    >
                      {h.label}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {pipeline.map((p, i) => (
                  <TableRow key={p.code} className="border-b border-border">
                    <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-middle">
                      <span className="font-mono text-[12px]">{p.code}</span>
                      {p.brand && (
                        <div className="mt-[2px] font-mono text-[10px] text-muted-foreground">
                          {p.brand}
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-normal px-0 py-2 pr-[10px] align-middle text-[13.5px]">
                      {p.indication}
                    </TableCell>
                    <TableCell className="px-0 py-2 pr-[10px] align-middle">
                      <PhaseBar phase={p.phase} label={p.phaseLabel} index={i} />
                    </TableCell>
                    <TableCell className="px-0 py-2 pr-[10px] align-middle font-mono text-[12px] tabular-nums">
                      {p.lead}
                    </TableCell>
                    <TableCell className="px-0 py-2 text-right align-middle font-mono text-[12px] tabular-nums">
                      {p.trials}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Section>

          <Section id="financials" title="Financial trend" period={financialsPeriod}>
            <div className="grid grid-cols-2 gap-x-[34px]">
              {financials.map((series) => (
                <Sparkline key={series.name} series={series} />
              ))}
            </div>
            <CashCallout />
          </Section>
        </div>

        <div className="bg-border" />

        {/* ------------------------------------------------------------ rail */}
        <aside className="bg-secondary px-6 pb-[34px] pt-[26px]">
          <Section id="patents" title="Patent protection" period="Orange Book 2026-08">
            <PatentStates />
          </Section>

          <Section title="Upcoming readouts" period="primary completion dates">
            <RailList items={readouts} />
          </Section>

          <Section id="filings" title="Filings held" period="five years, per company">
            <RailList items={filingsHeld} />
          </Section>
        </aside>
      </div>

      <footer className="border-t border-border px-[30px] py-4">
        <PeriodLabel>
          Fixture data carried from design/readbase-canvas.html · identifiers are
          unverified
        </PeriodLabel>
      </footer>
    </div>
  );
}
