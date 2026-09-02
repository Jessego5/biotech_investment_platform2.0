import { cn } from "@/lib/utils";

/**
 * Every figure shows the period it covers. A number without one is a bug,
 * so this is deliberately a component rather than a loose className.
 */
export function PeriodLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <span className={cn("period", className)}>{children}</span>;
}
