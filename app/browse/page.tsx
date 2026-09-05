import { NotusChrome } from "@/components/readbase/notus-chrome";
import { Browse } from "@/components/readbase/browse";
import { notusPage } from "@/lib/readbase/notus-theme";
import { API_BASE } from "@/lib/readbase/api";

/**
 * How much there is to search, counted now.
 *
 * This is the page where the figure earns its place: it tells a reader what
 * the box in front of them is searching over. It says so rather than showing a
 * number it could not read.
 */
async function corpusLine(): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/stats`, { cache: "no-store" });
    if (!res.ok) return "corpus size unavailable";
    const s = await res.json();
    const n = (v: number) => v.toLocaleString("en-US");
    return [
      `${n(s.companies)} companies`,
      `${n(s.approved_products)} approved products`,
      `${n(s.filings)} annual reports`,
      `${n(s.trials_total ?? s.trials)} trials`,
    ].join(" · ");
  } catch {
    return "corpus size unavailable";
  }
}

export default async function BrowsePage() {
  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome current="Browse" />
      <Browse corpus={await corpusLine()} />
    </div>
  );
}
