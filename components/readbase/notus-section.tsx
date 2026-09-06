import { notusCard } from "@/lib/readbase/notus-theme";

/**
 * This is a section rendered as a card, with its period beside the title rather
 * than under it. The period is not optional here for the same reason it is not
 * optional in the canvas: a figure without the span it covers is a figure that
 * cannot be checked. Used across the company page for each block of figures.
 */
export function NotusSection({
  id,
  title,
  period,
  children,
}: {
  id?: string;
  title: string;
  period: string;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      className={`${notusCard} scroll-mt-6 overflow-hidden`}
      style={{ borderColor: "var(--n-line)" }}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-6 pb-4 pt-5">
        <h2 className="text-[17px] font-medium">{title}</h2>
        <span className="font-mono text-[10.5px]" style={{ color: "var(--n-ink-2)" }}>
          {period}
        </span>
      </div>
      <div className="px-6 pb-6">{children}</div>
    </section>
  );
}
