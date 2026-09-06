/**
 * This returns a row per watched company. The list itself is not stored here,
 * because with no accounts a server-side watchlist would be one list shared by
 * everyone; it lives in the reader's browser and arrives as a query parameter,
 * which is also what lets a list travel as a link.
 */

import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

export async function GET(request: Request) {
  const tickers = new URL(request.url).searchParams.get("tickers") ?? "";
  if (!tickers.trim()) return NextResponse.json({ companies: [] });

  try {
    const upstream = await fetch(
      `${API_BASE}/watchlist?tickers=${encodeURIComponent(tickers)}`,
      { cache: "no-store" },
    );
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { error: `Could not reach the BioBase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
