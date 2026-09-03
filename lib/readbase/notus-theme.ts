/**
 * The Notus register: white ground, grotesque sans, pill actions, rounded
 * cards with a soft shadow, green as the primary and the five-step palette
 * carrying anything ordered.
 *
 * Held in one place because it is now on more than one screen, and a register
 * copied into each of them drifts apart a shade at a time.
 *
 * These are deliberately not the product palette in globals.css. That one is
 * the canvas: serif, near-sharp, rules rather than shadows, colour that never
 * decorates. This is the alternative being tried against it, and the two
 * should not quietly blend.
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
  // carry type — the light three fail contrast on white and are fills.
  "--p1": "#c8e8be",
  "--p2": "#a9d8b8",
  "--p3": "#7ca5b8",
  "--p4": "#3b369a",
  "--p5": "#020887",
  "--n-sans":
    'ui-sans-serif, system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif',
} as React.CSSProperties;

/** A card in this register. Border and a shadow soft enough to read as depth. */
export const notusCard =
  "rounded-[14px] border bg-[var(--n-card)] shadow-[0_1px_2px_rgba(16,24,40,0.04),0_1px_3px_rgba(16,24,40,0.06)]";

/** The page shell: the tokens, the ground and the face. */
export const notusPage = {
  ...NOTUS,
  background: "var(--n-bg)",
  color: "var(--n-ink)",
  fontFamily: "var(--n-sans)",
} as React.CSSProperties;
