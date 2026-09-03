import { Chrome } from "@/components/readbase/chrome";
import { Watchlist } from "@/components/readbase/watchlist";

export default function WatchlistPage() {
  return (
    <div className="min-h-svh bg-card text-foreground">
      <Chrome crumb={["watchlist"]} />
      <Watchlist />
    </div>
  );
}
