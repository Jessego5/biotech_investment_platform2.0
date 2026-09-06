/**
 * This names the two snapshots being compared, including the extractor version
 * and ingest date for each, and states whether they can honestly be diffed at
 * all. The system can genuinely say that two filings are not comparable, so the
 * strip has to be able to say it, because presenting a rule change as an event
 * would be the bug. Rendered at the top of the what-changed screens.
 */

import type { Snapshot } from "@/lib/readbase/diff";

function SnapshotCell({ snapshot, emphasise }: { snapshot: Snapshot; emphasise?: boolean }) {
  return (
    <div>
      <div className="font-mono text-[9.5px] uppercase tracking-[0.11em] text-muted-foreground">
        {snapshot.role}
      </div>
      <div className="mt-1 font-mono text-[11.5px] leading-[1.55]">
        {snapshot.document}
        <br />
        <span className="text-ink-2">
          {snapshot.detail} · extractor{" "}
          {/* the version is what decides comparability, so it is called out
              rather than left to be spotted in a run of identifiers */}
          <b className={emphasise ? "font-semibold text-foreground" : "font-normal"}>
            {snapshot.extractor}
          </b>{" "}
          · {snapshot.ingested}
        </span>
      </div>
    </div>
  );
}

export function ProvenanceStrip({
  earlier,
  later,
  verdict,
  comparable = true,
}: {
  earlier: Snapshot;
  later: Snapshot;
  verdict: string;
  comparable?: boolean;
}) {
  return (
    <div
      className={`mb-3 grid grid-cols-[1fr_1fr_auto] items-center gap-[22px] bg-secondary px-[18px] py-[14px] ${
        comparable
          ? "border border-line-hi"
          : "border border-warn border-l-[3px] border-l-warn"
      }`}
    >
      <SnapshotCell snapshot={earlier} emphasise={!comparable} />
      <SnapshotCell snapshot={later} emphasise={!comparable} />
      <span
        className={`whitespace-nowrap px-[9px] py-[5px] font-mono text-[10px] uppercase tracking-[0.08em] ${
          comparable ? "bg-tint text-accent-deep" : "bg-warn text-white"
        }`}
      >
        {verdict}
      </span>
    </div>
  );
}

/** The withheld-comparison note. Attaches directly under a failed strip. */
export function WithheldNote({ caption, children }: { caption: string; children: React.ReactNode }) {
  return (
    <div className="mb-[26px] border border-t-0 border-warn bg-card px-[18px] pb-[15px] pt-[13px]">
      <div className="mb-[7px] font-mono text-[10px] uppercase tracking-[0.1em] text-warn">
        {caption}
      </div>
      <p className="m-0 max-w-[88ch] text-[14.5px] leading-[1.6]">{children}</p>
    </div>
  );
}
