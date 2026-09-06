import { Chrome } from "@/components/readbase/chrome";
import { PeriodLabel } from "@/components/readbase/period-label";
import { AccessorTrace } from "@/components/readbase/accessor-trace";
import {
  accessorTrace,
  answer,
  answeredAt,
  question,
  sections,
  sourceLocation,
} from "@/lib/readbase/semaglutide";
import { headerFor, isHeld } from "@/lib/readbase/passages";
import type { AnswerNode } from "@/lib/readbase/types";

/** The sources a paragraph leans on, in the order it cites them. */
function citedIn(nodes: AnswerNode[]): number[] {
  const seen: number[] = [];
  for (const n of nodes) {
    if (n.kind === "chip" && !seen.includes(n.source)) seen.push(n.source);
  }
  return seen;
}

/**
 * Tufte's sidenote, applied to provenance.
 *
 * The chip-and-panel version asks the reader to click before it will say where
 * a claim came from. Here the source sits in the margin beside the sentence,
 * always visible — so the answer cannot be read without also reading what it
 * rests on. The passage still has to be opened; what the margin removes is
 * having to ask which document a sentence belongs to.
 *
 * The cost is width: a margin column takes room the panel used, and on a
 * narrow screen the notes have to fall inline, which is the point where this
 * treatment stops being an improvement.
 */
export default function SidenoteDemo() {
  return (
    <div className="min-h-svh bg-card text-foreground">
      <Chrome crumb={["demos", "sidenote"]} />

      <div className="mx-auto max-w-[1100px] px-10 py-[40px]">
        <h1 className="mb-1 max-w-[44ch] text-[23px] leading-[1.42]">{question}</h1>
        <div className="mb-[30px] flex flex-wrap items-baseline gap-[18px]">
          <PeriodLabel>{answeredAt}</PeriodLabel>
          <AccessorTrace {...accessorTrace} />
        </div>

        {answer.map((nodes, i) => {
          const cited = citedIn(nodes);
          return (
            <div
              key={i}
              className="grid grid-cols-1 gap-x-8 gap-y-2 border-b border-border py-5 last:border-b-0 lg:grid-cols-[1fr_260px]"
            >
              <p className="max-w-[62ch] text-[18px] leading-[1.68]">
                {nodes.map((node, j) => {
                  if (node.kind === "cited") {
                    return (
                      <span key={j} className="cited-sentence">
                        {node.text}
                      </span>
                    );
                  }
                  // the chip is gone: the margin already names the source, and
                  // a marker that adds nothing is decoration
                  if (node.kind === "chip") return null;
                  if (node.kind === "figure") {
                    return (
                      <span key={j} className="font-mono tabular-nums">
                        {node.text}
                      </span>
                    );
                  }
                  if (node.kind === "unresolved") {
                    return (
                      <span key={j} className="font-mono text-[10.5px] text-warn">
                        [{node.n} unsourced]
                      </span>
                    );
                  }
                  return <span key={j}>{node.text}</span>;
                })}
              </p>

              <aside className="lg:border-l lg:border-border lg:pl-4">
                {cited.map((n) => {
                  const at = sourceLocation[n];
                  const section = sections[at.sectionId];
                  const held = isHeld(section.passages[at.index - 1]);
                  return (
                    <div key={n} className="mb-3 last:mb-0">
                      <span className="mr-[6px] rounded-[2px] bg-cite px-[5px] py-[3px] font-mono text-[10.5px] text-cite-ink">
                        {n}
                      </span>
                      <span className="font-mono text-[10.5px] leading-[1.6] text-ink-2">
                        {headerFor(section, at.index).join(" · ")}
                      </span>
                      <span className="mt-1 block font-mono text-[9.5px] tracking-[0.06em] text-muted-foreground">
                        {held ? "passage stored · open to read it" : "record held · text not stored"}
                      </span>
                    </div>
                  );
                })}
                {cited.length === 0 && (
                  <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-warn">
                    no source
                  </span>
                )}
              </aside>
            </div>
          );
        })}

        <p className="mt-8 max-w-[70ch] font-mono text-[10px] leading-[1.6] text-muted-foreground">
          Every paragraph names its sources in the margin, including the last
          one, which cites the Orange Book and then says the two sources
          disagree on scope. In the chip version that disagreement is a sentence
          you have to read; here the two documents sit side by side while you
          read it.
        </p>
      </div>
    </div>
  );
}
