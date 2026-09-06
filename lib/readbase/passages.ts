/**
 * This models passages as belonging to a section of a document rather than to a
 * citation. Two citations can land in the same section at different passages,
 * sources 1 and 3 of the semaglutide answer both being "intellectual property"
 * at passages 1 and 4 of four, and modelling it this way is what lets the
 * stepper actually step, since it moves through the section the citation opened
 * into. Imported by the passage panel and the fixture answer screens.
 */

export type StoredPassage = {
  /** 1-indexed position within the section. */
  index: number;
  /** Where to fetch this passage from, when its text is not loaded yet. */
  chunkId?: number;
  characters?: string;
  provenance?: string;
  checksum?: string;
  /** Absent when the passage is a real record whose text we do not hold. */
  paragraphs?: string[];
};

/** The document a section was cut from — the second of the two checks. */
export type OriginalRecord = {
  url: string | null;
  displayUrl: string;
  fields: [string, string][];
};

export type PassageSection = {
  id: string;
  /** Present for live sections; the fixtures carry their own block. */
  original?: OriginalRecord;
  /** Document identity. The passage locator is derived, not stored. */
  header: string[];
  total: number;
  /** A table rather than prose: no passage sequence to step through. */
  tabular?: boolean;
  /** The section's length is known but its members are not addressable, so
   *  only the cited passage can be produced. */
  indexUnavailable?: boolean;
  passages: StoredPassage[];
};

/** Where a numbered source sits: which section, and which passage of it. */
export type SourceLocation = { sectionId: string; index: number };

export const NOT_STORED =
  "We hold the record for this passage but not its text. Nothing is shown here rather than an approximation of it.";

/**
 * A passage we can produce on demand: its text is already loaded, or we hold
 * the id that fetches it. Not yet fetched is a different claim from not held,
 * and only the second belongs in the count below.
 */
export function isHeld(passage: StoredPassage | undefined): boolean {
  return Boolean(passage?.paragraphs?.length || passage?.chunkId);
}

/**
 * The canvas reads "4 passages stored for this section". That is only true
 * when we hold every one of them, so the count is stated rather than assumed —
 * the same sentence appears verbatim when it is accurate.
 */
function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function passageNote(section: PassageSection): string {
  if (section.tabular) return "a table, not a passage of prose";
  const held = section.passages.filter(isHeld).length;
  if (section.indexUnavailable) {
    // we know how long the section is and can only produce the cited passage.
    // Saying "1 of 1" here would be a plain untruth about the document.
    return `${plural(section.total, "passage")} in this section · only the cited one is addressable`;
  }
  return held === section.total
    ? `${plural(section.total, "passage")} stored for this section`
    : `${held} of ${plural(section.total, "passage")} stored for this section`;
}

export function headerFor(section: PassageSection, index: number): string[] {
  return section.tabular
    ? section.header
    : [...section.header, `passage ${index} of ${section.total}`];
}

/** Builds a section whose records are known but whose text is not held. */
export function unstoredSection(
  id: string,
  header: string[],
  total: number,
  tabular = false,
): PassageSection {
  return {
    id,
    header,
    total,
    tabular,
    passages: Array.from({ length: total }, (_, i) => ({ index: i + 1 })),
  };
}
