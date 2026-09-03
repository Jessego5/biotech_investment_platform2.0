import { NotusChrome } from "@/components/readbase/notus-chrome";
import { LiveAsk } from "@/components/readbase/live-ask";
import { notusPage } from "@/lib/readbase/notus-theme";

/**
 * Ask, against the live corpus. The fixtures that stood in for this while the
 * artboards were built now live at /ask/fixture, in the canvas register.
 */
export default function AskPage() {
  return (
    <div style={notusPage} className="min-h-svh">
      <NotusChrome current="Ask" />
      <LiveAsk corpusNote="Every figure here comes from a filing, a trial record or an FDA table, and every one can be opened and checked. Ask a question to begin." />
    </div>
  );
}
