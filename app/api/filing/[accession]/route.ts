import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ accession: string }> },
) {
  const p = await params;
  try {
    const upstream = await fetch(
      `${API_BASE}/filing/${encodeURIComponent(p.accession)}`,
      { cache: "no-store" },
    );
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  } catch {
    return NextResponse.json(
      { error: `Could not reach the Readbase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
