import type { LucideIcon } from "lucide-react";
import { notusCard } from "@/lib/readbase/notus-theme";

export type Tile = {
  /** What the figure is of — a flask for trials, a page for filings. The chip
   *  says which source it came from; the icon says what was counted, so the
   *  two carry different halves of the same sentence. */
  icon: LucideIcon;
  n: string;
  label: string;
  /** The span the figure covers. Never optional — a figure without one cannot be checked. */
  note: string;
  /** The system it came from, which is what the chip colour keys to. */
  source: string;
  chip: string;
  glyph: string;
};

/**
 * The figures a reader wants first, each carrying the period it covers and the
 * system behind it. The chip colour is the source, not decoration — four
 * figures here come from four different places and the colour says which.
 */
export function StatTiles({ tiles }: { tiles: Tile[] }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className={`${notusCard} p-5`} style={{ borderColor: "var(--n-line)" }}>
          <div
            className="mb-3 flex h-9 w-9 items-center justify-center rounded-[10px]"
            style={{ background: t.chip, color: t.glyph }}
          >
            <t.icon size={17} strokeWidth={2} aria-hidden />
          </div>
          <div className="text-[26px] font-semibold tabular-nums tracking-[-0.02em]">{t.n}</div>
          <div className="mt-[2px] text-[13px]" style={{ color: "var(--n-ink-2)" }}>
            {t.label}
          </div>
          <div className="mt-3 border-t pt-2" style={{ borderColor: "var(--n-line)" }}>
            <div className="text-[11px] tabular-nums" style={{ color: "var(--n-ink)" }}>
              {t.note}
            </div>
            <div className="mt-[2px] text-[10.5px]" style={{ color: "var(--n-ink-2)" }}>
              {t.source}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** The donut, in the ordinal ramp, darkest first. */
export function PhaseDonut({ slices }: { slices: { label: string; n: number }[] }) {
  const total = slices.reduce((a, s) => a + s.n, 0) || 1;
  const shades = ["var(--p5)", "var(--p4)", "var(--p3)", "var(--p2)", "var(--p1)"];
  const C = 2 * Math.PI * 54;
  const arcs = slices.reduce<{ label: string; len: number; at: number }[]>((acc, s) => {
    const prev = acc[acc.length - 1];
    return [...acc, { label: s.label, len: (s.n / total) * C, at: prev ? prev.at + prev.len : 0 }];
  }, []);

  return (
    <div className="flex flex-wrap items-center gap-7">
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
            <span className="h-[9px] w-[18px] rounded-full" style={{ background: shades[i % shades.length] }} />
            <span style={{ color: "var(--n-ink-2)" }}>{s.label}</span>
            <span className="font-medium tabular-nums">{s.n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
