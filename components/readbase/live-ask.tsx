"use client";

/**
 * This is the Ask screen: the question box, the worked examples a reader arrives
 * at, the accessor steps, the answer and the sources behind it. A citation
 * resolves to the document behind its evidence block, and blocks that computed a
 * figure have no document to open and say so rather than offering a control that
 * leads nowhere. An answer that rests on nothing is a refusal and gets the
 * refusal card, which is a designed state carrying the same weight as an answer
 * and not a greyed-out failure. Rendered by app/ask/page.tsx, which passes the
 * corpus note.
 */

import { useState } from "react";
import { AnswerProse } from "@/components/readbase/answer-prose";
import { SourceRow } from "@/components/readbase/source-row";
import { PeriodLabel } from "@/components/readbase/period-label";
import { notusCard } from "@/lib/readbase/notus-theme";
import { AccessorSteps } from "@/components/readbase/accessor-steps";
import { RefusalCard } from "@/components/readbase/refusal-card";
import { accessorResults } from "@/lib/readbase/accessors";
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

/**
 * Questions that have each been run against this corpus, grouped by the shape
 * of answer they produce. The last one is here on purpose: it is refused, and a
 * reader should meet that state early rather than mistake it for a failure.
 */
const EXAMPLES: { q: string; shows: string }[] = [
  {
    q: "What does Vertex say about its intellectual property risks?",
    shows: "Filing text · opens the stored passage",
  },
  {
    q: "What was Moderna's revenue in 2019?",
    shows: "A reported figure · no passage behind it",
  },
  {
    q: "Which companies have a patent expiring soonest?",
    shows: "Across the universe · ranked",
  },
  {
    q: "Which companies have more than 20 active trials and over a billion in cash?",
    shows: "Filtered · 787 issuers",
  },
  {
    q: "How has GSK's pipeline changed since 2021?",
    shows: "Refused · outside the five-year window",
  },
];

/**
 * The frame around a live refusal. The sentence in the middle is the model's own
 * and the rows under it are the accessors that actually ran, so only the
 * heading, the caption and the remedy are written here. The remedy names what
 * this corpus holds, which is a fact about the corpus and true of every refusal,
 * rather than a guess at what the reader should have asked instead.
 *
 * Two refusals, because they are not the same event. The lookups can run and
 * come back with nothing the answer could stand on, or the question can be one
 * this never answers, declined before anything was read. Calling the second one
 * "no data" would blame the corpus for a boundary the system chose.
 */
const REFUSAL_CAPTION = "What was queried";

const CORPUS =
  "The corpus holds up to five years of annual reports per company, ten years " +
  "of reported figures, 30,823 trials and the FDA's patent and exclusivity tables.";

const REFUSAL = {
  noData: {
    heading: "No data for this",
    remedy:
      `${CORPUS} A question reaching outside that has nothing here to rest on. ` +
      "It can answer a company's pipeline by phase, its figures year by year, " +
      "what a filing says on a topic, or which companies match a filter.",
  },
  outOfScope: {
    heading: "Outside what this answers",
    remedy: `${CORPUS} It reports what those sources say and goes no further.`,
  },
};

export function LiveAsk({ corpusNote }: { corpusNote: string }) {
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [pending, setPending] = useState(false);
  const [answeredAt, setAnsweredAt] = useState<string | null>(null);

  async function run(q: string) {
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

  function submit(e: React.FormEvent) {
    e.preventDefault();
    void run(question.trim());
  }

  const evidence = result?.evidence ?? [];
  // Companies the answer actually drew on. Morphic offers follow-up questions
  // here; these are links to pages that exist rather than prompts written for
  // the reader, because a suggestion that leads nowhere is worse than none.
  //
  // Only shown when the answer cites something. A refusal still has rows
  // behind it, three lookups matched BIAFW, LONA and CTNM while declining a
  // question about GSK, and calling those "companies behind this answer"
  // would attribute the refusal to companies it never rested on.
  const cited = parseCitationMarkers(result?.answer ?? "").length > 0;
  const touched = cited
    ? [...new Set(evidence.flatMap((e) => e.tickers ?? []))].slice(0, 6)
    : [];
  const listings = evidence.map(listingFor);
  const dropped = result?.dropped_citations ?? 0;
  // A refusal is an answer resting on nothing: the model looked, found nothing
  // it could stand behind and said so, which is why it cites nothing. It is a
  // designed state and gets the refusal card rather than the answer card. The
  // greeting is not one, it is the canned reply to "what can you do" and never
  // looked anything up; the budget ceiling and a failed request are their own
  // states above.
  const tools = result?.tools_used ?? [];
  const refused =
    Boolean(result?.answer) &&
    !cited &&
    !result?.budget &&
    !result?.error &&
    !tools.includes("greeting");
  // Declined before anything was read, rather than read and found wanting.
  const declined = tools.includes("decline");
  // The refusal card lists what ran, so the rows under it are only worth their
  // space when one of them can be opened. Under an answer they always are: they
  // are what the citations point at.
  const showListings = refused
    ? listings.some((l) => l.chunkId || l.url)
    : listings.length > 0;

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
          {!asked && (
            // the corpus size lives on Browse, where it says what the search
            // box is searching over. The 28.5px it occupied is kept as padding
            // so the headline stays where it was.
            <div className="mb-8 pt-[28px] text-center">
              <h1 className="mx-auto mb-4 max-w-[16ch] text-[46px] font-medium leading-[1.08] tracking-[-0.03em]">
                Ask, and see the{" "}
                <span style={{ color: "var(--n-accent)" }}>working</span>
              </h1>
              <p
                className="mx-auto max-w-[52ch] text-[16px] leading-[1.6]"
                style={{ color: "var(--n-ink-2)" }}
              >
                {corpusNote}
              </p>
            </div>
          )}

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
            <div className="mt-8">
              <div
                className="mb-3 text-[12px] font-medium uppercase tracking-[0.12em]"
                style={{ color: "var(--n-ink-2)" }}
              >
                Try one of these
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex.q}
                    type="button"
                    onClick={() => {
                      setQuestion(ex.q);
                      void run(ex.q);
                    }}
                    className={`${notusCard} px-5 py-4 text-left`}
                    style={{ borderColor: "var(--n-line)" }}
                  >
                    <span className="block text-[15px] leading-[1.45]">{ex.q}</span>
                    <span
                      className="mt-2 block text-[12px]"
                      style={{ color: "var(--n-accent-deep)" }}
                    >
                      {ex.shows}
                    </span>
                  </button>
                ))}
              </div>
            </div>
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

              {/* Not under a refusal: the card below carries the same
                  accessors, and the working shown twice on one screen reads as
                  two different traces. */}
              {!pending && result && !refused && (
                <div className="mb-5">
                  <AccessorSteps tools={tools} evidence={evidence} dropped={dropped} />
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

              {/* Refusal is a designed state, not an error state: the same
                  typographic weight as an answer, a rule in the accent rather
                  than in warn, because nothing has gone wrong. The system knows
                  what it spent and says so. */}
              {result?.budget && (
                <div
                  className={`${notusCard} border-l-[3px] px-6 py-6`}
                  style={{ borderColor: "var(--n-line)", borderLeftColor: "var(--n-accent-deep)" }}
                >
                  <h4
                    className="mb-3 text-[10px] uppercase tracking-[0.14em]"
                    style={{ color: "var(--n-accent-deep)" }}
                  >
                    {result.budget.throttled ? "Too quickly" : "Budget spent"}
                  </h4>
                  {(result.answer ?? "").split("\n\n").map((para, i) => (
                    <p
                      key={i}
                      className="mb-3 max-w-[64ch] text-[16px] leading-[1.65] last:mb-0"
                      style={i > 0 ? { color: "var(--n-ink-2)" } : undefined}
                    >
                      {para}
                    </p>
                  ))}
                  {result.budget.limit !== undefined && (
                    <div
                      className="mt-4 border-t pt-3 tabular-nums text-[11.5px]"
                      style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}
                    >
                      {result.budget.used} of {result.budget.limit} questions
                      answered · resets {result.budget.resets}
                    </div>
                  )}
                </div>
              )}

              {result?.answer && !result.budget && !refused && (
                <div className={`${notusCard} px-6 py-6`} style={{ borderColor: "var(--n-line)" }}>
                  <AnswerProse
                    paragraphs={toAnswerNodes(result.answer, evidence.length)}
                    className="text-[17px] leading-[1.7]"
                    paragraphClassName="mb-4 max-w-[70ch] last:mb-0"
                  />
                </div>
              )}

              {refused && (
                <RefusalCard
                  {...(declined ? REFUSAL.outOfScope : REFUSAL.noData)}
                  statement={result?.answer ?? ""}
                  queriedCaption={REFUSAL_CAPTION}
                  queried={accessorResults(tools, evidence)}
                  className={notusCard}
                />
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

              {showListings && (
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
