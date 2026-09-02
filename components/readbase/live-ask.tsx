"use client";

import { useState } from "react";
import { AnswerProse } from "@/components/readbase/answer-prose";
import { SourceRow } from "@/components/readbase/source-row";
import { PeriodLabel } from "@/components/readbase/period-label";
import { InspectorProvider } from "@/components/readbase/inspector-provider";
import { PassageSheet } from "@/components/readbase/passage-sheet";
import {
  ask,
  fetchChunk,
  sectionFromChunk,
  splitPassage,
  toAnswerNodes,
  type AskResponse,
  type EvidenceBlock,
} from "@/lib/readbase/api";
import type { SourceListing } from "@/lib/readbase/types";

/**
 * A citation resolves to the document behind its evidence block. Blocks that
 * computed a figure have no document to open, and say so rather than offering
 * a control that leads nowhere.
 */
function listingFor(block: EvidenceBlock): SourceListing & {
  chunkId?: number;
  url?: string;
} {
  const doc = block.documents?.[0];
  return {
    n: block.n,
    document: doc?.label ?? block.label,
    locator: doc?.detail ?? block.source,
    chunkId: doc?.chunk_id ?? undefined,
    url: doc?.url ?? undefined,
  };
}

export function LiveAsk({ corpusNote }: { corpusNote: string }) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [answeredAt, setAnsweredAt] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || pending) return;
    setPending(true);
    setAsked(q);
    setResult(null);
    try {
      const res = await ask(q);
      setResult(res);
      setAnsweredAt(
        `answered ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`,
      );
    } catch {
      setResult({ answer: "", error: "The request failed before it reached the API." });
    } finally {
      setPending(false);
    }
  }

  const evidence = result?.evidence ?? [];
  const listings = evidence.map(listingFor);
  const dropped = result?.dropped_citations ?? 0;

  return (
    <InspectorProvider
      resolveSource={async (source) => {
        const chunkId = listings.find((l) => l.n === source)?.chunkId;
        if (!chunkId) return null;
        const chunk = await fetchChunk(chunkId);
        return chunk?.chunk_id ? sectionFromChunk(chunk) : null;
      }}
      loadPassage={async (chunkId) => {
        const chunk = await fetchChunk(chunkId);
        if (!chunk?.chunk_id) return null;
        return {
          characters: `${chunk.text.length.toLocaleString()} characters`,
          provenance: "stored verbatim · no summarisation",
          paragraphs: splitPassage(chunk.text),
        };
      }}
    >
      <div className="flex flex-col items-center pb-[52px] pt-[46px]">
        <div className="w-[788px] max-w-full">
          <form
            onSubmit={submit}
            className="mb-[38px] flex items-center gap-[14px] border border-line-hi bg-card px-[18px] py-[15px]"
          >
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about trials by phase, R&D, cash, patents or expected readouts"
              aria-label="Ask a question"
              className="flex-1 bg-transparent text-[19px] outline-none placeholder:text-muted-foreground"
            />
            <button
              type="submit"
              disabled={pending || !question.trim()}
              className="font-mono text-[10.5px] tracking-[0.1em] text-muted-foreground disabled:opacity-40"
            >
              {pending ? "reading" : "return"}
            </button>
          </form>

          {!asked && (
            <p className="max-w-[62ch] text-[15px] leading-[1.6] text-ink-2">
              {corpusNote}
            </p>
          )}

          {asked && (
            <>
              <p className="mb-[26px] max-w-[70ch] text-[19px] leading-[1.7]">{asked}</p>

              <div className="mb-[26px] flex flex-wrap items-baseline gap-[18px]">
                {answeredAt && !pending && <PeriodLabel>{answeredAt}</PeriodLabel>}
                <span className="font-mono text-[10px] tracking-[0.04em] text-muted-foreground">
                  {pending ? (
                    "reading the corpus…"
                  ) : (
                    <>
                      read{" "}
                      {(result?.tools_used ?? []).length
                        ? result!.tools_used!.map((t, i) => (
                            <span key={`${t}-${i}`}>
                              {i > 0 && " · "}
                              <b className="font-normal text-primary">{t}</b>
                            </span>
                          ))
                        : "nothing"}
                      {" — "}
                      {evidence.length} block{evidence.length === 1 ? "" : "s"} returned
                      {/* the drop is reported rather than left silent: a
                          citation removed from the prose still happened */}
                      {dropped > 0 && (
                        <span className="text-warn">
                          {" · "}
                          {dropped} citation{dropped === 1 ? "" : "s"} removed, pointing at
                          blocks that were never returned
                        </span>
                      )}
                    </>
                  )}
                </span>
              </div>

              {result?.error && (
                <div className="border border-border border-l-[3px] border-l-warn bg-secondary px-7 pb-[26px] pt-6">
                  <h4 className="mb-3 font-mono text-[10px] font-normal uppercase tracking-[0.14em] text-warn">
                    The API did not answer
                  </h4>
                  <p className="max-w-[62ch] text-[19px] leading-[1.6]">{result.error}</p>
                </div>
              )}

              {result?.answer && (
                <AnswerProse
                  paragraphs={toAnswerNodes(result.answer, evidence.length)}
                  className="text-[19px] leading-[1.7]"
                  paragraphClassName="mb-5 max-w-[70ch] last:mb-0"
                />
              )}

              {listings.length > 0 && (
                <div className="mt-[34px] border-t border-border pt-[18px]">
                  {listings.map((l) => (
                    <SourceRow
                      key={l.n}
                      source={l}
                      filingUrl={l.url}
                      readable={Boolean(l.chunkId)}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <PassageSheet />
    </InspectorProvider>
  );
}
