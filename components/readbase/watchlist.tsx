"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { CompanyPicker, type PickedCompany } from "@/components/readbase/company-picker";
import { PeriodLabel } from "@/components/readbase/period-label";

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

export function Watchlist() {
  const raw = useSyncExternalStore(store.subscribe, store.read, store.server);
  const tickers: string[] = (() => {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  })();

  const [rows, setRows] = useState<Row[]>([]);
  const [picking, setPicking] = useState(false);
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
      if (!tickers.includes(c.ticker)) store.write([...tickers, c.ticker]);
    },
    [tickers],
  );
  const remove = useCallback(
    (ticker: string) => store.write(tickers.filter((x) => x !== ticker)),
    [tickers],
  );

  const shown = key ? rows : [];

  return (
    <div className="mx-auto max-w-[1100px] px-8 py-[38px]">
      <div className="mb-[26px] flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h1 className="text-[23px] leading-[1.42]">Watchlist</h1>
          <p className="mt-1 max-w-[64ch] text-[14px] leading-[1.6] text-ink-2">
            What a watcher is watching for: the next readout, the nearest loss of
            protection, and how long the money lasts. No price and no position —
            those would be the first figures here neither computed from a filing
            nor traceable to one.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setPicking(true)}
          className="whitespace-nowrap bg-primary px-[14px] py-[8px] font-mono text-[11px] tracking-[0.05em] text-primary-foreground"
        >
          Add a company
        </button>
      </div>

      {tickers.length === 0 && (
        <div className="border border-border border-l-[3px] border-l-primary bg-secondary px-7 pb-[26px] pt-6">
          <h4 className="mb-3 font-mono text-[10px] font-normal uppercase tracking-[0.14em] text-accent-deep">
            Nothing watched yet
          </h4>
          <p className="max-w-[62ch] text-[19px] leading-[1.6]">
            Add a company and this becomes a row per issuer, refreshed from the
            corpus each time you open it.
          </p>
          <p className="mt-4 max-w-[62ch] text-[14px] leading-[1.6] text-ink-2">
            The list is kept in this browser. There are no accounts, so it does
            not follow you to another device — and nobody else sees it.
          </p>
        </div>
      )}

      {shown.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] border-collapse text-[13.5px]">
            <thead>
              <tr>
                {[
                  ["Company", ""],
                  ["Next readout", "primary completion"],
                  ["Protection", "Orange Book · Purple Book"],
                  ["Runway", "liquidity ÷ annual burn"],
                  ["", ""],
                ].map(([h, sub], i) => (
                  <th
                    key={h || i}
                    className="whitespace-normal border-b border-border px-0 pb-[7px] pr-[14px] text-left align-bottom font-mono text-[9.5px] font-normal uppercase tracking-[0.11em] text-muted-foreground"
                  >
                    {h}
                    {sub && (
                      <span className="mt-[2px] block normal-case tracking-[0.04em] opacity-80">
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
                return (
                  <tr key={row.ticker} className="border-b border-border">
                    <td className="px-0 py-[11px] pr-[14px] align-top">
                      <Link
                        href={`/companies/${row.ticker}`}
                        className="font-mono text-[12px] text-primary"
                      >
                        {row.ticker}
                      </Link>
                      <span className="mt-[2px] block max-w-[26ch] text-[13px] leading-[1.4]">
                        {row.name}
                      </span>
                    </td>

                    <td className="px-0 py-[11px] pr-[14px] align-top">
                      {row.next_readout ? (
                        <>
                          <span className="font-mono text-[12px] tabular-nums">
                            {row.next_readout.completion_date?.slice(0, 10)}
                          </span>
                          <span className="mt-[2px] block max-w-[34ch] text-[12.5px] leading-[1.45] text-ink-2">
                            {row.next_readout.title}
                          </span>
                          <span className="mt-[2px] block font-mono text-[10px] text-muted-foreground">
                            {row.next_readout.nct_id}
                          </span>
                        </>
                      ) : (
                        <span className="font-mono text-[11px] text-muted-foreground">
                          none with a date ahead
                        </span>
                      )}
                    </td>

                    <td className="px-0 py-[11px] pr-[14px] align-top">
                      <span className="text-[13px]">{row.protection_state}</span>
                      <span className="mt-[2px] block font-mono text-[11px] tabular-nums text-ink-2">
                        {row.next_expiry
                          ? `nearest expiry ${row.next_expiry}`
                          : "no expiry recorded"}
                      </span>
                    </td>

                    <td className="px-0 py-[11px] pr-[14px] align-top">
                      <span
                        className={`font-mono text-[12px] tabular-nums ${
                          runway.muted ? "text-muted-foreground" : ""
                        }`}
                      >
                        {runway.value}
                      </span>
                      {runway.note && (
                        <span className="mt-[2px] block font-mono text-[10px] text-muted-foreground">
                          {runway.note}
                        </span>
                      )}
                    </td>

                    <td className="px-0 py-[11px] text-right align-top">
                      <button
                        type="button"
                        onClick={() => remove(row.ticker)}
                        aria-label={`Stop watching ${row.ticker}`}
                        className="border border-line-hi px-[8px] py-[4px] font-mono text-[10px] text-ink-2"
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {shown.length > 0 && (
        <PeriodLabel className="mt-4 block whitespace-normal">
          {loading ? "refreshing from the corpus…" : "read from the corpus just now"}
          {" · "}
          the list is kept in this browser, not on the server
        </PeriodLabel>
      )}

      <CompanyPicker
        open={picking}
        onOpenChange={setPicking}
        onPick={add}
        exclude={tickers}
      />
    </div>
  );
}
