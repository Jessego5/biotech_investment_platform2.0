/**
 * This holds the live company response and the mappings the company page needs.
 * Two things the canvas draws are not in this data and are not invented here: a
 * programme has no record of its own, only the trials testing it, and an
 * indication is not carried on an approved product. Imported by live-company.tsx
 * and by the watchlist for phaseLevel and the money formatting.
 */
import type { PhaseLevel, Series } from "@/lib/readbase/moderna";
import type { ProtectionState } from "@/lib/readbase/moderna";

export type HistoryPoint = {
  value: number;
  fiscal_year: number;
  fiscal_period: string;
  period_end: string;
  /** What the value is counted in, as XBRL reported it: "USD", "DKK", "JPY".
   *  Null where the figure predates the column and its currency is unknown,
   *  which is not the same claim as dollars. */
  unit?: string | null;
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

/**
 * Symbols only where the symbol is unambiguous. "kr" is Danish, Swedish and
 * Norwegian krone at once, so everything outside this map is written with its
 * ISO code, mirroring units.py on the service.
 */
const SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  JPY: "¥",
  GBP: "£",
};

/**
 * What the code stands for, spelled out. A reader who knows what $ means does
 * not necessarily know SGD from SEK, so wherever a figure stands on its own the
 * currency is named rather than left as three letters. Mirrors units.py on the
 * service; anything missing falls back to its code, which is still true.
 */
const NAMES: Record<string, string> = {
  USD: "US dollars",
  EUR: "euro",
  GBP: "pounds sterling",
  JPY: "Japanese yen",
  DKK: "Danish kroner",
  SEK: "Swedish kronor",
  NOK: "Norwegian kroner",
  CHF: "Swiss francs",
  CAD: "Canadian dollars",
  AUD: "Australian dollars",
  NZD: "New Zealand dollars",
  SGD: "Singapore dollars",
  HKD: "Hong Kong dollars",
  ILS: "Israeli shekels",
  INR: "Indian rupees",
  CNY: "Chinese yuan",
  KRW: "South Korean won",
  TWD: "Taiwan dollars",
  BRL: "Brazilian reais",
  MXN: "Mexican pesos",
  ZAR: "South African rand",
  PLN: "Polish zloty",
};

/** The currency spelled out, or the code itself where it is not known. */
export function currencyName(unit: string | null | undefined): string {
  if (unit === undefined) return NAMES.USD;
  if (!unit) return "an unrecorded unit";
  return NAMES[unit] ?? unit;
}

/**
 * One figure at the scale it warrants, in the currency it was reported in.
 *
 * The unit defaults to dollars for the canvas fixtures, whose figures are US
 * filers by construction. Live data passes what the service stored, null
 * included: a figure whose currency was never recorded says so rather than
 * borrowing a dollar sign, which is how kroner and yen came to be displayed as
 * dollars in the first place.
 */
export function money(
  value: number,
  unit: string | null | undefined = "USD",
  { name = false }: { name?: boolean } = {},
): string {
  const sign = value < 0 ? "-" : "";
  const n = Math.abs(value);
  const scaled =
    n >= 1e9
      ? `${(n / 1e9).toFixed(2)}B`
      : n >= 1e6
        ? `${Math.round(n / 1e6)}M`
        : Math.round(n).toLocaleString();
  if (!unit) return `${sign}${scaled} (unit not recorded)`;
  const symbol = SYMBOLS[unit];
  const figure = symbol
    ? `${sign}${symbol}${scaled}`
    : `${sign}${unit} ${scaled}`;
  // dollars need no gloss; repeating one down a column of them would bury the
  // figures it is there to qualify
  return name && unit !== "USD" ? `${figure} (${currencyName(unit)})` : figure;
}

/**
 * The label above a series drawn in billions of one currency.
 *
 * Dollars keep the short form the canvas draws. Anything else spells the
 * currency out, because this label is the only place the reader is told what
 * the line is counted in, and "DKK B" answers that only for someone who already
 * knows what DKK is.
 */
export function scaleLabel(unit: string | null | undefined): string {
  if (unit === undefined || unit === "USD") return "US$B";
  if (!unit) return "billions · unit not recorded";
  return `${currencyName(unit)}, billions`;
}

/**
 * One metric's history as a sparkline series. Years come from the data rather
 * than a fixed window, because not every issuer has ten of them.
 */
export function toSeries(
  name: string,
  points: HistoryPoint[] | undefined,
  opts: { zeroRule?: boolean } = {},
): (Series & { years: number[]; currency?: string | null }) | null {
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
  // One currency for the whole line, or none. A company that changed reporting
  // currency has a step in its series that is not a change in the business, and
  // drawing that as one trend under one label would be the same mistake this
  // column was added to fix, so the label says the line is mixed instead.
  //
  // An absent unit and a null one are different claims, and both arrive here: a
  // canvas fixture has no such field and is dollars by construction, while a
  // live row whose currency was never recorded sends null and must say so.
  const units = new Set(ordered.map((p) => p.unit));
  return {
    name,
    unit: units.size === 1 ? scaleLabel([...units][0]) : "mixed currencies",
    // the code as well as the label, so a caller can name the currency in its
    // own words rather than parsing it back out of an axis label
    currency: units.size === 1 ? [...units][0] : undefined,
    values,
    years,
    first: `FY${first.fiscal_year} ${money(first.value, first.unit)}`,
    last: `FY${last.fiscal_year} ${money(last.value, last.unit)}`,
    peakIndex,
    peakLabel: `peak FY${ordered[peakIndex].fiscal_year}`,
    zeroRule: opts.zeroRule,
  };
}
