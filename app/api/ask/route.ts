/**
 * This proxies a question to the Python service. The browser talks to its own
 * origin, so there is no CORS dance and no API host in the client bundle, and
 * the key never leaves the server. It also holds the per-caller burst limit,
 * which is a fairness limit and not a defence: anyone determined enough changes
 * address and has a fresh allowance, and a browser behind a shared address
 * counts as one caller for everybody using it. What actually caps the spend is
 * the daily budget in the API, counted where the money goes and for everyone at
 * once; this only stops one script taking the day's budget before anybody else
 * arrives.
 */

import { NextResponse } from "next/server";
import { API_BASE, apiHeaders } from "@/lib/readbase/api";

const PER_MINUTE = 10;
const PER_DAY = 50;

// In the process, deliberately. The global budget is in Postgres because it has
// to survive restarts and more than one task; this does not, a burst window
// that resets on deploy costs nothing, and two web tasks giving one caller two
// windows is a rounding error against a limit that was already approximate.
const seen = new Map<string, number[]>();

function overLimit(key: string) {
  const now = Date.now();
  const times = (seen.get(key) ?? []).filter((t) => now - t < 86_400_000);
  const lastMinute = times.filter((t) => now - t < 60_000).length;
  if (lastMinute >= PER_MINUTE || times.length >= PER_DAY) {
    seen.set(key, times);
    return true;
  }
  times.push(now);
  seen.set(key, times);
  // the map only ever grows otherwise, and a long-lived task serving a lot of
  // addresses is exactly where that matters
  if (seen.size > 5000) {
    for (const [k, v] of seen) if (v.every((t) => now - t > 86_400_000)) seen.delete(k);
  }
  return false;
}

function caller(request: Request) {
  const forwarded = request.headers.get("x-forwarded-for") ?? "";
  // the LAST entry, not the first. The load balancer appends the address it
  // saw to whatever the client sent, so the leftmost value is attacker-supplied
  // and the rightmost is the one AWS observed.
  const hops = forwarded.split(",").map((h) => h.trim()).filter(Boolean);
  return hops[hops.length - 1] || "unknown";
}

/**
 * Proxies the question to the Python service.
 *
 * The browser talks to its own origin so there is no CORS dance and no API
 * host baked into the client bundle, the backend URL stays server-side.
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

  if (overLimit(caller(request))) {
    // shaped like the API's own refusal, and a 200, because being asked to
    // slow down is not the request failing, the page renders it as a state,
    // not as an error
    return NextResponse.json({
      answer:
        "That is more questions than one reader gets in a minute. Nothing is " +
        "wrong and nothing is lost. Wait a moment and ask again.\n\nThe limit " +
        "is here because answering costs money and there is one budget for " +
        "everyone. Browse, the company pages and the watchlist are unaffected.",
      sources: [],
      unavailable: true,
      budget: { throttled: true },
    });
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
        { error: "The API rejected this server's key. Check BIOBASE_API_KEY." },
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
