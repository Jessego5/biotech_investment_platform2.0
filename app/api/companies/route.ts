/**
 * This is the universe, searchable by ticker or name, which is what the company
 * picker reads. It proxies to the Python service so the backend URL and key stay
 * server-side.
 */

import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

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
      { error: `Could not reach the BioBase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
