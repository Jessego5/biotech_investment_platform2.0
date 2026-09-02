import { Chrome } from "@/components/readbase/chrome";
import { AnswerProse } from "@/components/readbase/answer-prose";
import { AccessorTrace } from "@/components/readbase/accessor-trace";
import { SourceRow } from "@/components/readbase/source-row";
import { RefusalCard } from "@/components/readbase/refusal-card";
import { PeriodLabel } from "@/components/readbase/period-label";
import { InspectorProvider } from "@/components/readbase/inspector-provider";
import { PassageSheet } from "@/components/readbase/passage-sheet";
import {
  accessorTrace,
  answer,
  answeredAt,
  filingUrl,
  question,
  sections,
  sourceLocation,
  sources,
} from "@/lib/readbase/vertex";

/**
 * Artboard 2 as drawn, on fixtures. Kept alongside the live /ask because it is
 * the reference for the refusal card, which needs a question the corpus
 * genuinely cannot answer to show at all.
 */
export default function AskFixturePage() {
  return (
    <InspectorProvider sections={sections} locate={sourceLocation}>
      <div className="min-h-svh bg-card text-foreground">
        <Chrome crumb={["ask", "fixture"]} />

        <div className="flex flex-col items-center pb-[52px] pt-[46px]">
          <div className="w-[788px]">
            <div className="mb-[38px] flex items-center gap-[14px] border border-line-hi bg-card px-[18px] py-[15px]">
              <span className="flex-1 text-[19px]">{question}</span>
              <span className="font-mono text-[10.5px] tracking-[0.1em] text-muted-foreground">
                return
              </span>
            </div>

            <div className="-mt-6 mb-[26px] flex items-baseline gap-[18px]">
              <PeriodLabel>{answeredAt}</PeriodLabel>
              <AccessorTrace {...accessorTrace} />
            </div>

            <AnswerProse
              paragraphs={answer}
              className="text-[19px] leading-[1.7]"
              paragraphClassName="mb-5 max-w-[70ch] last:mb-0"
            />

            <div className="mt-[34px] border-t border-border pt-[18px]">
              {sources.map((s) => (
                <SourceRow key={s.n} source={s} filingUrl={filingUrl} />
              ))}
            </div>

            <RefusalCard />
          </div>
        </div>

        <PassageSheet />
      </div>
    </InspectorProvider>
  );
}
