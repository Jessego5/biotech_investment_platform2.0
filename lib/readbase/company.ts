/**
 * The live company response, and the mappings the company page needs.
 *
 * Two things the canvas draws are not in this data, and are not invented here:
 * a programme has no record of its own (only the trials testing it), and an
 * indication is not carried on an approved product.
 */
import type { PhaseLevel, Series } from "@/lib/readbase/moderna";
import type { ProtectionState } from "@/lib/readbase/moderna";

export type HistoryPoint = {
  value: number;
  fiscal_year: number;
  fiscal_period: string;
  period_end: string;
};

export type CompanyResponse = {
  ticker: string;
  name: string;
  cik: string | null;
  pipeline: { total_trials: number; by_phase: Record<string, number> };
  financial_history: Record<string, HistoryPoint[]>;
  protection: {
    state: string;
    evidence: string[];
    products?: number;
    biologics?: number;
    next_expiry?: string | null;
    last_expiry?: string | null;
  } | null;
  readouts: {
    nct_id: string;
    title: string;
    phase: string;
    status: string;
    completion_date: string;
    conditions: string;
  }[];
  trials: {
    nct_id: string;
    title: string;
    phase: string;
    status: string;
    conditions: string;
    completion_date: string | null;
    enrollment: number | null;
  }[];
  filings: {
    form: string;
    filed: string;
    fiscal_year: number | null;
    period_end: string | null;
    accession: string;
    sections: string[];
    url: string | null;
  }[];
  interventions: {
    name: string;
    trials: number;
    phase: string | null;
    lead_nct: string | null;
    conditions: string[];
    approved_as: string | null;
    /** Other names the registry states are the same thing, so a merged row
     *  can be checked rather than taken on trust. */
    also_known_as: string[];
  }[];
  approved_products: {
    trade_name: string | null;
    ingredient: string | null;
    approval_date: string | null;
    applications: string[];
  }[];
  error?: string;
};

/** The registry's phase strings, onto the ordinal ramp. */
export function phaseLevel(phase: string | null): PhaseLevel | null {
  const p = (phase ?? "").toUpperCase().replace(/\s/g, "");
  if (p.includes("PHASE4")) return 4;
  if (p.includes("PHASE3")) return 3;
  if (p.includes("PHASE2")) return 2;
  if (p.includes("PHASE1")) return 1;
  return null;
}

export function phaseLabel(phase: string | null): string {
  const p = (phase ?? "").toUpperCase().replace(/\s/g, "");
  if (!p || p === "NA" || p === "N/A") return "Not stated";
  return p
    .split(",")
    .map((x) => x.replace("PHASE", "Phase "))
    .join("/")
    .replace(/Phase (\d)\/Phase (\d)/, "Phase $1/$2");
}

export function protectionState(state: string | undefined): ProtectionState {
  if (state === "protected") return "protected";
  if (state === "approved, no listed protection") return "approved-unlisted";
  return "no-product";
}

/** US$ at the scale the figure actually warrants. */
export function money(value: number): string {
  const sign = value < 0 ? "-" : "";
  const n = Math.abs(value);
  if (n >= 1e9) return `${sign}$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${sign}$${Math.round(n / 1e6)}M`;
  return `${sign}$${Math.round(n).toLocaleString()}`;
}

/**
 * One metric's history as a sparkline series. Years come from the data rather
 * than a fixed window, because not every issuer has ten of them.
 */
export function toSeries(
  name: string,
  points: HistoryPoint[] | undefined,
  opts: { zeroRule?: boolean } = {},
): (Series & { years: number[] }) | null {
  if (!points?.length) return null;
  // the API returns newest first; a series reads left to right in time
  const ordered = [...points].sort((a, b) => a.fiscal_year - b.fiscal_year);
  const values = ordered.map((p) => p.value / 1e9);
  const years = ordered.map((p) => p.fiscal_year);
  let peakIndex = 0;
  ordered.forEach((p, i) => {
    if (p.value > ordered[peakIndex].value) peakIndex = i;
  });
  const first = ordered[0];
  const last = ordered[ordered.length - 1];
  return {
    name,
    unit: "US$B",
    values,
    years,
    first: `FY${first.fiscal_year} ${money(first.value)}`,
    last: `FY${last.fiscal_year} ${money(last.value)}`,
    peakIndex,
    peakLabel: `peak FY${ordered[peakIndex].fiscal_year}`,
    zeroRule: opts.zeroRule,
  };
}
