"use client";

/**
 * This is the passage panel, the first of the two checks: the exact stored text
 * the model was allowed to read, headed by the document it came from and marked
 * one of four so nobody mistakes one passage for the whole section. It scrolls
 * internally under a pinned footer, and the passage being cut off at the fold is
 * correct, since it stops anyone reading the excerpt as the whole document. It
 * renders nothing when the inspector has nothing open.
 */

import { ScrollArea } from "@/components/ui/scroll-area";
import { useInspector } from "@/components/readbase/inspector-provider";
import {
  headerFor,
  isHeld,
  passageNote,
  NOT_STORED,
  type PassageSection,
} from "@/lib/readbase/passages";

function Stepper({
  section,
  index,
  onSelect,
}: {
  section: PassageSection;
  index: number;
  onSelect: (n: number) => void;
}) {
  const step = (n: number) => onSelect(Math.min(Math.max(n, 1), section.total));

  // Wraps rather than squeezes. The canvas draws a section of four, where the
  // strip fits on one line; a 10-K risk-factor section is twenty-seven, and a
  // flex row without shrink-0 answers that by compressing every box until "1"
  // is narrower than "27" and the count reads as ragged. Nothing shrinks, and
  // what does not fit goes to the next line.
  return (
    <div className="mt-[11px] flex flex-wrap items-center gap-x-[5px] gap-y-[6px]">
      <button
        type="button"
        onClick={() => step(index - 1)}
        disabled={index === 1}
        aria-label="Previous passage"
        className="shrink-0 px-[3px] font-mono text-[11px] text-muted-foreground disabled:opacity-40"
      >
        &lsaquo;
      </button>
      {Array.from({ length: section.total }, (_, i) => i + 1).map((n) => {
        const held = isHeld(section.passages[n - 1]);
        return (
          <button
            key={n}
            type="button"
            onClick={() => step(n)}
            aria-current={n === index ? "true" : undefined}
            aria-label={`Passage ${n} of ${section.total}${held ? "" : ", text not held"}`}
            className={`grid h-[20px] min-w-[22px] shrink-0 place-items-center border px-[3px] font-mono text-[10.5px] ${
              n === index
                ? // filled: accent-ink lightens in dark, so the label takes the
                  // surface colour rather than white
                  "border-primary bg-primary text-primary-foreground"
                : held
                  ? "border-line-hi bg-card text-ink-2"
                  : // a passage we can name but cannot show: dashed, the same
                    // way the patent rail distinguishes states in kind
                    "border-dashed border-line-hi bg-card text-muted-foreground"
            }`}
          >
            {n}
          </button>
        );
      })}
      <button
        type="button"
        onClick={() => step(index + 1)}
        disabled={index === section.total}
        aria-label="Next passage"
        className="shrink-0 px-[3px] font-mono text-[11px] text-muted-foreground disabled:opacity-40"
      >
        &rsaquo;
      </button>
      <span className="ml-2 shrink-0 whitespace-nowrap font-mono text-[10px] tracking-[0.06em] text-muted-foreground">
        {passageNote(section)}
      </span>
    </div>
  );
}

/**
 * What we read. The first of the two checks: a filled reading surface under a
 * tinted header, holding the exact stored text and nothing else. It scrolls
 * internally under a pinned footer, the passage running past the fold is
 * correct, because it stops anyone reading the excerpt as the whole section.
 *
 * When the text is not held, that is stated at the same weight rather than
 * shown as an empty or disabled panel. A citation whose passage cannot be
 * produced has to say so.
 */
export function PassagePanel() {
  const { open, sections, showPassage, loading, registerHeaderChip } = useInspector();
  if (!open) return null;

  const section = sections[open.sectionId];
  if (!section) return null;

  const current = section.passages[open.index - 1];
  const stored = Boolean(current?.paragraphs?.length);
  // held but not loaded yet is a third state: the text exists and is on its
  // way, which is not the same as having no text to show
  const fetching = !stored && isHeld(current) && loading;

  return (
    <>
      <div className="border-b border-border bg-card px-[26px] pb-[14px] pt-4">
        <div className="font-mono text-[11px] leading-[1.75] tracking-[0.015em] text-foreground">
          {/* The chip the reader clicked, landed. It is the far end of the
              open transition, and it also answers "which citation is this
              panel showing" without making anyone re-read the header. */}
          {open.label && (
            <span
              ref={registerHeaderChip}
              className="cite-chip mr-[6px] cursor-default align-baseline"
              aria-label={`Showing source ${open.label}`}
            >
              {open.label}
            </span>
          )}
          {headerFor(section, open.index).map((part, i) => (
            <span key={part}>
              {i > 0 && <span className="text-muted-foreground"> · </span>}
              {part}
            </span>
          ))}
        </div>
        {!section.tabular && (
          <Stepper section={section} index={open.index} onSelect={showPassage} />
        )}
      </div>

      <div className="flex justify-between border-b border-border bg-tint px-[26px] py-[11px] font-mono text-[10px] uppercase tracking-[0.1em] text-accent-deep">
        <span>
          {stored
            ? "What we read"
            : fetching
              ? "Fetching the stored text"
              : "No stored text for this passage"}
        </span>
        <span>{current?.characters ?? "–"}</span>
      </div>

      <ScrollArea className="min-h-0 flex-1 bg-card">
        <div className="px-[26px] pb-[26px] pt-[22px]">
          {stored ? (
            current.paragraphs!.map((text, i) => (
              <p
                key={i}
                className="mb-[13px] max-w-[58ch] text-justify text-[14.5px] leading-[1.66] hyphens-auto last:mb-0"
              >
                {text}
              </p>
            ))
          ) : (
            <p className="max-w-[58ch] text-[14.5px] leading-[1.66]">
              {fetching ? "Reading the passage from the store…" : NOT_STORED}
            </p>
          )}
        </div>
      </ScrollArea>

      <div className="flex items-center justify-between border-t border-border bg-card px-[26px] py-[9px]">
        <span className="sys-label">
          {current?.provenance ??
            (isHeld(current) ? "record held · text not loaded" : "record held · text not stored")}
        </span>
        <span className="font-mono text-[11px] tracking-[0.01em] text-ink-2">
          {current?.checksum ?? "–"}
        </span>
      </div>
    </>
  );
}
