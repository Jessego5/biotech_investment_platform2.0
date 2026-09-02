import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

/** The exact stored passage behind a citation. */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) {
    return NextResponse.json({ error: "Not a chunk id." }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${API_BASE}/source/chunk/${id}`, {
      cache: "no-store",
    });
    const body = await upstream.json();
    return NextResponse.json(body, { status: upstream.status });
  } catch {
    return NextResponse.json(
      { error: `Could not reach the Readbase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
