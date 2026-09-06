/**
 * This is Ask against the live corpus. The fixtures that stood in for it while
 * the artboards were being built now live at /ask/fixture, in the canvas
 * register.
 */

import { NotusChrome } from "@/components/readbase/notus-chrome";
import { LiveAsk } from "@/components/readbase/live-ask";
import { notusPage } from "@/lib/readbase/notus-theme";

export default function AskPage() {
  return (
    <div style={notusPage} className="notus min-h-svh">
      <NotusChrome current="Ask" />
      <LiveAsk corpusNote="Every figure here comes from a filing, a trial record or an FDA table, and every one can be opened and checked. Ask a question to begin." />
    </div>
  );
}
