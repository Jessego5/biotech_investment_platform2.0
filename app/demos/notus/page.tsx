/**
 * This is the Notus register applied to a real company, and it is the demo the
 * product was eventually built from. White ground, grotesque sans, pill actions,
 * green as the primary and the five-step palette carrying anything ordered.
 */

import { notFound } from "next/navigation";
import { fixturesVisible } from "@/lib/readbase/fixtures";
import { API_BASE } from "@/lib/readbase/api";
import { NOTUS, notusCard } from "@/lib/readbase/notus-theme";
import {
  money,
  phaseLabel,
  phaseLevel,
  toSeries,
  type CompanyResponse,
} from "@/lib/readbase/company";

// Rendered per request, not at build. Prerendering would bake the decision into
// the build output, and SHOW_FIXTURES would then be a flag that cannot turn
// anything on in the deployment it exists for.
export const dynamic = "force-dynamic";


/**
 * The Notus register on a white ground, with green as the primary colour and
 * the five-step palette carrying the ordinal scale.
 *
 * The two are deliberately not the same colour. Green is the brand: actions,
 * links, provenance. The ramp is a measurement, pale for the earliest phase,
 * navy for approval, and it appears only where something is genuinely ordered.
 * Pale green to mint is 1.19:1, near identical to the eye, so the bars encode
 * phase in length as well and nobody has to order them by hue.
 *
 * rather than an accent on a black interface: it takes the main button, the
 * headline emphasis, the phase ramp and every active mark.
 *
 * Page and cards are both white, so the border carries the separation and is
 * a little stronger than it would need to be over a grey page.
 *
 * This deliberately breaks four of the brief's non-negotiables, sans rather
 * than serif, generous radii rather than near-sharp corners, shadows rather
 * than rules, and colour used as decoration. It is a comparison of design
 * languages, not an adjustment of one, so its tokens are declared here and
 * kept out of the product palette.
 *
 * The data is the live corpus, so the two registers can be judged on the same
 * figures rather than on lorem.
 */
const card = notusCard;

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
  const shades = ["var(--p5)", "var(--p4)", "var(--p3)", "var(--p2)", "var(--p1)"];
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
  if (!fixturesVisible()) notFound();

  const data = await load("VRTX");
  if (!data?.ticker) {
    return <div className="p-10">The API is not reachable.</div>;
  }

  const rd = toSeries("R&D", data.financial_history?.rd_expense);
  const rev = toSeries("Revenue", data.financial_history?.revenue);
  // Keep the registry's own phase string alongside the label. The level must
  // come from that, not from the label: phaseLevel promises the furthest phase
  // in a combined string, and "Phase 2/3" read back as a label gives 2, which
  // would draw a Phase 2/3 trial at the Phase 2 step and understate it.
  const phases = Object.values(
    Object.entries(data.pipeline?.by_phase ?? {}).reduce<
      Record<string, { label: string; n: number; level: number | null }>
    >((acc, [raw, n]) => {
      const label = phaseLabel(raw);
      const existing = acc[label];
      acc[label] = {
        label,
        n: (existing?.n ?? 0) + n,
        level: existing?.level ?? phaseLevel(raw),
      };
      return acc;
    }, {}),
  )
    .filter((p) => p.n > 0)
    .sort((a, b) => b.n - a.n);

  /**
   * The tiles are coloured by where the figure came from, not decoratively.
   * Four figures, four different systems, and this register had no other
   * place to say so, which was its weakest point against the canvas.
   *
   * Glyph colour follows contrast rather than taste: navy reads on the three
   * light steps (11.3:1, 9.5:1, 5.7:1) and white on the two dark ones
   * (9.6:1, 15.1:1).
   */
  const stats = [
    {
      n: String(data.pipeline?.total_trials ?? 0),
      label: "Registered trials",
      note: `${phases[0]?.n ?? 0} in ${phases[0]?.label ?? "–"}`,
      source: "ClinicalTrials.gov",
      chip: "var(--p1)",
      glyph: "#020887",
    },
    {
      n: String((data.approved_products ?? []).length),
      label: "Approved products",
      note: data.protection?.state ?? "–",
      source: "FDA Orange Book",
      chip: "var(--p2)",
      glyph: "#020887",
    },
    {
      n: rd ? money(rd.values[rd.values.length - 1] * 1e9) : "–",
      label: "Research and development",
      note: rd ? `FY${rd.years![rd.years!.length - 1]}` : "–",
      source: "SEC XBRL company facts",
      chip: "var(--p3)",
      glyph: "#020887",
    },
    {
      n: String((data.filings ?? []).length),
      label: "Annual reports held",
      note: (data.filings ?? []).length
        ? `FY${data.filings[data.filings.length - 1].fiscal_year}–FY${data.filings[0].fiscal_year}`
        : "–",
      source: "SEC EDGAR",
      chip: "var(--p4)",
      glyph: "#ffffff",
    },
  ];

  return (
    <div
      style={{ ...NOTUS, background: "var(--n-bg)", color: "var(--n-ink)", fontFamily: "var(--n-sans)" }}
      className="notus min-h-svh"
    >
      {/* header */}
      <div className="border-b bg-[var(--n-card)]" style={{ borderColor: "var(--n-line)" }}>
        <div className="mx-auto flex max-w-[1180px] items-center gap-8 px-8 py-4">
          <span className="text-[19px] font-semibold tracking-[-0.02em]">BioBase</span>
          <nav className="hidden gap-7 text-[14px] md:flex" style={{ color: "var(--n-ink-2)" }}>
            {["Companies", "Ask", "Filings", "Trials"].map((x) => (
              <span key={x}>{x}</span>
            ))}
          </nav>
          <div className="flex-1" />
          <span className="rounded-full px-[18px] py-[9px] text-[14px] font-medium text-white" style={{ background: "var(--n-accent-deep)" }}>
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
            {data.name}: pipeline, financials and protection, drawn from SEC
            filings and ClinicalTrials.gov, with the passage behind each claim
            one click away.
          </p>
          <div className="flex justify-center gap-3">
            <span className="rounded-full px-6 py-3 text-[15px] font-medium text-white" style={{ background: "var(--n-accent-deep)" }}>
              Ask a question
            </span>
            <span className="rounded-full border bg-white px-6 py-3 text-[15px] font-medium" style={{ borderColor: "var(--n-accent)", color: "var(--n-accent-deep)" }}>
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
                style={{ background: s.chip, color: s.glyph }}
              >
                <span className="text-[15px]">◆</span>
              </div>
              <div className="text-[26px] font-semibold tracking-[-0.02em]">{s.n}</div>
              <div className="mt-[2px] text-[13px]" style={{ color: "var(--n-ink-2)" }}>
                {s.label}
              </div>
              {/* the period the figure covers, and the system it came from,
                  the two things this register had nowhere to put */}
              <div className="mt-3 border-t pt-2" style={{ borderColor: "var(--n-line)" }}>
                <div className="font-mono text-[10.5px]" style={{ color: "var(--n-ink)" }}>
                  {s.note}
                </div>
                <div className="mt-[2px] font-mono text-[10px]" style={{ color: "var(--n-ink-2)" }}>
                  {s.source}
                </div>
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

        {/* the ramp, where the ordering is the point */}
        <div className={`${card} mb-6 p-6`} style={{ borderColor: "var(--n-line)" }}>
          <div className="mb-1 flex items-baseline justify-between">
            <h2 className="text-[17px] font-medium">Pipeline by phase</h2>
            <span className="font-mono text-[11px]" style={{ color: "var(--n-ink-2)" }}>
              as of today · ClinicalTrials.gov
            </span>
          </div>
          <p className="mb-5 text-[13px]" style={{ color: "var(--n-ink-2)" }}>
            The step is the phase itself, pale at Phase 1 and indigo at Phase 4,
            and length carries it too, so the two palest steps never have to be
            told apart by hue alone. Navy is held back for approval, which is
            not a phase. A trial whose phase the registry never stated sits off
            the scale in grey rather than being placed on it.
          </p>
          <div className="space-y-[10px]">
            {phases.map((p) => (
              <div key={p.label} className="flex items-center gap-4">
                <span className="w-[92px] text-[13px]" style={{ color: "var(--n-ink-2)" }}>
                  {p.label}
                </span>
                <span className="h-[10px] flex-1 overflow-hidden rounded-full" style={{ background: "#f1f4f2" }}>
                  <span
                    className="block h-full rounded-full"
                    style={{
                      width: `${(p.n / Math.max(...phases.map((x) => x.n))) * 100}%`,
                      // the step comes from the phase, not from the row's rank
                      // by count, an earlier version coloured by position and
                      // gave Phase 1 navy and Phase 4 mint, which inverted the
                      // one thing the ramp exists to say
                      background: p.level ? `var(--p${p.level})` : "#c7d0cb",
                    }}
                  />
                </span>
                <span className="w-[38px] text-right font-mono text-[13px]">{p.n}</span>
              </div>
            ))}
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
          Green is the brand and the five-step palette is the measurement. They
          are kept apart on purpose, so a colour never means two things. Same
          corpus and figures as /companies/VRTX. What this register gives
          up is the period stamp on every number and the provenance chip, both
          would have to be reintroduced before it could carry the product&rsquo;s
          claim.
        </p>
      </div>
    </div>
  );
}
