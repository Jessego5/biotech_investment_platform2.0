import { API_BASE } from "@/lib/readbase/api";
import { money, phaseLabel, toSeries, type CompanyResponse } from "@/lib/readbase/company";

/**
 * The Notus register, applied to the company page, with green where the
 * template uses coral.
 *
 * This deliberately breaks four of the brief's non-negotiables — sans rather
 * than serif, generous radii rather than near-sharp corners, shadows rather
 * than rules, and colour used as decoration. It is a comparison of design
 * languages, not an adjustment of one, so its tokens are declared here and
 * kept out of the product palette.
 *
 * The data is the live corpus, so the two registers can be judged on the same
 * figures rather than on lorem.
 */
const NOTUS = {
  "--n-bg": "#fbfbfa",
  "--n-card": "#ffffff",
  "--n-ink": "#16171a",
  "--n-ink-2": "#6b7076",
  "--n-line": "#ececea",
  "--n-accent": "#1d9e75",
  "--n-accent-soft": "#e1f5ee",
  "--n-accent-deep": "#0f6e56",
  "--n-sans":
    'ui-sans-serif, system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif',
} as React.CSSProperties;

const card =
  "rounded-[14px] border bg-[var(--n-card)] shadow-[0_1px_2px_rgba(16,24,40,0.04),0_1px_3px_rgba(16,24,40,0.06)]";

async function load(ticker: string): Promise<CompanyResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/company/${ticker}`, { cache: "no-store" });
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}

function Donut({ slices }: { slices: { label: string; n: number }[] }) {
  const total = slices.reduce((a, s) => a + s.n, 0) || 1;
  const shades = ["var(--n-accent)", "#5dcaa5", "#9fe1cb", "#c9e9dd", "#e1f5ee"];
  const C = 2 * Math.PI * 54;
  // offsets worked out before the render rather than accumulated during it
  const arcs = slices.reduce<{ label: string; len: number; at: number }[]>((acc, s) => {
    const prev = acc[acc.length - 1];
    const at = prev ? prev.at + prev.len : 0;
    return [...acc, { label: s.label, len: (s.n / total) * C, at }];
  }, []);
  return (
    <div className="flex items-center gap-7">
      <svg width="150" height="150" viewBox="0 0 150 150">
        <g transform="rotate(-90 75 75)">
          {arcs.map((a, i) => (
            <circle
              key={a.label}
              cx="75" cy="75" r="54" fill="none"
              stroke={shades[i % shades.length]}
              strokeWidth="17"
              strokeDasharray={`${a.len} ${C - a.len}`}
              strokeDashoffset={-a.at}
              strokeLinecap="butt"
            />
          ))}
        </g>
        <text x="75" y="70" textAnchor="middle" style={{ fontSize: 26, fontWeight: 600 }} fill="var(--n-ink)">
          {total}
        </text>
        <text x="75" y="90" textAnchor="middle" style={{ fontSize: 11 }} fill="var(--n-ink-2)">
          trials
        </text>
      </svg>
      <div className="space-y-[10px]">
        {slices.map((s, i) => (
          <div key={s.label} className="flex items-center gap-[10px] text-[13px]">
            <span
              className="h-[9px] w-[18px] rounded-full"
              style={{ background: shades[i % shades.length] }}
            />
            <span style={{ color: "var(--n-ink-2)" }}>{s.label}</span>
            <span className="font-medium">{s.n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default async function NotusDemo() {
  const data = await load("VRTX");
  if (!data?.ticker) {
    return <div className="p-10">The API is not reachable.</div>;
  }

  const rd = toSeries("R&D", data.financial_history?.rd_expense);
  const rev = toSeries("Revenue", data.financial_history?.revenue);
  const phases = Object.entries(
    Object.entries(data.pipeline?.by_phase ?? {}).reduce<Record<string, number>>((a, [p, n]) => {
      const l = phaseLabel(p);
      a[l] = (a[l] ?? 0) + n;
      return a;
    }, {}),
  )
    .sort((a, b) => b[1] - a[1])
    .map(([label, n]) => ({ label, n }));
  // every bucket, not the top few: the donut's centre total has to agree with
  // the trial count in the tile above it, and slicing the tail made it 232
  // against 244 with nothing on the page to explain the twelve missing

  const stats = [
    { n: String(data.pipeline?.total_trials ?? 0), label: "Registered trials", delta: `${phases[0]?.n ?? 0} in ${phases[0]?.label ?? "—"}` },
    { n: String((data.approved_products ?? []).length), label: "Approved products", delta: data.protection?.state ?? "—" },
    { n: rd ? money(rd.values[rd.values.length - 1] * 1e9) : "—", label: "R&D, latest year", delta: rd ? rd.peakLabel : "—" },
    { n: String((data.filings ?? []).length), label: "Annual reports held", delta: "five-year window" },
  ];

  return (
    <div
      style={{ ...NOTUS, background: "var(--n-bg)", color: "var(--n-ink)", fontFamily: "var(--n-sans)" }}
      className="min-h-svh"
    >
      {/* header */}
      <div className="border-b bg-[var(--n-card)]" style={{ borderColor: "var(--n-line)" }}>
        <div className="mx-auto flex max-w-[1180px] items-center gap-8 px-8 py-4">
          <span className="text-[19px] font-semibold tracking-[-0.02em]">Readbase</span>
          <nav className="hidden gap-7 text-[14px] md:flex" style={{ color: "var(--n-ink-2)" }}>
            {["Companies", "Ask", "Filings", "Trials"].map((x) => (
              <span key={x}>{x}</span>
            ))}
          </nav>
          <div className="flex-1" />
          <span className="rounded-full bg-[var(--n-ink)] px-[18px] py-[9px] text-[14px] font-medium text-white">
            Start asking
          </span>
        </div>
      </div>

      <div className="mx-auto max-w-[1180px] px-8 py-10">
        {/* hero, in the template's centred register */}
        <div className="mb-12 text-center">
          <div className="mb-3 text-[14px]" style={{ color: "var(--n-accent)" }}>
            787 companies · 3,614 annual reports
          </div>
          <h1 className="mx-auto mb-4 max-w-[16ch] text-[52px] font-medium leading-[1.06] tracking-[-0.03em]">
            Every figure traced to its{" "}
            <span style={{ color: "var(--n-accent)" }}>filing</span>
          </h1>
          <p className="mx-auto mb-7 max-w-[52ch] text-[16px] leading-[1.6]" style={{ color: "var(--n-ink-2)" }}>
            {data.name} — pipeline, financials and protection, drawn from SEC
            filings and ClinicalTrials.gov, with the passage behind each claim
            one click away.
          </p>
          <div className="flex justify-center gap-3">
            <span className="rounded-full bg-[var(--n-ink)] px-6 py-3 text-[15px] font-medium text-white">
              Ask a question
            </span>
            <span className="rounded-full border bg-white px-6 py-3 text-[15px] font-medium" style={{ borderColor: "var(--n-line)" }}>
              Browse companies
            </span>
          </div>
        </div>

        {/* stat tiles */}
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {stats.map((s) => (
            <div key={s.label} className={`${card} p-5`} style={{ borderColor: "var(--n-line)" }}>
              <div
                className="mb-3 flex h-9 w-9 items-center justify-center rounded-[10px]"
                style={{ background: "var(--n-accent-soft)", color: "var(--n-accent-deep)" }}
              >
                <span className="text-[15px]">◆</span>
              </div>
              <div className="text-[26px] font-semibold tracking-[-0.02em]">{s.n}</div>
              <div className="mt-[2px] text-[13px]" style={{ color: "var(--n-ink-2)" }}>
                {s.label}
              </div>
              <div className="mt-2 text-[12px]" style={{ color: "var(--n-accent-deep)" }}>
                {s.delta}
              </div>
            </div>
          ))}
        </div>

        {/* monitor table */}
        <div className={`${card} mb-6 overflow-hidden`} style={{ borderColor: "var(--n-line)" }}>
          <div className="flex items-center justify-between px-6 py-[18px]">
            <h2 className="text-[17px] font-medium">Approved products</h2>
            <span className="rounded-full border px-3 py-1 text-[12px]" style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}>
              Orange Book
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-t text-[14px]" style={{ borderColor: "var(--n-line)" }}>
              <thead>
                <tr style={{ color: "var(--n-ink-2)" }}>
                  {["Product", "Ingredient", "Status", "Approved", "Applications"].map((h) => (
                    <th key={h} className="border-b px-6 py-3 text-left text-[13px] font-normal" style={{ borderColor: "var(--n-line)" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(data.approved_products ?? []).slice(0, 6).map((p) => (
                  <tr key={p.trade_name ?? p.ingredient}>
                    <td className="border-b px-6 py-[14px] font-medium" style={{ borderColor: "var(--n-line)" }}>
                      {p.trade_name}
                    </td>
                    <td className="border-b px-6 py-[14px]" style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}>
                      <span
                        className="rounded-full px-[10px] py-1 text-[12.5px]"
                        style={{ background: "var(--n-accent-soft)", color: "var(--n-accent-deep)" }}
                      >
                        {(p.ingredient ?? "").split(";")[0]}
                      </span>
                    </td>
                    <td className="border-b px-6 py-[14px]" style={{ borderColor: "var(--n-line)" }}>
                      <span className="inline-flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full" style={{ background: "var(--n-accent)" }} />
                        Marketed
                      </span>
                    </td>
                    <td className="border-b px-6 py-[14px]" style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}>
                      {p.approval_date}
                    </td>
                    <td className="border-b px-6 py-[14px]" style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}>
                      {p.applications.length}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* charts row */}
        <div className="grid gap-4 lg:grid-cols-2">
          <div className={`${card} p-6`} style={{ borderColor: "var(--n-line)" }}>
            <h2 className="mb-5 text-[17px] font-medium">Trials by phase</h2>
            <Donut slices={phases} />
          </div>

          <div className={`${card} p-6`} style={{ borderColor: "var(--n-line)" }}>
            <div className="mb-5 flex items-center justify-between">
              <h2 className="text-[17px] font-medium">Revenue</h2>
              <span className="rounded-full border px-3 py-1 text-[12px]" style={{ borderColor: "var(--n-line)", color: "var(--n-ink-2)" }}>
                Ten years
              </span>
            </div>
            {rev && (
              <div className="flex h-[190px] items-end gap-2">
                {rev.values.map((v, i) => {
                  const h = Math.max((v / Math.max(...rev.values)) * 150, 3);
                  return (
                    <div key={rev.years![i]} className="flex flex-1 flex-col items-center gap-2">
                      <span className="text-[11px]" style={{ color: "var(--n-ink-2)" }}>
                        {v.toFixed(1)}
                      </span>
                      <div
                        className="w-full rounded-t-[6px]"
                        style={{
                          height: h,
                          background: i === rev.values.length - 1 ? "var(--n-accent)" : "var(--n-accent-soft)",
                        }}
                      />
                      <span className="text-[11px]" style={{ color: "var(--n-ink-2)" }}>
                        &rsquo;{String(rev.years![i]).slice(2)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <p className="mx-auto mt-10 max-w-[70ch] text-center text-[13px] leading-[1.7]" style={{ color: "var(--n-ink-2)" }}>
          Same corpus, same figures as /companies/VRTX. What this register gives
          up is the period stamp on every number and the provenance chip — both
          would have to be reintroduced before it could carry the product&rsquo;s
          claim.
        </p>
      </div>
    </div>
  );
}
