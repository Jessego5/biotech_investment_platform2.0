/**
 * This returns the exact stored passage behind a citation, which is what the
 * passage panel shows. It is the whole claim of the product reduced to one
 * route: the text the model was allowed to read, unedited.
 */

import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

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
      { error: `Could not reach the BioBase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
