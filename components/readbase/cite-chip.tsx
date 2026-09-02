"use client";

import { useOptionalInspector } from "@/components/readbase/inspector-provider";

/**
 * A citation chip. It is an identifier, not a badge — it names a position in
 * the source index, and where there is a panel to open, opening it opens the
 * passage the figure came from. The warm colour is reserved for provenance and
 * is defined once, in globals.css, as .cite-chip.
 *
 * Without an inspector in the tree there is nothing to open, so the chip
 * renders as a plain marker rather than a control that does nothing.
 */
export function CiteChip({ id, source }: { id: string; source: number }) {
  const inspector = useOptionalInspector();

  if (!inspector) {
    return (
      <span className="cite-chip cursor-default" aria-label={`Source ${source}`}>
        {source}
      </span>
    );
  }

  const isOpen = inspector.open?.chipId === id;
  return (
    <button
      type="button"
      className="cite-chip"
      data-state={isOpen ? "open" : undefined}
      aria-label={`Open source ${source}`}
      aria-pressed={isOpen}
      onClick={(e) => inspector.openCitation(id, source, e.currentTarget)}
      onMouseEnter={() => inspector.setHovered(source)}
      onMouseLeave={() => inspector.setHovered(null)}
      onFocus={() => inspector.setHovered(source)}
      onBlur={() => inspector.setHovered(null)}
    >
      {source}
    </button>
  );
}
