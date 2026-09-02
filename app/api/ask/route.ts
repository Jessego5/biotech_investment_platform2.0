import { NextResponse } from "next/server";
import { API_BASE } from "@/lib/readbase/api";

/**
 * Proxies the question to the Python service.
 *
 * The browser talks to its own origin so there is no CORS dance and no API
 * host baked into the client bundle — the backend URL stays server-side.
 */
export async function POST(request: Request) {
  let question = "";
  try {
    ({ question } = await request.json());
  } catch {
    return NextResponse.json({ error: "Expected a JSON body." }, { status: 400 });
  }

  if (!question?.trim()) {
    return NextResponse.json({ error: "Please ask a question." }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${API_BASE}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      cache: "no-store",
    });
    const body = await upstream.json();
    return NextResponse.json(body, { status: upstream.status });
  } catch {
    // Say which service is unreachable rather than failing as a bare 500.
    return NextResponse.json(
      { error: `Could not reach the Readbase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
