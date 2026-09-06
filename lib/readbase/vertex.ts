/**
 * This holds the Vertex R&D spend and the GSK refusal, the fixtures behind
 * artboard 2, carried across from design/readbase-canvas.html intact. The CIK
 * and accession numbers are plausible in format but were written from memory for
 * the canvas, so they are fixtures and not verified data. Imported by
 * app/ask/fixture and by the refusal card, which is the one place the refusal
 * copy is rendered.
 */
import type { AccessorResult, AnswerNode, SourceListing } from "@/lib/readbase/types";
import { unstoredSection, type PassageSection, type SourceLocation } from "@/lib/readbase/passages";

export const question = "How much did Vertex spend on research and development last year?";
export const answeredAt = "answered 2026-08-31 09:14 UTC";

export const accessorTrace = {
  accessors: ["financial_series", "filing_section", "trial_search"],
  result: "9 passages returned, 3 cited",
};

export const answer: AnswerNode[][] = [
  [
    { kind: "text", text: "Vertex Pharmaceuticals reported research and development expense of " },
    { kind: "figure", text: "$3.20B" },
    { kind: "text", text: " for fiscal year 2025, against " },
    { kind: "figure", text: "$3.83B" },
    { kind: "text", text: " in fiscal 2024, a decrease of " },
    { kind: "figure", text: "16.4%" },
    { kind: "text", text: "." },
    { kind: "chip", id: "1a", source: 1 },
  ],
  [
    { kind: "text", text: "Fiscal 2024 also carried a " },
    { kind: "figure", text: "$4.4B" },
    {
      kind: "text",
      text: " acquired in-process research and development charge from the Alpine Immune Sciences acquisition. Vertex reports that on its own line, so it is in neither figure above; counting it, total research spending in fiscal 2024 was ",
    },
    { kind: "figure", text: "$8.23B" },
    { kind: "text", text: " on the company’s own presentation." },
    { kind: "chip", id: "1b", source: 1 },
  ],
  [
    { kind: "text", text: "Research and development was " },
    { kind: "figure", text: "28.7%" },
    { kind: "text", text: " of total revenue of " },
    { kind: "figure", text: "$11.15B" },
    { kind: "text", text: " in fiscal 2025." },
    { kind: "chip", id: "2a", source: 2 },
    {
      kind: "text",
      text: " Vertex has 41 trials registered on ClinicalTrials.gov with a status of recruiting or active.",
    },
  ],
];

export const sources: SourceListing[] = [
  {
    n: 1,
    document: "Vertex Pharmaceuticals · 10-K · FY2025 · consolidated statements of operations",
    locator: "filed 2026-02-12 · CIK 0000875320 · accession 0000875320-26-000009 · passage 2 of 3",
  },
  {
    n: 2,
    document: "Vertex Pharmaceuticals · 10-K · FY2025 · management’s discussion and analysis",
    locator: "filed 2026-02-12 · CIK 0000875320 · accession 0000875320-26-000009 · passage 1 of 6",
  },
];

/**
 * Vertex's 10-K sections. Both citations land in the same filing, in different
 * sections; we hold neither section's text, so opening either says so.
 */
export const sections: Record<string, PassageSection> = {
  "vrtx-ops": unstoredSection(
    "vrtx-ops",
    ["VRTX", "10-K", "FY2025", "filed 2026-02-12", "consolidated statements of operations"],
    3,
  ),
  "vrtx-mdna": unstoredSection(
    "vrtx-mdna",
    ["VRTX", "10-K", "FY2025", "filed 2026-02-12", "management’s discussion and analysis"],
    6,
  ),
};

export const sourceLocation: Record<number, SourceLocation> = {
  1: { sectionId: "vrtx-ops", index: 2 },
  2: { sectionId: "vrtx-mdna", index: 1 },
};

/** The filing both sources were cut from. Fixture identifiers, unverified. */
export const filingUrl =
  "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000875320&type=10-K";

/**
 * The refusal. Not an error and not an empty state, it is an answer of a
 * different kind, and it is traceable in exactly the same way: it shows which
 * accessors ran, what each returned, and what the system can do instead.
 */
export const refusal = {
  heading: "No data for this",
  statement: "I don’t have data on how GSK’s pipeline has changed since 2021.",
  queriedCaption: "What was queried",
  queried: [
    { accessor: "filing_section", returned: "GSK plc · 20-F · FY2021, not in corpus", rows: "0 rows" },
    { accessor: "filing_diff", returned: "needs two annual reports; earliest held is FY2023", rows: "0 rows" },
    { accessor: "trial_search", returned: "sponsor GSK, 604 trials, no phase history before 2023-11", rows: "604 rows" },
  ] satisfies AccessorResult[],
  remedy:
    "Annual reports go back five years per company, so FY2021 is outside the window for every issuer. Trial records reach further back but only hold current status, not the date a programme changed phase, so a pipeline comparison against 2021 isn’t something I can support from these sources. I can compare GSK’s FY2023 and FY2025 filings, or list the 604 registered trials by current phase.",
};
