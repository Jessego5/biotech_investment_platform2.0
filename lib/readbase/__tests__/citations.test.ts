import { describe, expect, it } from "vitest";
import { parseCitationMarkers, resolveCitation, unresolvedCitations } from "../citations";
import { toAnswerNodes, splitPassage, sectionFromChunk } from "../api";
import { phaseLevel, phaseLabel, protectionState, money, toSeries } from "../company";
import { passageNote, isHeld, headerFor } from "../passages";

describe("citation markers", () => {
  it("reads the format the service actually writes", () => {
    expect(parseCitationMarkers("R&D was $3.91B [1] and cash [2].").map((m) => m.n))
      .toEqual([1, 2]);
  });

  it("does not read morphic's format as ours", () => {
    // [n](#id) would have been two markers under the old parser
    expect(parseCitationMarkers("cited [1](#toolu_abc)").map((m) => m.n)).toEqual([1]);
  });

  it("marks a citation past the blocks returned as unresolved, with the counts", () => {
    const ref = resolveCitation(4, 2);
    expect(ref.status).toBe("unresolved");
    expect(ref.status === "unresolved" && ref.reason).toContain("cites block 4");
    expect(ref.status === "unresolved" && ref.reason).toContain("2 were returned");
  });

  it("resolves a citation inside the range", () => {
    expect(resolveCitation(2, 2).status).toBe("resolved");
  });

  it("never silently drops an unresolvable marker", () => {
    const bad = unresolvedCitations("A [1] and B [9].", 1);
    expect(bad).toHaveLength(1);
    expect(bad[0].n).toBe(9);
  });
});

describe("answer rendering", () => {
  it("renders an out-of-range citation as unresolved rather than a chip", () => {
    const nodes = toAnswerNodes("Spend was $1B [3].", 1).flat();
    expect(nodes.find((n) => n.kind === "chip")).toBeUndefined();
    expect(nodes.find((n) => n.kind === "unresolved")).toBeTruthy();
  });

  it("keeps the prose either side of a marker", () => {
    const nodes = toAnswerNodes("before [1] after", 1).flat();
    expect(nodes.filter((n) => n.kind === "text").map((n) => (n as { text: string }).text))
      .toEqual(["before ", " after"]);
  });

  it("gives each chip its own id so one source cited twice opens separately", () => {
    const ids = toAnswerNodes("a [1] b [1]", 1)
      .flat()
      .filter((n) => n.kind === "chip")
      .map((n) => (n as { id: string }).id);
    expect(new Set(ids).size).toBe(2);
  });
});

describe("passages", () => {
  const section = (passages: { index: number; chunkId?: number; paragraphs?: string[] }[]) => ({
    id: "s", header: ["X"], total: passages.length, passages,
  });

  it("counts a fetchable passage as held, because it can be produced", () => {
    expect(isHeld({ index: 1, chunkId: 7 })).toBe(true);
  });

  it("does not count a passage we have no way to get", () => {
    expect(isHeld({ index: 1 })).toBe(false);
  });

  it("uses the canvas wording only when every passage is held", () => {
    expect(passageNote(section([{ index: 1, chunkId: 1 }, { index: 2, chunkId: 2 }])))
      .toBe("2 passages stored for this section");
  });

  it("states the shortfall rather than implying the section is complete", () => {
    expect(passageNote(section([{ index: 1, chunkId: 1 }, { index: 2 }])))
      .toBe("1 of 2 passages stored for this section");
  });

  it("refuses to claim a length it cannot address", () => {
    expect(passageNote({ ...section([{ index: 1, chunkId: 1 }]), total: 27, indexUnavailable: true }))
      .toContain("only the cited one is addressable");
  });

  it("derives the passage locator rather than storing it", () => {
    expect(headerFor(section([{ index: 1 }, { index: 2 }]), 2)).toContain("passage 2 of 2");
  });
});

describe("live chunks", () => {
  const chunk = (over: Record<string, unknown> = {}) => ({
    chunk_id: 5, text: "a\n\nb", section: "risk_factors", ordinal: 1, of: 3,
    section_chunk_ids: [4, 5, 6],
    company: { ticker: "VRTX", name: "V", cik: "1" },
    filing: { form: "10-K", filed: "2026-02-13", fiscal_year: 2025, period_end: "2025-12-31",
              accession: "a", document: "d.htm", url: "https://sec.gov/d.htm" },
    ...over,
  });

  it("positions by the sibling list, not the zero-indexed ordinal", () => {
    expect(sectionFromChunk(chunk()).index).toBe(2);
  });

  it("falls back to the stated length when the ids are missing", () => {
    const { section } = sectionFromChunk(chunk({ section_chunk_ids: [] }));
    expect(section.total).toBe(3);
    expect(section.indexUnavailable).toBe(true);
  });

  it("splits stored text on blank lines only", () => {
    expect(splitPassage("one\n\ntwo")).toEqual(["one", "two"]);
    expect(splitPassage("no breaks here")).toHaveLength(1);
  });
});

describe("company mappings", () => {
  it("takes the furthest phase from a combined string", () => {
    expect(phaseLevel("PHASE2, PHASE3")).toBe(3);
    expect(phaseLabel("PHASE2, PHASE3")).toBe("Phase 2/3");
  });

  it("has no phase for an unstated one", () => {
    expect(phaseLevel("NA")).toBeNull();
    expect(phaseLabel("N/A")).toBe("Not stated");
  });

  it("maps the three protection states the backend returns", () => {
    expect(protectionState("protected")).toBe("protected");
    expect(protectionState("approved, no listed protection")).toBe("approved-unlisted");
    expect(protectionState("no approved product")).toBe("no-product");
  });

  it("scales money to the figure rather than a fixed unit", () => {
    expect(money(3_909_500_000)).toBe("$3.91B");
    expect(money(-112_000_000)).toBe("-$112M");
  });

  it("orders a series oldest first and names the peak year", () => {
    const s = toSeries("Revenue", [
      { value: 2e9, fiscal_year: 2025, fiscal_period: "FY", period_end: "2025-12-31" },
      { value: 5e9, fiscal_year: 2024, fiscal_period: "FY", period_end: "2024-12-31" },
      { value: 1e9, fiscal_year: 2023, fiscal_period: "FY", period_end: "2023-12-31" },
    ])!;
    expect(s.years).toEqual([2023, 2024, 2025]);
    expect(s.peakLabel).toBe("peak FY2024");
    expect(s.first).toBe("FY2023 $1.00B");
  });

  it("has no series when a company reports nothing", () => {
    expect(toSeries("Revenue", [])).toBeNull();
  });
});
