import { NotusChrome } from "@/components/readbase/notus-chrome";
import { Browse } from "@/components/readbase/browse";
import { notusPage } from "@/lib/readbase/notus-theme";

export default function BrowsePage() {
  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome current="Browse" />
      <Browse />
    </div>
  );
}
