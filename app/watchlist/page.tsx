import { NotusChrome } from "@/components/readbase/notus-chrome";
import { Watchlist } from "@/components/readbase/watchlist";
import { notusPage } from "@/lib/readbase/notus-theme";

export default function WatchlistPage() {
  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome current="Watchlist" />
      <Watchlist />
    </div>
  );
}
