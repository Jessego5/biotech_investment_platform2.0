import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

/** One index over companies, products, filings and trials. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const params = new URLSearchParams({ limit: "8" });
  const q = url.searchParams.get("q") ?? "";
  const kind = url.searchParams.get("kind");
  if (q.trim()) params.set("q", q.trim());
  if (kind) params.set("kind", kind);

  try {
    const upstream = await fetch(`${API_BASE}/search?${params}`, { cache: "no-store" });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { error: `Could not reach the BioBase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
