import { CiteChip } from "@/components/readbase/cite-chip";
import type { AnswerNode } from "@/lib/readbase/types";

/**
 * The answer. A cited sentence is marked in place rather than merely followed
 * by a chip, so it is visible which words the citation is standing behind, and
 * figures are set in mono inside the serif so they stay countable.
 */
export function AnswerProse({
  paragraphs,
  className = "",
  paragraphClassName = "mb-[18px] last:mb-0",
}: {
  paragraphs: AnswerNode[][];
  className?: string;
  paragraphClassName?: string;
}) {
  return (
    <div className={className}>
      {paragraphs.map((nodes, i) => (
        <p key={i} className={paragraphClassName}>
          {nodes.map((node, j) => {
            switch (node.kind) {
              case "chip":
                return (
                  <CiteChip key={node.id} id={node.id} source={node.source} />
                );
              case "cited":
                return (
                  <span key={j} className="cited-sentence">
                    {node.text}
                  </span>
                );
              case "figure":
                return (
                  <span key={j} className="font-mono tabular-nums">
                    {node.text}
                  </span>
                );
              default:
                return <span key={j}>{node.text}</span>;
            }
          })}
        </p>
      ))}
    </div>
  );
}
