import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto max-w-2xl px-12 py-20">
      <h1 className="font-mono text-[15px] uppercase tracking-[0.34em]">
        Readbase · RDB
      </h1>
      <p className="mt-4 max-w-[62ch] text-[16.5px] leading-relaxed text-ink-2">
        Grounded question answering over biotech&rsquo;s primary sources.
      </p>
      <Link
        href="/companies/moderna"
        className="mt-8 inline-block font-mono text-[11px] tracking-[0.05em] text-accent-deep underline underline-offset-4"
      >
        Moderna, Inc. &mdash; company page
      </Link>
    </main>
  );
}
