/**
 * This is the Moderna fixture behind artboard 3, every figure carried across
 * from design/readbase-canvas.html intact. The identifiers, meaning the CIK, the
 * NCT numbers and the accession numbers, are plausible in format but were
 * written from memory for the canvas and are not verified against the source
 * systems, so treat them as fixtures and never present them as verified.
 * Imported by the fixture company page, which says so on the page itself.
 */

export type PhaseLevel = 1 | 2 | 3 | 4;

export const company = {
  name: "Moderna, Inc.",
  ticker: "MRNA",
  cik: "0001682852",
  location: "Cambridge, MA",
  fiscalYearEnd: "fiscal year ends 31 December",
  filingsHeld: "5 annual reports held, FY2021–FY2025",
  registeredTrials: "312 registered trials",
} as const;

export const corpus = "787 companies · 3,614 annual reports · 30,823 trials";

/* ---------------------------------------------------------------- pipeline */

export type Programme = {
  code: string;
  brand?: string;
  indication: string;
  /** Ordinal position on the phase ramp. Approved sits at the top of it. */
  phase: PhaseLevel;
  phaseLabel: string;
  /** Approval date for approved products, lead NCT number otherwise. */
  lead: string;
  trials: number;
};

export const pipelineAsOf = "status as of 2026-08-24 · ClinicalTrials.gov + FDA approvals";

export const pipeline: Programme[] = [
  { code: "mRNA-1273", brand: "Spikevax", indication: "COVID-19, all ages", phase: 4, phaseLabel: "Approved", lead: "2020-12-18", trials: 182 },
  { code: "mRNA-1283", brand: "mNEXSPIKE", indication: "COVID-19, 12+ and at-risk", phase: 4, phaseLabel: "Approved", lead: "2025-05-31", trials: 14 },
  { code: "mRNA-1345", brand: "mRESVIA", indication: "RSV, adults 60+", phase: 4, phaseLabel: "Approved", lead: "2024-05-31", trials: 11 },
  { code: "mRNA-4157", brand: "intismeran autogene", indication: "Melanoma, adjuvant · with Merck", phase: 3, phaseLabel: "Phase 3", lead: "NCT05933577", trials: 9 },
  { code: "mRNA-1010", indication: "Seasonal influenza", phase: 3, phaseLabel: "Phase 3", lead: "NCT05827068", trials: 12 },
  { code: "mRNA-1083", indication: "Influenza + COVID-19 combination", phase: 3, phaseLabel: "Phase 3", lead: "NCT06694389", trials: 4 },
  { code: "mRNA-1647", indication: "Cytomegalovirus", phase: 3, phaseLabel: "Phase 3", lead: "NCT05085366", trials: 7 },
  { code: "mRNA-1468", indication: "Varicella zoster", phase: 2, phaseLabel: "Phase 1/2", lead: "NCT05934851", trials: 3 },
  { code: "mRNA-3927", indication: "Propionic acidemia", phase: 2, phaseLabel: "Phase 1/2", lead: "NCT05130437", trials: 2 },
  { code: "mRNA-1195", indication: "Epstein–Barr virus", phase: 1, phaseLabel: "Phase 1", lead: "NCT05831111", trials: 1 },
];

/* --------------------------------------------------------------- financial */

export type Series = {
  name: string;
  unit: string;
  /** Fiscal years in US$ billions, oldest first. */
  values: number[];
  /** The years themselves. Live series carry their own; not every issuer
   *  reports ten. Falls back to the fixture window when absent. */
  years?: number[];
  /** Endpoints stated at their own precision, as the filings report them. */
  first: string;
  last: string;
  /** Index into `values` of the peak year, and its label. */
  peakIndex: number;
  peakLabel: string;
  /** Series that cross zero get a zero rule drawn behind them. */
  zeroRule?: boolean;
};

export const fiscalYears = [2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025];

export const financialsPeriod = "FY2016–FY2025 · 10-K consolidated statements · US$";

export const financials: Series[] = [
  {
    name: "Total revenue",
    unit: "US$B",
    values: [0.1, 0.2, 0.1, 0.1, 0.8, 18.5, 19.3, 6.8, 3.2, 1.9],
    first: "FY2016 $108M",
    last: "FY2025 $1.9B",
    peakIndex: 6,
    peakLabel: "peak FY2022",
  },
  {
    name: "Research and development",
    unit: "US$B",
    values: [0.4, 0.5, 0.5, 0.5, 1.4, 2.0, 3.3, 4.8, 4.5, 3.6],
    first: "FY2016 $386M",
    last: "FY2025 $3.61B",
    peakIndex: 7,
    peakLabel: "peak FY2023",
  },
  {
    name: "Net income / (loss)",
    unit: "US$B",
    values: [-0.2, -0.3, -0.4, -0.5, -0.7, 12.2, 8.4, -4.7, -3.6, -2.8],
    first: "FY2016 ($216M)",
    last: "FY2025 ($2.79B)",
    peakIndex: 5,
    peakLabel: "peak FY2021",
    zeroRule: true,
  },
  {
    name: "Cash and investments, at year end",
    unit: "US$B",
    values: [1.2, 1.6, 1.7, 1.3, 5.2, 17.6, 18.2, 13.3, 9.5, 5.9],
    first: "FY2016 $1.25B",
    last: "FY2025 $5.92B",
    peakIndex: 6,
    peakLabel: "peak FY2022",
  },
];

/**
 * The headline cash figure is NOT a point on the series above: different period
 * (quarter end, not fiscal year end) and different definition (cash and
 * equivalents, not cash and investments). The design has to show that.
 */
export const cashCallout = {
  label: "Cash and cash equivalents",
  figure: "$1.723B",
  caveat:
    "Not a point on the series above. This is the quarter end, 2026-06-30, and it counts cash only. The annual line includes investments. Do not read it as FY2026.",
  source: ["10-Q · Q2 2026", "filed 2026-08-07", "accession 0001682852-26-000073"],
};

/* ------------------------------------------------------------------- rail */

/** Three states, visually distinct in kind — filled, outlined, dashed. */
export type ProtectionState = "protected" | "approved-unlisted" | "no-product";

export const patentStates: {
  product: string;
  state: ProtectionState;
  stateLabel: string;
  detail: string;
  note?: string;
}[] = [
  {
    product: "Spikevax",
    state: "protected",
    stateLabel: "Protected",
    detail: "Purple Book reference product exclusivity to 2032-12-18",
    note: "7 patent families asserted in filing text; biologics are not Orange Book listed",
  },
  {
    product: "mRESVIA",
    state: "approved-unlisted",
    stateLabel: "Approved, no listed protection",
    detail: "Approved 2024-05-31 · no exclusivity record found",
    note: "Absence in our tables is not evidence of absence in fact",
  },
  {
    product: "mRNA-1010",
    state: "no-product",
    stateLabel: "No approved product",
    detail: "Phase 3 · protection not assessable until approval",
  },
];

export const readouts = [
  { when: "2026-11", what: "mRNA-4157 adjuvant melanoma, primary completion", id: "NCT05933577 · INTerpath-001" },
  { when: "2026-12", what: "mRNA-1010 seasonal influenza, efficacy readout", id: "NCT05827068 · P304" },
  { when: "2027-04", what: "mRNA-1647 cytomegalovirus, topline", id: "NCT05085366 · CMVictory" },
  { when: "2027-06", what: "mRNA-1083 combination vaccine, immunogenicity", id: "NCT06694389" },
];

export const filingsHeld = [
  { when: "FY2025", what: "10-K · filed 2026-02-20", id: "0001682852-26-000011 · 41 sections stored" },
  { when: "FY2024", what: "10-K · filed 2025-02-21", id: "0001682852-25-000016 · 40 sections stored" },
  { when: "FY2023", what: "10-K · filed 2024-02-23", id: "0001682852-24-000021 · 40 sections stored" },
  { when: "FY2022", what: "10-K · filed 2023-02-24", id: "0001682852-23-000017 · 38 sections stored" },
  { when: "FY2021", what: "10-K · filed 2022-02-25", id: "0001682852-22-000010 · 38 sections stored" },
];
