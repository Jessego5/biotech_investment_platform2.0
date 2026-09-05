"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { notusCard } from "@/lib/readbase/notus-theme";

type Hit = {
  kind: "company" | "product" | "filing" | "trial";
  id: string;
  title: string;
  subtitle: string | null;
  meta: string | null;
  href: string;
};

/** Each kind takes a step from the ordinal palette, so a list reads by type. */
const KIND: Record<Hit["kind"], { label: string; chip: string; glyph: string }> = {
  company: { label: "Company", chip: "var(--p4)", glyph: "#ffffff" },
  product: { label: "Product", chip: "var(--p2)", glyph: "#020887" },
  filing: { label: "Filing", chip: "var(--p3)", glyph: "#020887" },
  trial: { label: "Trial", chip: "var(--p1)", glyph: "#020887" },
};

const KINDS = ["company", "product", "filing", "trial"] as const;

export function Browse() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<string | null>(null);
  const [hits, setHits] = useState<Hit[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [ran, setRan] = useState("");

  useEffect(() => {
    const q = query.trim();
    // nothing typed is not a result to store — it is a state to render, so it
    // is derived below rather than assigned here
    if (!q) return;
    let cancelled = false;
    const id = setTimeout(async () => {
      try {
        const res = await fetch(
          `/api/search?q=${encodeURIComponent(q)}${kind ? `&kind=${kind}` : ""}`,
        );
        const body = await res.json();
        if (cancelled) return;
        setHits(body.results ?? []);
        setCounts(body.counts ?? {});
        setRan(q);
      } catch {
        if (!cancelled) setHits([]);
      }
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [query, kind]);

  // only show what belongs to the query on screen now, so clearing the box
  // empties the list without a second render to do it
  const typed = query.trim();
  const shown = typed && ran === typed ? hits : typed ? hits : [];
  const total = typed ? Object.values(counts).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="mx-auto max-w-[900px] px-8 pb-16 pt-10">
      <div className="mb-6 text-center">
        <h1 className="mx-auto mb-3 max-w-[18ch] text-[40px] font-medium leading-[1.1] tracking-[-0.03em]">
          Everything the corpus{" "}
          <span style={{ color: "var(--n-accent)" }}>holds</span>
        </h1>
        <p
          className="mx-auto max-w-[56ch] text-[15px] leading-[1.6]"
          style={{ color: "var(--n-ink-2)" }}
        >
          Companies, approved products, annual reports and trials. Search by
          name, ticker, brand or accession — each result opens the thing it
          actually is. The counts are on the front page, read from the corpus
          rather than typed here, which is how the last hand-written figure went
          wrong.
        </p>
      </div>

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Trikafta, VRTX, ivacaftor, 0000875320-26-000056…"
        aria-label="Search the corpus"
        className={`${notusCard} mb-4 w-full px-5 py-4 text-[17px] outline-none`}
        style={{ borderColor: "var(--n-line)" }}
      />

      <div className="mb-6 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setKind(null)}
          className="rounded-full border px-[14px] py-[6px] text-[13px]"
          style={
            kind === null
              ? { borderColor: "var(--n-accent)", color: "var(--n-accent-deep)" }
              : { borderColor: "var(--n-line)", color: "var(--n-ink-2)" }
          }
        >
          Everything
        </button>
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(kind === k ? null : k)}
            className="rounded-full border px-[14px] py-[6px] text-[13px]"
            style={
              kind === k
                ? { borderColor: "var(--n-accent)", color: "var(--n-accent-deep)" }
                : { borderColor: "var(--n-line)", color: "var(--n-ink-2)" }
            }
          >
            {KIND[k].label}
            {counts[k] !== undefined && (
              <span className="ml-2 tabular-nums opacity-70">{counts[k]}</span>
            )}
          </button>
        ))}
      </div>

      {typed && shown.length === 0 && ran === typed && (
        <div className={`${notusCard} px-6 py-6`} style={{ borderColor: "var(--n-line)" }}>
          <p className="text-[15px]">
            Nothing held under &ldquo;{query.trim()}&rdquo;.
          </p>
          <p className="mt-2 text-[13px]" style={{ color: "var(--n-ink-2)" }}>
            This matches names, tickers, brands and accession numbers as written
            — it is not the semantic search the chat uses, so a near-miss will
            not be guessed at.
          </p>
        </div>
      )}

      {shown.length > 0 && (
        <>
          <div className="mb-3 text-[13px]" style={{ color: "var(--n-ink-2)" }}>
            {total} {total === 1 ? "match" : "matches"}, capped at eight per kind
          </div>
          <div className={`${notusCard} overflow-hidden`} style={{ borderColor: "var(--n-line)" }}>
            {shown.map((h) => {
              const k = KIND[h.kind];
              const external = h.href.startsWith("http");
              const Row = (
                <>
                  <span
                    className="mt-[2px] flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] text-[10px]"
                    style={{ background: k.chip, color: k.glyph }}
                  >
                    ◆
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[15px] leading-[1.4]">{h.title}</span>
                    <span className="mt-[2px] block text-[12.5px]" style={{ color: "var(--n-ink-2)" }}>
                      {[h.subtitle, h.meta].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                  <span
                    className="shrink-0 rounded-full px-[10px] py-[3px] text-[11.5px]"
                    style={{ background: "var(--n-accent-soft)", color: "var(--n-accent-deep)" }}
                  >
                    {k.label}
                    {external && " ↗"}
                  </span>
                </>
              );
              const cls =
                "flex items-start gap-3 border-b px-6 py-[14px] last:border-b-0";
              return external ? (
                <a
                  key={`${h.kind}-${h.id}`}
                  href={h.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={cls}
                  style={{ borderColor: "var(--n-line)" }}
                >
                  {Row}
                </a>
              ) : (
                <Link
                  key={`${h.kind}-${h.id}`}
                  href={h.href}
                  className={cls}
                  style={{ borderColor: "var(--n-line)" }}
                >
                  {Row}
                </Link>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
