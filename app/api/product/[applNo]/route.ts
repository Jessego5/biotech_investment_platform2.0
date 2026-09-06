/**
 * This returns one approved product: the application, its listed patents
 * deduplicated, and whatever exclusivity is recorded against it.
 */

import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ applNo: string }> },
) {
  const p = await params;
  try {
    const upstream = await fetch(
      `${API_BASE}/product/${encodeURIComponent(p.applNo)}`,
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
