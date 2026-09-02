/** Shared shapes across the answer screens. */

export type AnswerNode =
  | { kind: "text"; text: string }
  /** The sentence a citation directly supports. Gets the highlight rule. */
  | { kind: "cited"; text: string }
  /** A figure. Mono and tabular inside serif prose, so numbers stay countable. */
  | { kind: "figure"; text: string }
  /** `id` is per-chip, not per-source: the same source can be cited twice and
   *  only the chip actually clicked is the open one. */
  | { kind: "chip"; id: string; source: number }
  /** A marker pointing at a block that was never returned. Shown, not hidden:
   *  a figure that looks sourced and is not is the one thing that must never
   *  pass silently. */
  | { kind: "unresolved"; n: number; reason: string };

/** A source in the compact index under an answer (artboard 1). */
export type Source = {
  n: number;
  /** The document, named. Not the archive it came from. */
  document: string;
  locator: string;
};

/** A source in the full list with per-source actions (artboard 2). */
export type SourceListing = {
  n: number;
  document: string;
  locator: string;
};

/** One accessor that ran, what it found, and how many rows came back. */
export type AccessorResult = {
  accessor: string;
  returned: string;
  rows: string;
};
