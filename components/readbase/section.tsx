/**
 * This is a section head: a title against the heavier rule, with its period on
 * the right. Used by the canvas register screens.
 */

import { PeriodLabel } from "@/components/readbase/period-label";

export function SectionHead({ title, period }: { title: string; period: string }) {
  return (
    <div className="mb-[14px] flex flex-wrap items-baseline justify-between gap-x-4 border-b border-line-hi pb-[7px]">
      <h3 className="text-[16px] font-normal tracking-[0.01em]">{title}</h3>
      {/* .period is nowrap so a date never breaks mid-figure; a whole sentence
          of provenance has to be allowed to wrap on a narrow screen */}
      <PeriodLabel className="whitespace-normal lg:whitespace-nowrap">
        {period}
      </PeriodLabel>
    </div>
  );
}

export function Section({
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
    <section id={id} className="mb-[34px] scroll-mt-6 last:mb-0">
      <SectionHead title={title} period={period} />
      {children}
    </section>
  );
}
