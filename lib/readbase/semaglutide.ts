/**
 * Novo Nordisk / semaglutide — the fixture behind artboard 1.
 *
 * Carried across from design/readbase-canvas.html intact. The CIK, accession
 * number and Orange Book application number are plausible in format but were
 * written from memory for the canvas, and the 20-F passage text is written
 * in-register — it is NOT the actual filing. Fixtures, not verified data.
 */

import type { AnswerNode, Source } from "@/lib/readbase/types";
import {
  unstoredSection,
  type PassageSection,
  type SourceLocation,
} from "@/lib/readbase/passages";

export const question = "When does patent protection on semaglutide expire, and what is being challenged?";
export const answeredAt = "answered 2026-08-31 14:22 UTC";

/** Which typed accessors ran, and how much of what they returned was used. */
export const accessorTrace = {
  accessors: ["filing_section", "patent_exclusivity"],
  result: "6 passages returned, 4 cited",
};

/* ------------------------------------------------------------------ answer */

export const answer: AnswerNode[][] = [
  [
    {
      kind: "cited",
      text: "Composition-of-matter protection for semaglutide expires in the United States in 2031, subject to the pediatric exclusivity Novo Nordisk obtained in 2024, and in the principal European markets in 2031.",
    },
    { kind: "chip", id: "1a", source: 1 },
    {
      kind: "text",
      text: " Novo Nordisk holds further patents on formulations, dosing regimens, manufacturing processes and oral delivery, which run past those dates, though the filing is explicit that it cannot say whether those patents would survive a validity challenge or reach a competitor’s product.",
    },
    { kind: "chip", id: "1b", source: 1 },
  ],
  [
    {
      kind: "text",
      text: "Three challenges are disclosed as pending: inter partes review petitions at the USPTO and oppositions at the EPO, both directed at patents covering semaglutide.",
    },
    { kind: "chip", id: "2a", source: 2 },
    {
      kind: "text",
      text: " The company states that an adverse outcome could allow generic or biosimilar entry earlier than it currently expects.",
    },
    { kind: "chip", id: "2b", source: 2 },
  ],
  [
    {
      kind: "text",
      text: "Separately from the patents, semaglutide products carry regulatory exclusivity that runs on its own clock — twelve years of reference product exclusivity in the United States for biologics, and eight years of data exclusivity plus two years of market protection in the European Union.",
    },
    { kind: "chip", id: "3a", source: 3 },
  ],
  [
    {
      kind: "text",
      text: "The Orange Book listing for Ozempic records 14 unexpired patents as of the most recent monthly file, the latest of which expires 2033-03-20.",
    },
    { kind: "chip", id: "4a", source: 4 },
    {
      kind: "text",
      text: " That table is a different source from the filing text above and the two do not agree on scope: the filing describes families, the Orange Book lists individual patents against one approved product.",
    },
  ],
];

/* ------------------------------------------------------------------ sources */

export const sources: Source[] = [
  { n: 1, document: "NONOF · 20-F · FY2025", locator: "intellectual property · passage 1 of 4" },
  { n: 2, document: "NONOF · 20-F · FY2025", locator: "legal proceedings · passage 3 of 5" },
  { n: 3, document: "NONOF · 20-F · FY2025", locator: "intellectual property · passage 4 of 4" },
  { n: 4, document: "FDA Orange Book", locator: "monthly file 2026-08-01 · appl. N209637" },
];

/**
 * How much of the answer a source carries, counted from the chips that cite
 * it rather than stored alongside them. The canvas's own figures are exactly
 * these counts, and deriving them removes a field that could disagree with
 * the prose — and that previously held the literal string "open", which
 * collided with the now-dynamic open state.
 */
export function extentFor(source: number): string {
  const n = answer.flat().filter((node) => node.kind === "chip" && node.source === source).length;
  return `${n} sentence${n === 1 ? "" : "s"}`;
}

/* ------------------------------------------------------------------ passage */

/** What we read — the only text the model was allowed to see. */
export const passage = {
  header: ["NONOF", "20-F", "FY2025", "filed 2026-02-04", "intellectual property", "passage 1 of 4"],
  index: 1,
  total: 4,
  totalNote: "4 passages stored for this section",
  characters: "2,992 characters",
  provenance: "stored verbatim · no summarisation",
  checksum: "sha256 4f1c9a…e0b7",
  paragraphs: [
    "Our commercial success depends in part on our ability to obtain and maintain patent and other intellectual property protection for our products and product candidates, their formulations, methods of manufacture and methods of use, as well as our ability to operate without infringing the proprietary rights of others. We seek patent protection in the United States, Europe, Japan, China and other jurisdictions we consider commercially significant. As of 31 December 2025, our patent portfolio comprised roughly 1,100 active patent families, of which the families covering semaglutide, insulin icodec and our oral peptide delivery technology are the most material to our results of operations.",
    "Composition-of-matter protection for semaglutide expires in the United States in 2031, subject to the pediatric exclusivity we obtained in 2024, and in the principal European markets in 2031. We hold additional patents directed to formulations, dosing regimens, manufacturing processes and delivery technologies that extend beyond those dates, but there can be no assurance that such patents would be held valid or infringed if asserted, or that they would prevent a competitor from marketing a product that does not fall within their claims.",
    "We are party to proceedings in which third parties have challenged the validity of patents covering semaglutide, including inter partes review petitions before the United States Patent and Trademark Office and oppositions before the European Patent Office. An adverse outcome in one or more of these proceedings could permit generic or biosimilar entry earlier than we currently anticipate and would be expected to reduce sales of the affected product materially. We also rely on trade secrets and know-how, particularly in respect of our manufacturing processes, which we protect through confidentiality agreements and internal controls; such protection may be inadequate if the relevant information is independently developed or improperly disclosed.",
    "Patent terms are limited and patent term extensions may be unavailable or shorter than we seek. Changes in patent law or its interpretation in the jurisdictions in which we operate could diminish the value of our portfolio.",
    "In addition to patents, we rely on regulatory exclusivities that operate independently of our patent rights. In the United States, our biological products are eligible for twelve years of reference product exclusivity from the date of first licensure, and our small molecule and peptide products for periods of new chemical entity or new clinical investigation exclusivity under the Federal Food, Drug, and Cosmetic Act. In the European Union, our products are generally eligible for eight years of data exclusivity followed by two years of market protection, with the possibility of a further year for a new therapeutic indication demonstrating significant clinical benefit. These exclusivities do not prevent a competitor from developing a competing product independently.",
  ],
};

/**
 * The sections this answer read into. Only the first passage of the
 * intellectual-property section has stored text; the rest are real records
 * whose text we do not hold, which the panel states rather than hides.
 *
 * Sources 1 and 3 both land in `nonof-ip` — passages 1 and 4 of the same four
 * — so stepping from one reaches the other.
 */
export const sections: Record<string, PassageSection> = {
  "nonof-ip": {
    id: "nonof-ip",
    header: ["NONOF", "20-F", "FY2025", "filed 2026-02-04", "intellectual property"],
    total: 4,
    passages: [
      {
        index: 1,
        characters: passage.characters,
        provenance: passage.provenance,
        checksum: passage.checksum,
        paragraphs: passage.paragraphs,
      },
      { index: 2 },
      { index: 3 },
      { index: 4 },
    ],
  },
  "nonof-legal": unstoredSection(
    "nonof-legal",
    ["NONOF", "20-F", "FY2025", "filed 2026-02-04", "legal proceedings"],
    5,
  ),
  "orange-book": unstoredSection(
    "orange-book",
    ["FDA Orange Book", "monthly file 2026-08-01", "appl. N209637"],
    1,
    true,
  ),
};

export const sourceLocation: Record<number, SourceLocation> = {
  1: { sectionId: "nonof-ip", index: 1 },
  2: { sectionId: "nonof-legal", index: 3 },
  3: { sectionId: "nonof-ip", index: 4 },
  4: { sectionId: "orange-book", index: 1 },
};

/* ---------------------------------------------------------- the original */

/** Deliberately a separate record from `passage`. They are not the same thing. */
export const original = {
  caption: "The original document",
  url: "sec.gov/Archives/edgar/data/353278/000117184326001204/nonof-20f_2025.htm",
  href: "https://www.sec.gov/Archives/edgar/data/353278/000117184326001204/nonof-20f_2025.htm",
  fields: [
    ["CIK", "0000353278"],
    ["Accession", "0001171843-26-001204"],
    ["Form", "20-F · fiscal year ended 2025-12-31"],
    ["Retrieved", "2026-02-06 · 1,184 pages"],
  ] as const,
  action: "Open filing on sec.gov ↗",
  distinction:
    "These are not the same thing. The panel above is the only text the model could see. The filing is the complete document it was cut from — go there to check that the cut was fair.",
};

export type { AnswerNode, Source } from "@/lib/readbase/types";
