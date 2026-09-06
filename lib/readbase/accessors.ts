/**
 * This pairs the accessors that ran with the evidence blocks they produced. The
 * service reports the calls in `tools_used` and the blocks in `evidence`, and
 * nothing joins them: the same accessor can run twice, and a call that matched
 * nothing produces no block at all. Both the steps above an answer and the
 * refusal card below one need that join, so it is here rather than written
 * twice and drifting.
 */

import type { EvidenceBlock } from "@/lib/readbase/api";
import type { AccessorResult } from "@/lib/readbase/types";

/** One accessor call, and the block it produced if it produced one. */
export type AccessorStep = { tool: string; block?: EvidenceBlock };

/**
 * These two end the conversation rather than retrieving anything, so they are
 * not lookups and counting them as lookups overstates what was tried. See
 * chat.py, where both return before a tool is run.
 */
const CONTROL_TOOLS = new Set(["greeting", "decline"]);

/**
 * The calls in the order they were made, each matched to the first block it
 * produced. A block is claimed once and not offered to the next call of the
 * same name, so two searches show as two rows rather than sharing one.
 */
export function pairAccessors(
  tools: string[],
  evidence: EvidenceBlock[],
): AccessorStep[] {
  const claimed = new Set<number>();
  return tools
    .filter((tool) => !CONTROL_TOOLS.has(tool))
    .map((tool) => {
      const index = evidence.findIndex((e, i) => e.tool === tool && !claimed.has(i));
      if (index === -1) return { tool };
      claimed.add(index);
      return { tool, block: evidence[index] };
    });
}

/**
 * The same steps as the rows a refusal card lists under "what was queried".
 *
 * The third column names the block rather than a row count, because the service
 * does not report one: it returns the retrieved text, not how many rows went
 * into it. A count written here would be a number nothing behind it produced,
 * which is the one thing this product must not do.
 */
export function accessorResults(
  tools: string[],
  evidence: EvidenceBlock[],
): AccessorResult[] {
  return pairAccessors(tools, evidence).map(({ tool, block }) => ({
    accessor: tool,
    returned: block ? `${block.label} · ${block.source}` : "ran and matched nothing",
    rows: block ? `block ${block.n}` : "no rows",
  }));
}
