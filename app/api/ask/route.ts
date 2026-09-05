import { NextResponse } from "next/server";
import { API_BASE, apiHeaders } from "@/lib/readbase/api";

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
      headers: { "Content-Type": "application/json", ...apiHeaders() },
      body: JSON.stringify({ question }),
      cache: "no-store",
    });
    const body = await upstream.json();
    if (upstream.status === 401) {
      // the guard turned us away: say so plainly rather than passing a bare
      // 401 to a page that will read it as "no answer"
      return NextResponse.json(
        { error: "The API rejected this server's key. Check READBASE_API_KEY." },
        { status: 502 },
      );
    }
    return NextResponse.json(body, { status: upstream.status });
  } catch {
    // Say which service is unreachable rather than failing as a bare 500.
    return NextResponse.json(
      { error: `Could not reach the BioBase API at ${API_BASE}.` },
      { status: 502 },
    );
  }
}
