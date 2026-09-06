/**
 * This is the period a figure covers. Every figure shows one, and a number
 * without one is a bug, which is why this is a component rather than a loose
 * className that can be forgotten.
 */

import { cn } from "@/lib/utils";

export function PeriodLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <span className={cn("period", className)}>{children}</span>;
}
