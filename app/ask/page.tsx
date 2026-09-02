import { Chrome } from "@/components/readbase/chrome";
import { LiveAsk } from "@/components/readbase/live-ask";

/**
 * Ask, against the live corpus. The fixtures that stood in for this while the
 * artboards were built now live at /ask/fixture.
 */
export default function AskPage() {
  return (
    <div className="min-h-svh bg-card text-foreground">
      <Chrome crumb={["ask"]} />
      <LiveAsk corpusNote="Every figure here comes from a filing, a trial record or an FDA table, and every one can be opened and checked. Ask a question to begin." />
    </div>
  );
}
