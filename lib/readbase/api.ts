/**
 * This is the client for the live BioBase API, the Python service in backend/.
 * The response shapes here mirror what that service actually returns and are not
 * a hopeful contract, so where these screens and the API disagree, the API is
 * the fact. Every call goes through the Next route handlers under app/api rather
 * than straight from the browser, which is what keeps the backend URL and the
 * key server-side. Import the typed helpers, ask() and company() and the rest,
 * from a client component.
 */
import type { AnswerNode } from "@/lib/readbase/types";
import type { PassageSection } from "@/lib/readbase/passages";
import { parseCitationMarkers, resolveCitation } from "@/lib/readbase/citations";

export const API_BASE =
  process.env.BIOBASE_API_URL ?? "http://127.0.0.1:8000";

/**
 * Sent on the one endpoint that spends money. Server-side only, it lives in
 * the route handlers, never in anything shipped to the browser, which is the
 * whole point of proxying through them.
 *
 * Unset in development, where the API asks for nothing.
 */
export function apiHeaders(): Record<string, string> {
  const key = process.env.BIOBASE_API_KEY;
  // has to match require_key on the API. Both sides were renamed in one change,
  // which was free before anything was deployed and would not have been after
  return key ? { "X-BioBase-Key": key } : {};
}

/** One document behind a retrieval, as the service names it. */
export type CitedDoc = {
  kind: "filing" | "trial";
  ticker?: string | null;
  label?: string | null;
  detail?: string | null;
  url?: string | null;
  chunk_id?: number | null;
  accession?: string | null;
  nct_id?: string | null;
};

/** One numbered block the model was given, and was told to cite by number. */
export type EvidenceBlock = {
  n: number;
  tool: string;
  label: string;
  source: string;
  text: string;
  tickers: string[];
  documents: CitedDoc[];
};

export type AskResponse = {
  answer: string;
  sources?: string[];
  match_count?: number;
  tools_used?: string[] | null;
  /** Markers the model wrote against blocks that never existed. */
  dropped_citations?: number;
  retrieved?: string;
  evidence?: EvidenceBlock[];
  error?: string;
  /** Set when the answer is a refusal rather than an answer. */
  unavailable?: boolean;
  /** Present only when the refusal is about cost: the day's budget, or a burst. */
  budget?: { used?: number; limit?: number; resets?: string; throttled?: boolean };
};

export type ChunkResponse = {
  chunk_id: number;
  text: string;
  section: string;
  /** 0-indexed within the section, display position, not this. */
  ordinal: number;
  of: number;
  section_chunk_ids: number[];
  company: { ticker: string; name: string; cik: string | null };
  filing: {
    form: string;
    filed: string;
    fiscal_year: number | null;
    period_end: string | null;
    accession: string;
    document: string;
    url: string | null;
  };
  error?: string;
};

/**
 * The answer arrives as prose with `[n]` markers indexing the evidence blocks.
 * This turns it into the nodes the answer components already render, so the
 * live answer and the fixtures go through exactly the same typography.
 *
 * `blocks` is how many were actually returned. A marker past that becomes an
 * unresolved node rather than a chip, so it cannot be clicked and cannot be
 * mistaken for a citation that leads somewhere.
 */
export function toAnswerNodes(answer: string, blocks = Infinity): AnswerNode[][] {
  return answer
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, li) => {
      const nodes: AnswerNode[] = [];
      let cursor = 0;
      let chip = 0;
      for (const m of parseCitationMarkers(line)) {
        if (m.start > cursor) {
          nodes.push({ kind: "text", text: line.slice(cursor, m.start) });
        }
        const ref = resolveCitation(m.n, blocks);
        nodes.push(
          ref.status === "resolved"
            ? { kind: "chip", id: `p${li}c${chip++}`, source: m.n }
            : { kind: "unresolved", n: m.n, reason: ref.reason },
        );
        cursor = m.end;
      }
      if (cursor < line.length) nodes.push({ kind: "text", text: line.slice(cursor) });
      return nodes;
    });
}

/**
 * A fetched passage, as a section the panel can show and step through.
 *
 * Only the fetched passage carries text; its siblings are known by id and load
 * when stepped to. `ordinal` is 0-indexed in the service, so position comes
 * from the sibling list rather than from the ordinal.
 */
export function sectionFromChunk(chunk: ChunkResponse): {
  section: PassageSection;
  index: number;
} {
  // Older builds of the service return the section length but not its member
  // ids. The length is still true, so it is still shown, but the passages
  // cannot be stepped to, and the panel has to say that rather than pretend
  // the section is one passage long.
  const indexed = Boolean(chunk.section_chunk_ids?.length);
  const total = indexed ? chunk.section_chunk_ids.length : Math.max(chunk.of, 1);
  const ids = indexed ? chunk.section_chunk_ids : [];
  const position = indexed
    ? Math.max(ids.indexOf(chunk.chunk_id), 0) + 1
    : Math.min(Math.max(chunk.ordinal + 1, 1), total);
  const year = chunk.filing.fiscal_year ? `FY${chunk.filing.fiscal_year}` : null;

  const url = chunk.filing.url;
  return {
    index: position,
    section: {
      id: `chunk-section-${chunk.filing.accession}-${chunk.section}`,
      original: {
        url,
        displayUrl: url ? url.replace(/^https?:\/\/(www\.)?/, "") : "not on EDGAR",
        fields: [
          ["CIK", chunk.company.cik ?? "–"],
          ["Accession", chunk.filing.accession],
          [
            "Form",
            [chunk.filing.form, chunk.filing.period_end && `period ended ${chunk.filing.period_end}`]
              .filter(Boolean)
              .join(" · "),
          ],
          ["Document", chunk.filing.document],
        ] as [string, string][],
      },
      header: [
        chunk.company.ticker,
        chunk.filing.form,
        year,
        `filed ${chunk.filing.filed}`,
        chunk.section.replace(/_/g, " "),
      ].filter(Boolean) as string[],
      total,
      indexUnavailable: !indexed,
      passages: Array.from({ length: total }, (_, i) => ({
        index: i + 1,
        chunkId: indexed ? ids[i] : undefined,
        ...((indexed ? ids[i] === chunk.chunk_id : i + 1 === position)
          ? {
              characters: `${chunk.text.length.toLocaleString()} characters`,
              provenance: "stored verbatim · no summarisation",
              paragraphs: splitPassage(chunk.text),
            }
          : {}),
      })),
    },
  };
}

/** Stored text is one blob; paragraph breaks are the only thing added. */
export function splitPassage(text: string): string[] {
  const parts = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return parts.length ? parts : [text.trim()];
}

export async function ask(question: string): Promise<AskResponse> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  return res.json();
}

export async function fetchChunk(chunkId: number): Promise<ChunkResponse> {
  const res = await fetch(`/api/source/chunk/${chunkId}`);
  return res.json();
}
