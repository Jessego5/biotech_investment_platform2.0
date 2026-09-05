"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CompanyPicker, type PickedCompany } from "@/components/readbase/company-picker";
import { notusCard } from "@/lib/readbase/notus-theme";
import { phaseLevel } from "@/lib/readbase/company";

const STORE = "readbase.watchlist";

type Row = {
  ticker: string;
  name: string;
  sector: string | null;
  next_readout: {
    nct_id: string;
    title: string;
    phase: string;
    completion_date: string;
  } | null;
  protection_state: string;
  next_expiry: string | null;
  runway: number | null;
  burn_source: string | null;
  cash_generative: boolean | null;
  liquidity_note: string | null;
};

/** The three states a null runway can mean, kept apart. */
function runwayCell(row: Row) {
  if (row.runway !== null) {
    return {
      value: `${row.runway.toFixed(2)} yr`,
      note: row.burn_source ? `burn from ${row.burn_source}` : null,
      muted: false,
    };
  }
  if (row.cash_generative) {
    return { value: "self-funding", note: "no runway to report", muted: false };
  }
  return {
    value: "not computable",
    note: "no burn figure to divide by",
    muted: true,
  };
}

/**
 * The list, read straight out of the browser.
 *
 * useSyncExternalStore rather than an effect that assigns state on mount: it
 * gives the server a snapshot of its own, so the first paint agrees with the
 * markup instead of correcting itself afterwards.
 */
const store = {
  subscribe(onChange: () => void) {
    window.addEventListener("storage", onChange);
    window.addEventListener(STORE, onChange);
    return () => {
      window.removeEventListener("storage", onChange);
      window.removeEventListener(STORE, onChange);
    };
  },
  read: () => {
    try {
      return window.localStorage.getItem(STORE) ?? "[]";
    } catch {
      // a browser refusing storage is not a reason to break the page
      return "[]";
    }
  },
  // nothing is watched until the browser says otherwise
  server: () => "[]",
  write(next: string[]) {
    try {
      window.localStorage.setItem(STORE, JSON.stringify(next));
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(STORE));
  },
};

/**
 * @param shared a list arriving in the URL rather than from this browser.
 *
 * This is the whole of the answer to "my watchlist does not follow me to
 * another device". There are no accounts, so the list cannot be looked up —
 * but it is four tickers, and four tickers fit in a link. Sending yourself one
 * moves the list; sending it to someone else shares it. Neither needs a user.
 */
export function Watchlist({ shared = null }: { shared?: string[] | null }) {
  const router = useRouter();
  const raw = useSyncExternalStore(store.subscribe, store.read, store.server);
  const mine: string[] = (() => {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  })();

  // A link never edits the browser it is opened in. Someone following a shared
  // list is reading it, and replacing what they watch to show it to them would
  // be destroying one list to display another.
  const visiting = shared !== null;
  const tickers = visiting ? shared : mine;

  const [rows, setRows] = useState<Row[]>([]);
  const [picking, setPicking] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  // which ticker list `rows` actually describes. Comparing it to the current
  // one gives the refreshing state without a second flag to keep in step, and
  // it is only ever assigned after the request comes back.
  const [loadedFor, setLoadedFor] = useState("");
  const key = tickers.join(",");
  const loading = key !== loadedFor;

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    fetch(`/api/watchlist?tickers=${encodeURIComponent(key)}`)
      .then((r) => r.json())
      .then((b) => {
        if (cancelled) return;
        setLoadedFor(key);
        setRows(b.companies ?? []);
      })
      .catch(() => {
        if (!cancelled) setRows([]);
      });
    return () => {
      cancelled = true;
    };
  }, [key]);

  const add = useCallback(
    (c: PickedCompany) => {
      if (!mine.includes(c.ticker)) store.write([...mine, c.ticker]);
    },
    [mine],
  );
  const remove = useCallback(
    (ticker: string) => store.write(mine.filter((x) => x !== ticker)),
    [mine],
  );

  /** Merge, never replace: keeping a shared list should not cost you your own. */
  const keepShared = useCallback(() => {
    store.write([...mine, ...(shared ?? []).filter((t) => !mine.includes(t))]);
    router.push("/watchlist");
  }, [mine, shared, router]);

  const copyLink = useCallback(async () => {
    const url = `${window.location.origin}/watchlist?tickers=${mine.join(",")}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied("copied");
    } catch {
      // a browser that refuses the clipboard still has to give the reader the
      // link, so show it rather than reporting a failure they cannot act on
      setCopied(url);
    }
  }, [mine]);

  const shown = key ? rows : [];

  return (
    <div className="mx-auto max-w-[1100px] px-8 py-[38px]">
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[30px] font-medium tracking-[-0.02em]">Watchlist</h1>
          <p className="mt-2 max-w-[64ch] text-[15px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
            What a watcher is watching for: the next readout, the nearest loss of
            protection, and how long the money lasts. No price and no position —
            those would be the first figures here neither computed from a filing
            nor traceable to one.
          </p>
        </div>
        {visiting ? (
          <Link
            href="/watchlist"
            className="whitespace-nowrap rounded-full border px-[18px] py-[10px] text-[14px] font-medium"
            style={{ borderColor: "var(--n-accent)", color: "var(--n-accent-deep)" }}
          >
            Back to my list
          </Link>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            {mine.length > 0 && (
              <button
                type="button"
                onClick={copyLink}
                className="whitespace-nowrap rounded-full border px-[18px] py-[10px] text-[14px] font-medium"
                style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}
              >
                {copied === "copied" ? "Link copied" : "Copy as link"}
              </button>
            )}
            <button
              type="button"
              onClick={() => setPicking(true)}
              className="whitespace-nowrap rounded-full px-[18px] py-[10px] text-[14px] font-medium text-white"
              style={{ background: "var(--n-accent-deep)" }}
            >
              Add a company
            </button>
          </div>
        )}
      </div>

      {copied && copied !== "copied" && (
        <div className={`${notusCard} mb-5 px-6 py-4`} style={{ borderColor: "var(--n-line)" }}>
          <p className="mb-2 text-[13px]" style={{ color: "var(--n-ink-2)" }}>
            This browser would not let the page reach the clipboard. The link:
          </p>
          <input
            readOnly
            value={copied}
            onFocus={(e) => e.currentTarget.select()}
            className="w-full bg-transparent font-mono text-[12px] outline-none"
          />
        </div>
      )}

      {visiting && (
        <div className={`${notusCard} mb-5 px-6 py-5`} style={{ borderColor: "var(--n-accent)" }}>
          <h2 className="mb-2 text-[15px] font-medium">
            A list from a link, not the one this browser keeps
          </h2>
          <p className="mb-4 max-w-[64ch] text-[14px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
            {tickers.length} {tickers.length === 1 ? "company" : "companies"}, read
            from the corpus the same way. Nothing here has changed what you watch
            {mine.length > 0 ? `, and your own ${mine.length} are still there.` : "."}
          </p>
          <button
            type="button"
            onClick={keepShared}
            className="rounded-full px-[18px] py-[9px] text-[14px] font-medium text-white"
            style={{ background: "var(--n-accent-deep)" }}
          >
            Add these to my list
          </button>
        </div>
      )}

      {!visiting && tickers.length === 0 && (
        <div className={`${notusCard} px-7 pb-7 pt-6`} style={{ borderColor: "var(--n-line)" }}>
          <div
            className="mb-3 flex h-9 w-9 items-center justify-center rounded-[10px]"
            style={{ background: "var(--n-accent-soft)", color: "var(--n-accent-deep)" }}
          >
            <span className="text-[15px]">◆</span>
          </div>
          <h4 className="mb-2 text-[17px] font-medium">Nothing watched yet</h4>
          <p className="max-w-[62ch] text-[15px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
            Add a company and this becomes a row per issuer, refreshed from the
            corpus each time you open it.
          </p>
          <p className="mt-3 max-w-[62ch] text-[13px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
            The list is kept in this browser. There are no accounts, so it does
            not follow you to another device by itself — but it fits in a link,
            and once there is something here you can copy one and send it to
            yourself or to anyone else.
          </p>
        </div>
      )}

      {shown.length > 0 && (
        <div className={`${notusCard} overflow-hidden`} style={{ borderColor: "var(--n-line)" }}>
          <div className="flex items-center justify-between px-6 py-[18px]">
            <h2 className="text-[17px] font-medium">
              {shown.length} {shown.length === 1 ? "company" : "companies"}
            </h2>
            <span
              className="rounded-full border px-3 py-1 text-[12px]"
              style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}
            >
              {loading ? "refreshing…" : "read just now"}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table
              className="w-full min-w-[860px] border-t text-[14px]"
              style={{ borderColor: "var(--n-line)" }}
            >
              <thead>
                <tr style={{ color: "var(--n-ink-2)" }}>
                  {[
                    ["Company", ""],
                    ["Next readout", "primary completion"],
                    ["Protection", "Orange Book · Purple Book"],
                    ["Runway", "liquidity ÷ annual burn"],
                    ["", ""],
                  ].map(([h, sub], i) => (
                    <th
                      key={h || i}
                      className="border-b px-6 py-3 text-left align-bottom text-[13px] font-normal"
                      style={{ borderColor: "var(--n-line)" }}
                    >
                      {h}
                      {sub && (
                        <span className="mt-[2px] block font-mono text-[10px] opacity-70">
                          {sub}
                        </span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => {
                  const runway = runwayCell(row);
                  const level = phaseLevel(row.next_readout?.phase ?? null);
                  return (
                    <tr key={row.ticker}>
                      <td className="border-b px-6 py-[14px] align-top" style={{ borderColor: "var(--n-line)" }}>
                        <Link href={`/companies/${row.ticker}`} className="font-medium">
                          {row.ticker}
                        </Link>
                        <span className="mt-[2px] block max-w-[24ch] text-[13px] leading-[1.4]" style={{ color: "var(--n-ink-2)" }}>
                          {row.name}
                        </span>
                      </td>

                      <td className="border-b px-6 py-[14px] align-top" style={{ borderColor: "var(--n-line)" }}>
                        {row.next_readout ? (
                          <>
                            <span className="inline-flex items-center gap-2">
                              {/* the step is the phase of the study reporting,
                                  which is the one ordered thing in this row */}
                              <span
                                className="h-[9px] w-[9px] rounded-full"
                                style={{ background: level ? `var(--p${level})` : "#c7d0cb" }}
                              />
                              <span className="font-mono text-[13px] tabular-nums">
                                {row.next_readout.completion_date?.slice(0, 10)}
                              </span>
                            </span>
                            <span className="mt-[3px] block max-w-[36ch] text-[12.5px] leading-[1.45]" style={{ color: "var(--n-ink-2)" }}>
                              {row.next_readout.title}
                            </span>
                            <span className="mt-[2px] block font-mono text-[10.5px] opacity-70" style={{ color: "var(--n-ink-2)" }}>
                              {row.next_readout.nct_id}
                            </span>
                          </>
                        ) : (
                          <span className="text-[13px]" style={{ color: "var(--n-ink-2)" }}>
                            none with a date ahead
                          </span>
                        )}
                      </td>

                      <td className="border-b px-6 py-[14px] align-top" style={{ borderColor: "var(--n-line)" }}>
                        <span
                          className="rounded-full px-[10px] py-1 text-[12.5px]"
                          style={{ background: "var(--n-accent-soft)", color: "var(--n-accent-deep)" }}
                        >
                          {row.protection_state}
                        </span>
                        <span className="mt-[4px] block font-mono text-[11px] tabular-nums" style={{ color: "var(--n-ink-2)" }}>
                          {row.next_expiry ? `nearest expiry ${row.next_expiry}` : "no expiry recorded"}
                        </span>
                      </td>

                      <td className="border-b px-6 py-[14px] align-top" style={{ borderColor: "var(--n-line)" }}>
                        <span
                          className="font-mono text-[13px] tabular-nums"
                          style={{ color: runway.muted ? "var(--n-ink-2)" : "var(--n-ink)" }}
                        >
                          {runway.value}
                        </span>
                        {runway.note && (
                          <span className="mt-[2px] block font-mono text-[10.5px]" style={{ color: "var(--n-ink-2)" }}>
                            {runway.note}
                          </span>
                        )}
                      </td>

                      <td className="border-b px-6 py-[14px] text-right align-top" style={{ borderColor: "var(--n-line)" }}>
                        {!visiting && (
                          <button
                            type="button"
                            onClick={() => remove(row.ticker)}
                            aria-label={`Stop watching ${row.ticker}`}
                            className="rounded-full border px-[12px] py-[5px] text-[12px]"
                            style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="px-6 py-4 text-[12px]" style={{ color: "var(--n-ink-2)" }}>
            Read from the corpus on each visit. The list is kept in this browser,
            not on the server — a link carries the tickers, and the rows are
            rebuilt from the corpus at the other end.
          </p>
        </div>
      )}

      <CompanyPicker
        open={picking}
        onOpenChange={setPicking}
        onPick={add}
        exclude={mine}
      />
    </div>
  );
}
