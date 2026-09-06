/**
 * This is the watchlist page. A tickers query parameter is a list someone was
 * sent, and it is read here rather than in the client so the page knows on its
 * first paint whether it is showing this browser's list or a visitor's, the two
 * saying different things and correcting one into the other afterwards showing
 * the reader a list that was never theirs.
 */

import { NotusChrome } from "@/components/readbase/notus-chrome";
import { Watchlist } from "@/components/readbase/watchlist";
import { notusPage } from "@/lib/readbase/notus-theme";

/**
 * ?tickers=VRTX,MRNA is a list someone was sent.
 *
 * Read here rather than from the client, so the page knows on its first paint
 * whether it is showing this browser's list or a visitor's, the two say
 * different things, and correcting one into the other afterwards would show
 * the reader a list that was never theirs.
 */
export default async function WatchlistPage({
  searchParams,
}: {
  searchParams: Promise<{ tickers?: string }>;
}) {
  const raw = (await searchParams).tickers ?? "";
  const shared = raw
    .split(",")
    .map((t) => t.trim().toUpperCase())
    .filter(Boolean);

  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome current="Watchlist" />
      {/* an empty parameter is not a shared list, it is the page */}
      <Watchlist shared={shared.length ? shared : null} />
    </div>
  );
}
