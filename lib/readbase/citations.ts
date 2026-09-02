/**
 * Citation markers → source records.
 *
 * The marker format and the id-normalisation fallback are adapted from the
 * approach in miurla/morphic (Apache-2.0), reimplemented here for filings and
 * stored passages rather than web search results.
 *
 * One deliberate departure. Morphic drops a marker it cannot resolve, emitting
 * an empty string. For an answer engine over web search that is a reasonable
 * swallow. Here it is the one failure the product exists to prevent: a figure
 * that quietly loses its provenance still reads as sourced. So an unresolved
 * marker resolves to an explicit `unresolved` result that the renderer is
 * obliged to show. Nothing fails silently.
 */

/** `[1](#accessorCallId)` — 1-indexed, whitespace tolerated inside the bracket. */
const MARKER = /\[\s*(\d{1,3})\s*\]\(#([^)\s]+)\)/g;

/** Providers prefix tool-call ids differently; compare on the bare id. */
const ID_PREFIXES = ["toolu_", "call_", "fc_", "tool_"];

export function normaliseCallId(id: string): string {
  const prefix = ID_PREFIXES.find((p) => id.startsWith(p));
  return prefix ? id.slice(prefix.length) : id;
}

export type CitationMarker = {
  /** The whole `[n](#id)` span, so a renderer can substitute in place. */
  raw: string;
  n: number;
  callId: string;
  start: number;
  end: number;
};

export function parseCitationMarkers(text: string): CitationMarker[] {
  const found: CitationMarker[] = [];
  for (const m of text.matchAll(MARKER)) {
    const n = Number(m[1]);
    // 1-indexed, and an answer citing past 100 sources is a bug upstream.
    if (!Number.isInteger(n) || n < 1 || n > 100) continue;
    found.push({
      raw: m[0],
      n,
      callId: m[2],
      start: m.index,
      end: m.index + m[0].length,
    });
  }
  return found;
}

/** What an accessor returned, addressable by the call that produced it. */
export type AccessorOutput = {
  callId: string;
  accessor: string;
  /** 1-indexed, matching the marker numbering the model was given. */
  records: CitedRecord[];
};

export type CitedRecord = {
  /** The document, named — never the archive it came from. */
  document: string;
  locator: string;
  /** Absent when the record exists but its text was not stored. */
  paragraphs?: string[];
};

export type ResolvedCitation =
  | { status: "resolved"; n: number; accessor: string; record: CitedRecord }
  /** The record is known but its text is not held. Say so; do not hide it. */
  | { status: "not-stored"; n: number; accessor: string; record: CitedRecord }
  /** The marker points at nothing we can name. The loudest state. */
  | { status: "unresolved"; n: number; raw: string; reason: string };

export function resolveMarker(
  marker: CitationMarker,
  outputs: AccessorOutput[],
): ResolvedCitation {
  const wanted = normaliseCallId(marker.callId);
  const output =
    outputs.find((o) => o.callId === marker.callId) ??
    outputs.find((o) => normaliseCallId(o.callId) === wanted);

  if (!output) {
    return {
      status: "unresolved",
      n: marker.n,
      raw: marker.raw,
      reason: `no accessor call matching ${marker.callId}`,
    };
  }

  const record = output.records[marker.n - 1];
  if (!record) {
    return {
      status: "unresolved",
      n: marker.n,
      raw: marker.raw,
      reason: `${output.accessor} returned ${output.records.length} records; citation asks for ${marker.n}`,
    };
  }

  return {
    status: record.paragraphs?.length ? "resolved" : "not-stored",
    n: marker.n,
    accessor: output.accessor,
    record,
  };
}

export function resolveCitations(
  text: string,
  outputs: AccessorOutput[],
): ResolvedCitation[] {
  return parseCitationMarkers(text).map((m) => resolveMarker(m, outputs));
}

/** True when every marker in the text found a record we can name. */
export function allCitationsResolve(resolved: ResolvedCitation[]): boolean {
  return resolved.every((r) => r.status !== "unresolved");
}
