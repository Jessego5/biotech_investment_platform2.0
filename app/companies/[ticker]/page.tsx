/**
 * This is one company, live from the corpus. It fetches server-side so the page
 * arrives whole, and a ticker the corpus does not hold gets a page saying so
 * rather than an empty one.
 */

import { LiveCompany } from "@/components/readbase/live-company";

export default async function CompanyPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  return <LiveCompany ticker={ticker} />;
}
