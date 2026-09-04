/**
 * Says, on the page itself, that nothing here is real.
 *
 * These screens were drawn before there was a corpus, and their identifiers —
 * the accession numbers, the CIKs, the NCT numbers — are plausible in format
 * and were written from memory. The 20-F passage is written in register and is
 * not the filing. The panel showing it still says "stored verbatim · no
 * summarisation", which is true of how the fixture is displayed and false
 * about where the words came from.
 *
 * That is only safe while a reader knows. Removing the link from the front
 * page is not enough: a URL can be shared, and the chrome above reports the
 * real corpus size, so the page reads as live unless it says otherwise.
 */
export function FixtureNotice({ what }: { what: string }) {
  return (
    <div
      className="border-b px-6 py-3 text-[13px] leading-[1.5]"
      style={{
        borderColor: "var(--warn)",
        background: "color-mix(in srgb, var(--warn) 7%, transparent)",
        color: "var(--warn)",
      }}
    >
      <strong className="font-medium">Invented data.</strong> {what} The
      identifiers are plausible in format but were written from memory, and the
      filing text was composed to read like a filing. Nothing here came from
      SEC EDGAR. The live product is at <a href="/browse" className="underline">/browse</a>.
    </div>
  );
}
