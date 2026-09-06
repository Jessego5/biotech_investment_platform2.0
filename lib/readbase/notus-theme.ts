/**
 * This is the Notus register: white ground, grotesque sans, pill actions,
 * rounded cards with a soft shadow, green as the primary and the five-step
 * palette carrying anything ordered. It is held in one place because it is on
 * more than one screen and a register copied into each of them drifts apart a
 * shade at a time. These are deliberately not the product palette in
 * globals.css, which is the canvas: serif, near-sharp, rules rather than
 * shadows, colour that never decorates. Spread notusPage on a page wrapper to
 * remap the product tokens, add the notus class for the typeface rules in
 * effects.css, and use notusCard for a card.
 */
export const NOTUS = {
  // page and cards are both white, so the border does the separating
  "--n-bg": "#ffffff",
  "--n-card": "#ffffff",
  "--n-ink": "#14251f",
  "--n-ink-2": "#68736e",
  "--n-line": "#dbe3df",
  // green is the primary: the main action, the emphasis, every active mark
  "--n-accent": "#1d9e75",
  "--n-accent-soft": "#e1f5ee",
  "--n-accent-deep": "#0f6e56",
  // the five, in order, for anything genuinely ordered. Only the last two
  // carry type, the light three fail contrast on white and are fills.
  "--p1": "#c8e8be",
  "--p2": "#a9d8b8",
  "--p3": "#7ca5b8",
  "--p4": "#3b369a",
  "--p5": "#020887",
  "--n-sans":
    'ui-sans-serif, system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif',
} as React.CSSProperties;



/**
 * One face everywhere.
 *
 * `--font-mono` is remapped to the same stack, so a component asking for mono
 * gets the sans and the register has a single typeface differing only in size
 * and colour. Nothing had to be rewritten to do it.
 *
 * The one thing mono was carrying is kept: globals.css sets
 * font-variant-numeric: tabular-nums on .font-mono, so figures in a column
 * still line up digit under digit. That was the practical reason for a
 * monospace face in a table of numbers, and it survives without it.
 */
export const notusFonts = {
  "--font-mono": "var(--n-sans)",
  "--font-serif": "var(--n-sans)",
  "--font-sans": "var(--n-sans)",
} as React.CSSProperties;

/** A card in this register. Border and a shadow soft enough to read as depth. */
export const notusCard =
  "rounded-[14px] border bg-[var(--n-card)] shadow-[0_1px_2px_rgba(16,24,40,0.04),0_1px_3px_rgba(16,24,40,0.06)]";

/**
 * The page shell.
 *
 * As well as its own tokens it remaps the product's, so a component written
 * against `border-border` or `text-muted-foreground` renders in this register
 * without being rewritten. That keeps one implementation of each screen rather
 * than a Notus copy drifting away from a canvas original, and it means
 * switching a page between registers is a change of wrapper, not a rewrite.
 *
 * Only the surface tokens are remapped. The citation chip is not: it means
 * provenance in either register and does not become a green pill because the
 * page around it changed.
 */
export const notusPage = {
  ...NOTUS,
  ...notusFonts,
  background: "var(--n-bg)",
  color: "var(--n-ink)",
  fontFamily: "var(--n-sans)",
  "--background": "#ffffff",
  "--foreground": "#14251f",
  "--card": "#ffffff",
  "--card-foreground": "#14251f",
  "--secondary": "#f6f8f7",
  "--muted": "#f6f8f7",
  "--muted-foreground": "#68736e",
  "--border": "#dbe3df",
  "--input": "#c9d5cf",
  "--ink-2": "#68736e",
  "--line-hi": "#c9d5cf",
  "--primary": "#0f6e56",
  "--primary-foreground": "#ffffff",
  "--accent-mid": "#1d9e75",
  "--accent-deep": "#0f6e56",
  "--tint": "#e1f5ee",
  "--good": "#0f6e56",
  // the ordinal ramp, so a phase bar in this register uses the five steps
  "--phase-1": "#c8e8be",
  "--phase-2": "#a9d8b8",
  "--phase-3": "#7ca5b8",
  "--phase-4": "#3b369a",
  "--phase-na": "#dde3e0",
} as React.CSSProperties;
