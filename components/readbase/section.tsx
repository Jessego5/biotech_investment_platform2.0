import { PeriodLabel } from "@/components/readbase/period-label";

/** Section head: a title against the heavier rule, with its period on the right. */
export function SectionHead({ title, period }: { title: string; period: string }) {
  return (
    <div className="mb-[14px] flex items-baseline justify-between border-b border-line-hi pb-[7px]">
      <h3 className="text-[16px] font-normal tracking-[0.01em]">{title}</h3>
      <PeriodLabel>{period}</PeriodLabel>
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
