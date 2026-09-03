import Link from "next/link";
import { Chrome } from "@/components/readbase/chrome";

const DEMOS: [string, string, string][] = [
  [
    "/ask/semaglutide",
    "As built — chip and panel",
    "The canvas as specified. Provenance is a chip you click, opening the stored passage beside the answer. Baseline for comparison.",
  ],
  [
    "/demos/sidenote",
    "Tufte — provenance in the margin",
    "The source sits beside the sentence it supports, always visible, nothing to click. Borrowed from Tufte CSS's sidenote.",
  ],
  [
    "/demos/notus",
    "Notus — modern SaaS register",
    "The company page in a white, sans-serif, pill-and-card style with a green accent. Replaces the design language rather than adjusting it.",
  ],
  [
    "/demos/paper",
    "FT Origami — editorial register",
    "A newspaper's treatment of the same answer: warmer ground, one wide measure, figures set as editorial data rather than as table cells.",
  ],
];

export default function DemosPage() {
  return (
    <div className="min-h-svh bg-card text-foreground">
      <Chrome crumb={["demos"]} />
      <div className="mx-auto max-w-[788px] px-8 py-[46px]">
        <h1 className="mb-4 text-[23px] leading-[1.42]">
          Four treatments, one corpus
        </h1>
        <p className="mb-[34px] max-w-[62ch] text-[16px] leading-[1.6] text-ink-2">
          The same content, rendered several ways — so the question is which
          makes provenance easiest to check, not which looks better in
          isolation. The first three are one answer; the Notus demo is the
          Vertex company page, since that register is built around tiles and
          charts rather than prose.
        </p>
        {DEMOS.map(([href, title, note]) => (
          <Link
            key={href}
            href={href}
            className="grid grid-cols-1 gap-1 border-b border-border py-[15px] sm:grid-cols-[240px_1fr] sm:gap-4"
          >
            <span className="text-[15px]">{title}</span>
            <span className="text-[14px] leading-[1.5] text-ink-2">
              {note}
              <span className="mt-[3px] block font-mono text-[10px] text-muted-foreground">
                {href}
              </span>
            </span>
          </Link>
        ))}
        <p className="mt-8 max-w-[62ch] font-mono text-[10px] leading-[1.6] text-muted-foreground">
          These are exploratory. The paper demo declares its own colours in a
          scoped block rather than using the product palette, which the brief
          otherwise forbids in a component — it is the point of that demo, and
          it is confined to it.
        </p>
      </div>
    </div>
  );
}
