import type { Metadata } from "next";
import "./globals.css";
import "./effects.css";

// No webfont is loaded. The two families — serif for prose, mono for figures —
// are system stacks declared in globals.css under @theme inline. Adding
// next/font here would introduce a third typeface.

export const metadata: Metadata = {
  title: "BioBase",
  description:
    "Grounded question answering over biotech's primary sources: SEC filings, ClinicalTrials.gov and FDA data.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
