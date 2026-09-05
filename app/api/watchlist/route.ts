import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

/**
 * A row per watched company. The list itself is not stored here — there are no
 * accounts, so a server-side watchlist would be one list shared by everyone.
 * It lives in the reader's browser and arrives as a query parameter.
 */
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
