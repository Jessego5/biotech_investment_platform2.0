/**
 * This returns everything the company page shows for one issuer, proxied to the
 * Python service so the backend URL and key stay server-side.
 */

import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ ticker: string }> },
) {
  const { ticker } = await params;
  if (!/^[A-Za-z.\-]{1,10}$/.test(ticker)) {
    return NextResponse.json({ error: "Not a ticker." }, { status: 400 });
  }
  try {
    const upstream = await fetch(`${API_BASE}/company/${ticker.toUpperCase()}`, {
      cache: "no-store",
    });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { error: `Could not reach the BioBase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
