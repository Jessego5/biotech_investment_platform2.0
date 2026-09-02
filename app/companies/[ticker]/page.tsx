import { LiveCompany } from "@/components/readbase/live-company";

export default async function CompanyPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  return <LiveCompany ticker={ticker} />;
}
