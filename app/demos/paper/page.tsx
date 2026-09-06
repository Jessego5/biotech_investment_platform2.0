/**
 * This is the FT Origami register applied to the same answer. A newspaper sets a
 * financial story on warm paper at a generous measure, with figures pulled out
 * of the prose rather than tabulated and sources gathered at the foot as a note
 * on the reporting, which is the opposite trade from the canvas: easier to read
 * straight through, harder to audit line by line. The colours here are declared
 * locally and are deliberately not the product palette, since the brief forbids
 * raw values in a component and this demo exists to show what a different ground
 * would feel like.
 */

import { Chrome } from "@/components/readbase/chrome";
import {
  answer,
  answeredAt,
  question,
  sections,
  sourceLocation,
  sources,
} from "@/lib/readbase/semaglutide";
import { headerFor } from "@/lib/readbase/passages";

/**
 * The FT Origami register, applied to the same answer.
 *
 * A newspaper sets a financial story on warm paper at a generous measure, with
 * figures pulled out of the prose rather than tabulated, and sources gathered
 * at the foot as a note on the reporting. It is the opposite trade from the
 * canvas: easier to read straight through, harder to audit line by line.
 *
 * The colours below are declared locally and are NOT the product palette,
 * the brief forbids raw values in a component, and this demo exists to show
 * what a different ground would feel like, so it declares its own and keeps
 * them here.
 */
const PAPER = {
  "--paper": "#fff1e5",      // FT's paper
  "--paper-ink": "#33302e",
  "--paper-ink-2": "#66605c",
  "--paper-rule": "#e6d9ce",
  "--paper-accent": "#990f3d", // FT claret
} as React.CSSProperties;

export default function PaperDemo() {
  return (
    <div className="min-h-svh bg-card text-foreground">
      <Chrome crumb={["demos", "paper"]} />

      <div
        style={{ ...PAPER, background: "var(--paper)", color: "var(--paper-ink)" }}
        className="min-h-svh"
      >
        <div className="mx-auto max-w-[720px] px-8 py-[52px]">
          <div
            className="mb-6 font-mono text-[10px] uppercase tracking-[0.16em]"
            style={{ color: "var(--paper-accent)" }}
          >
            Novo Nordisk A/S · intellectual property
          </div>

          <h1 className="mb-5 max-w-[24ch] text-[34px] leading-[1.18] tracking-[-0.01em]">
            {question}
          </h1>

          <div
            className="mb-8 border-b pb-4 font-mono text-[10.5px] tracking-[0.04em]"
            style={{ borderColor: "var(--paper-rule)", color: "var(--paper-ink-2)" }}
          >
            {answeredAt} · four sources · every figure below is drawn from a filing
          </div>

          {answer.map((nodes, i) => (
            <p key={i} className="mb-6 text-[19px] leading-[1.62]">
              {nodes.map((node, j) => {
                if (node.kind === "chip") {
                  return (
                    <sup
                      key={j}
                      className="ml-[2px] font-mono text-[11px]"
                      style={{ color: "var(--paper-accent)" }}
                    >
                      {node.source}
                    </sup>
                  );
                }
                if (node.kind === "figure") {
                  return (
                    <b key={j} className="font-mono font-normal tabular-nums">
                      {node.text}
                    </b>
                  );
                }
                if (node.kind === "cited") {
                  return <span key={j}>{node.text}</span>;
                }
                if (node.kind === "unresolved") {
                  return (
                    <sup key={j} className="font-mono text-[11px]">
                      [{node.n}?]
                    </sup>
                  );
                }
                return <span key={j}>{node.text}</span>;
              })}
            </p>
          ))}

          <div
            className="mt-10 border-t pt-5"
            style={{ borderColor: "var(--paper-rule)" }}
          >
            <div
              className="mb-3 font-mono text-[10px] uppercase tracking-[0.16em]"
              style={{ color: "var(--paper-accent)" }}
            >
              Sources
            </div>
            {sources.map((s) => {
              const at = sourceLocation[s.n];
              return (
                <div
                  key={s.n}
                  className="grid grid-cols-[18px_1fr] gap-3 border-b py-[10px] last:border-b-0"
                  style={{ borderColor: "var(--paper-rule)" }}
                >
                  <span
                    className="font-mono text-[11px]"
                    style={{ color: "var(--paper-accent)" }}
                  >
                    {s.n}
                  </span>
                  <span
                    className="font-mono text-[11px] leading-[1.6]"
                    style={{ color: "var(--paper-ink-2)" }}
                  >
                    {headerFor(sections[at.sectionId], at.index).join(" · ")}
                  </span>
                </div>
              );
            })}
          </div>

          <p
            className="mt-8 max-w-[62ch] text-[14px] leading-[1.6]"
            style={{ color: "var(--paper-ink-2)" }}
          >
            Note what this register costs. The superscripts read as a
            newspaper&rsquo;s footnotes, a gesture at authority, where the
            warm chip was a control that opened the exact text. Gathering
            sources at the foot separates a claim from its evidence by the
            length of the article, which is exactly the distance this product
            exists to close.
          </p>
        </div>
      </div>
    </div>
  );
}
