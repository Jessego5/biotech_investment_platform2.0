/**
 * This decides whether the pages built from invented data are reachable. They
 * render the real chrome over identifiers and passage text written for the
 * canvas, and the passage panel on them still says the text is stored verbatim,
 * which is true of the live pages and false of these. A banner says so, but a
 * banner is a weaker statement than the page not existing, and a search result
 * snippet does not carry one. They are the reference the live screens are
 * checked against, so they stay in development and 404 in production. Set
 * SHOW_FIXTURES=1 to serve them anywhere.
 */
export function fixturesVisible(): boolean {
  if (process.env.SHOW_FIXTURES === "1") return true;
  return process.env.NODE_ENV !== "production";
}
