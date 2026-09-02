/**
 * Citation markers → the evidence block they point at.
 *
 * The service writes `[n]`, one-indexed into the numbered blocks the model was
 * given (see chat.py `_CITATION`). An earlier version of this file parsed
 * `[n](#toolCallId)`, which is morphic's format and not one anything here
 * emits; it is the real format now.
 *
 * The service already removes markers pointing at blocks that were never
 * returned, and reports how many it removed. This is the second line: if one
 * reaches the page anyway — an older service, a stripping bug — it renders as
 * visibly unresolved rather than as a chip that opens nothing. A number that
 * looks sourced and is not is the failure this product exists to prevent, so
 * it is never rendered as though it were fine.
 */

/** Matches the service's own pattern, minus the leading-space capture. */
const MARKER = /\[(\d{1,3})\]/g;

export type CitationRef =
  | { status: "resolved"; n: number }
  | { status: "unresolved"; n: number; reason: string };

export function resolveCitation(n: number, blocks: number): CitationRef {
  if (!Number.isInteger(n) || n < 1) {
    return { status: "unresolved", n, reason: `${n} is not a block number` };
  }
  if (n > blocks) {
    return {
      status: "unresolved",
      n,
      reason: `cites block ${n}, and ${blocks} ${blocks === 1 ? "was" : "were"} returned`,
    };
  }
  return { status: "resolved", n };
}

export type ParsedMarker = { n: number; start: number; end: number };

export function parseCitationMarkers(text: string): ParsedMarker[] {
  const found: ParsedMarker[] = [];
  for (const m of text.matchAll(MARKER)) {
    const at = m.index ?? 0;
    found.push({ n: Number(m[1]), start: at, end: at + m[0].length });
  }
  return found;
}

/** Every marker in an answer that points at nothing. Empty is the happy case. */
export function unresolvedCitations(
  text: string,
  blocks: number,
): Extract<CitationRef, { status: "unresolved" }>[] {
  return parseCitationMarkers(text)
    .map((m) => resolveCitation(m.n, blocks))
    .filter((r): r is Extract<CitationRef, { status: "unresolved" }> =>
      r.status === "unresolved");
}
