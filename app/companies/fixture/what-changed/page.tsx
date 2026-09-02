import { Chrome } from "@/components/readbase/chrome";
import {
  ProvenanceStrip,
  WithheldNote,
} from "@/components/readbase/provenance-strip";
import {
  DiffGroup,
  DiffGroupHead,
  TextDiff,
} from "@/components/readbase/diff-group";
import {
  comparable,
  financialRows,
  groups,
  legend,
  notComparable,
  pipelineRows,
  riskFactor,
  secondHeading,
} from "@/lib/readbase/diff";
import { company } from "@/lib/readbase/moderna";

export default function WhatChangedPage() {
  return (
    <div className="min-h-svh bg-card text-foreground">
      <Chrome
        crumb={["companies", "fixture", company.name, "what changed", "FY2024 → FY2025"]}
      />

      <div className="px-[30px] pb-[34px] pt-[26px]">
        {/* --------------------------------------------------- comparable */}
        <ProvenanceStrip
          earlier={comparable.earlier}
          later={comparable.later}
          verdict={comparable.verdict}
        />

        <DiffGroup {...groups.financial} rows={financialRows} />
        <DiffGroup {...groups.pipeline} rows={pipelineRows} />

        <div className="mb-[26px]">
          <DiffGroupHead heading={riskFactor.heading} count={riskFactor.count} />
          <div className="grid grid-cols-[20px_1fr] items-baseline gap-4 border-b border-border py-[11px]">
            <span className="text-center font-mono text-[12px] leading-none text-muted-foreground">
              ≈
            </span>
            <span>
              <span className="text-[14px] leading-[1.45]">{riskFactor.label}</span>
              <TextDiff parts={riskFactor.parts} />
            </span>
          </div>
        </div>

        <div className="mt-[22px] flex gap-5 border-t border-border pt-[14px]">
          {[legend.lead, ...legend.keys].map((item) => (
            <span
              key={item}
              className="font-mono text-[10px] tracking-[0.05em] text-muted-foreground"
            >
              {item}
            </span>
          ))}
        </div>

        {/* ----------------------------------------------- not comparable */}
        <div className="mb-3 mt-[34px]">
          <h3 className="m-0 text-[15px] font-normal">{secondHeading}</h3>
        </div>

        <ProvenanceStrip
          earlier={notComparable.earlier}
          later={notComparable.later}
          verdict={notComparable.verdict}
          comparable={false}
        />
        <WithheldNote caption={notComparable.noteCaption}>
          {notComparable.note}
        </WithheldNote>
      </div>
    </div>
  );
}
