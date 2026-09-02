import { Chrome } from "@/components/readbase/chrome";
import { AnswerProse } from "@/components/readbase/answer-prose";
import { SourceIndex } from "@/components/readbase/source-index";
import { PassagePanel } from "@/components/readbase/passage-panel";
import { InspectorProvider } from "@/components/readbase/inspector-provider";
import { OriginalDocument } from "@/components/readbase/original-document";
import { PeriodLabel } from "@/components/readbase/period-label";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  accessorTrace,
  answeredAt,
  answer,
  question,
  sections,
  sourceLocation,
  sources,
} from "@/lib/readbase/semaglutide";

/** The chip the reader arrived on. Source 1 is cited twice; only this one is open. */
const INITIAL_CHIP = "1a";
const INITIAL_SOURCE = 1;

export default function SourceInspectorPage() {
  return (
    <InspectorProvider
      sections={sections}
      locate={sourceLocation}
      initialSource={INITIAL_SOURCE}
      initialChipId={INITIAL_CHIP}
    >
      <div className="flex h-svh flex-col bg-card text-foreground">
        <Chrome
          crumb={["Novo Nordisk A/S", "ask", "semaglutide patent expiry"]}
        />

        <ResizablePanelGroup
          orientation="horizontal"
          className="min-h-0 flex-1"
        >
          {/* ---------------------------------------------------- the answer */}
          <ResizablePanel defaultSize={856} minSize={480}>
            <div className="flex h-full flex-col overflow-hidden px-11 pt-[34px]">
              <h1 className="mb-1 max-w-[44ch] text-[23px] leading-[1.42]">
                {question}
              </h1>

              <div className="mb-[26px] flex items-baseline gap-[18px]">
                <PeriodLabel>{answeredAt}</PeriodLabel>
                <span className="font-mono text-[10px] tracking-[0.04em] text-muted-foreground">
                  read{" "}
                  {accessorTrace.accessors.map((a, i) => (
                    <span key={a}>
                      {i > 0 && " · "}
                      <b className="font-normal text-primary">{a}</b>
                    </span>
                  ))}
                  {" — "}
                  {accessorTrace.result}
                </span>
              </div>

              <AnswerProse
                paragraphs={answer}
                className="max-w-[66ch] text-[18px] leading-[1.68]"
              />

              <SourceIndex sources={sources} />
            </div>
          </ResizablePanel>

          <ResizableHandle />

          {/* ------------------------------- what we read, then the original */}
          <ResizablePanel defaultSize={583} minSize={360}>
            <div className="flex h-full min-h-0 flex-col overflow-hidden bg-secondary">
              <PassagePanel />
              <OriginalDocument />
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </InspectorProvider>
  );
}
