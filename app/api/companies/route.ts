import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

/** The universe, searchable by ticker or name — what the picker reads. */
export async function GET(request: Request) {
  const q = new URL(request.url).searchParams.get("q") ?? "";
  const params = new URLSearchParams({ limit: "12" });
  if (q.trim()) params.set("q", q.trim());

  try {
    const upstream = await fetch(`${API_BASE}/companies?${params}`, {
      cache: "no-store",
    });
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { error: `Could not reach the Readbase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
