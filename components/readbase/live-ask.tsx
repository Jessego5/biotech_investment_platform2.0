"use client";

import { useState } from "react";
import { AnswerProse } from "@/components/readbase/answer-prose";
import { SourceRow } from "@/components/readbase/source-row";
import { PeriodLabel } from "@/components/readbase/period-label";
import { notusCard } from "@/lib/readbase/notus-theme";
import { AccessorSteps } from "@/components/readbase/accessor-steps";
import Link from "next/link";
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
import { parseCitationMarkers } from "@/lib/readbase/citations";

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
  // Companies the answer actually drew on. Morphic offers follow-up questions
  // here; these are links to pages that exist rather than prompts written for
  // the reader, because a suggestion that leads nowhere is worse than none.
  //
  // Only shown when the answer cites something. A refusal still has rows
  // behind it — three lookups matched BIAFW, LONA and CTNM while declining a
  // question about GSK — and calling those "companies behind this answer"
  // would attribute the refusal to companies it never rested on.
  const cited = parseCitationMarkers(result?.answer ?? "").length > 0;
  const touched = cited
    ? [...new Set(evidence.flatMap((e) => e.tickers ?? []))].slice(0, 6)
    : [];
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
            className={`${notusCard} mb-8 flex items-center gap-[14px] px-5 py-4`}
            style={{ borderColor: "var(--n-line)" }}
          >
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about trials by phase, R&D, cash, patents or expected readouts"
              aria-label="Ask a question"
              className="flex-1 bg-transparent text-[17px] outline-none placeholder:text-muted-foreground"
            />
            <button
              type="submit"
              disabled={pending || !question.trim()}
              className="whitespace-nowrap rounded-full px-[16px] py-[8px] text-[13px] font-medium text-white disabled:opacity-40"
              style={{ background: "var(--n-accent-deep)" }}
            >
              {pending ? "Reading…" : "Ask"}
            </button>
          </form>

          {!asked && (
            <p className="max-w-[62ch] text-[15px] leading-[1.6] text-ink-2">
              {corpusNote}
            </p>
          )}

          {asked && (
            <>
              <p className="mb-4 max-w-[70ch] text-[22px] font-medium leading-[1.4] tracking-[-0.01em]">
                {asked}
              </p>

              <div className="mb-4 flex flex-wrap items-baseline gap-4">
                {answeredAt && !pending && <PeriodLabel>{answeredAt}</PeriodLabel>}
                {pending && (
                  <span className="text-[13px]" style={{ color: "var(--n-ink-2)" }}>
                    Reading the corpus…
                  </span>
                )}
              </div>

              {!pending && result && (
                <div className="mb-5">
                  <AccessorSteps
                    tools={result.tools_used ?? []}
                    evidence={evidence}
                    dropped={dropped}
                    // Open when the answer cites nothing. Lookups returning
                    // rows is not the same as the answer resting on them —
                    // "I don't have data on GSK since 2021" comes back after
                    // three successful lookups, and that is the answer where
                    // the working matters most.
                    defaultOpen={parseCitationMarkers(result.answer ?? "").length === 0}
                  />
                </div>
              )}

              {result?.error && (
                <div className={`${notusCard} px-6 py-6`} style={{ borderColor: "var(--warn)" }}>
                  <h4 className="mb-2 text-[16px] font-medium" style={{ color: "var(--warn)" }}>
                    The API did not answer
                  </h4>
                  <p className="max-w-[62ch] text-[15px] leading-[1.6]">{result.error}</p>
                </div>
              )}

              {result?.answer && (
                <div className={`${notusCard} px-6 py-6`} style={{ borderColor: "var(--n-line)" }}>
                  <AnswerProse
                    paragraphs={toAnswerNodes(result.answer, evidence.length)}
                    className="text-[17px] leading-[1.7]"
                    paragraphClassName="mb-4 max-w-[70ch] last:mb-0"
                  />
                </div>
              )}

              {touched.length > 0 && (
                <div className="mt-5 flex flex-wrap items-center gap-2">
                  <span className="text-[13px]" style={{ color: "var(--n-ink-2)" }}>
                    Companies behind this answer
                  </span>
                  {touched.map((t) => (
                    <Link
                      key={t}
                      href={`/companies/${t}`}
                      className="rounded-full border px-[12px] py-[5px] text-[12.5px]"
                      style={{ borderColor: "var(--n-accent)", color: "var(--n-accent-deep)" }}
                    >
                      {t}
                    </Link>
                  ))}
                </div>
              )}

              {listings.length > 0 && (
                <div className={`${notusCard} mt-5 px-6 py-2`} style={{ borderColor: "var(--n-line)" }}>
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
