/**
 * This is the Moderna FY2024 against FY2025 fixture behind artboard 4, carried
 * across from design/readbase-canvas.html intact. The accession numbers and
 * extractor versions are fixtures and not verified data, so nothing here should
 * be presented as though it came from a filing. Imported by the fixture pages
 * under app/companies/fixture, which label themselves as such.
 */

export type Mark = "plus" | "minus" | "eq";

export type Snapshot = {
  role: string;
  document: string;
  detail: string;
  /** Called out on its own because it is what decides comparability. */
  extractor: string;
  ingested: string;
};

export type DiffRow = {
  mark: Mark;
  label: string;
  sub: string;
  before: string;
  after: string;
  delta: string;
  direction: "up" | "dn" | "na";
};

/** A span of the rewritten risk factor: unchanged, removed, or added. */
export type TextDiffPart = { kind: "same" | "del" | "ins"; text: string };

const later: Snapshot = {
  role: "Later snapshot",
  document: "10-K · FY2025 · filed 2026-02-20",
  detail: "accession 0001682852-26-000033",
  extractor: "v2.4.1",
  ingested: "ingested 2026-02-27",
};

/** Same later snapshot both times; only the earlier one differs. */
export const comparable = {
  earlier: {
    role: "Earlier snapshot",
    document: "10-K · FY2024 · filed 2025-02-21",
    detail: "accession 0001682852-25-000022",
    extractor: "v2.4.1",
    ingested: "ingested 2025-03-11",
  } satisfies Snapshot,
  later,
  verdict: "Comparable",
};

export const notComparable = {
  earlier: {
    role: "Earlier snapshot",
    document: "10-K · FY2024 · filed 2025-02-21",
    detail: "accession 0001682852-25-000022",
    extractor: "v2.3.0",
    ingested: "ingested 2025-02-28",
  } satisfies Snapshot,
  later,
  verdict: "Not comparable",
  noteCaption: "Why this comparison is withheld",
  note: "Segment normalisation changed in extractor v2.4.0: product revenue and grant revenue were reported as one line before that version and as two lines after it. A diff across this boundary would show a revenue split that the company never announced. The five financial rows are withheld until FY2024 is re-extracted; the pipeline and risk-factor rows are unaffected and are shown above.",
};

export const financialRows: DiffRow[] = [
  { mark: "minus", label: "Total revenue", sub: "consolidated statements of operations", before: "3,236", after: "1,900", delta: "−41.3%", direction: "dn" },
  { mark: "minus", label: "Research and development", sub: "consolidated statements of operations", before: "4,453", after: "3,612", delta: "−18.9%", direction: "dn" },
  { mark: "plus", label: "Net loss narrowed", sub: "consolidated statements of operations", before: "(3,562)", after: "(2,792)", delta: "+21.6%", direction: "up" },
  { mark: "minus", label: "Cash, equivalents and investments", sub: "balance sheet, at 31 December", before: "9,483", after: "5,920", delta: "−37.6%", direction: "dn" },
  { mark: "minus", label: "Employees", sub: "Item 1, human capital", before: "5,600", after: "4,300", delta: "−23.2%", direction: "dn" },
];

export const pipelineRows: DiffRow[] = [
  { mark: "plus", label: "mRNA-1283 mNEXSPIKE", sub: "approved 2025-05-31 · moved out of clinical stage", before: "Phase 3", after: "Approved", delta: "–", direction: "na" },
  { mark: "minus", label: "mRNA-1073 influenza + COVID", sub: "no longer listed; superseded by mRNA-1083", before: "Phase 1/2", after: "Not listed", delta: "–", direction: "na" },
  { mark: "plus", label: "mRNA-1195 Epstein–Barr virus", sub: "first appearance in an annual report", before: "–", after: "Phase 1", delta: "–", direction: "na" },
];

export const riskFactor = {
  heading: "Risk factors",
  count: "61 → 58 · 1 rewritten",
  label: "Reliance on a concentrated customer base",
  parts: [
    { kind: "same", text: "A substantial portion of our revenue has been derived from " },
    { kind: "del", text: "a small number of government purchasers" },
    { kind: "ins", text: "supply agreements with governments and international health organisations" },
    { kind: "same", text: ", and " },
    { kind: "ins", text: "the expiry of the remaining COVID-19 supply commitments in 2026 means" },
    { kind: "same", text: " we " },
    { kind: "del", text: "may not be able to" },
    { kind: "ins", text: "do not expect to" },
    { kind: "same", text: " replace that revenue on comparable terms." },
  ] satisfies TextDiffPart[],
};

export const groups = {
  financial: { heading: "Financial statements", count: "5 line items compared · US$ millions" },
  pipeline: { heading: "Pipeline and approvals", count: "3 changes" },
};

export const legend = {
  lead: "Every row links to both filings · click a figure to open the passage it came from",
  keys: ["+ increase or addition", "− decrease or removal", "≈ text rewritten"],
};

export const secondHeading = "The same comparison when the snapshots disagree";
