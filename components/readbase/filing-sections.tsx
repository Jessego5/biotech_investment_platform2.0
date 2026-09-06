"use client";

/**
 * This lists the sections stored from one annual report and opens the same
 * passage panel a citation opens, so reading a filing from the filing page and
 * reading it from an answer land on identical text. A section that was found but
 * held no passages still gets a row, because a gap in extraction is a fact about
 * the filing rather than a reason to show nothing. Rendered by
 * app/filings/[accession].
 */

import { InspectorProvider } from "@/components/readbase/inspector-provider";
import { PassageSheet } from "@/components/readbase/passage-sheet";
import { useOptionalInspector } from "@/components/readbase/inspector-provider";
import { fetchChunk, sectionFromChunk, splitPassage } from "@/lib/readbase/api";

type Section = { section: string; passages: number; first_chunk_id: number | null };

function Rows({ sections }: { sections: Section[] }) {
  const inspector = useOptionalInspector();

  return (
    <table className="w-full text-[14px]">
      <thead>
        <tr style={{ color: "var(--n-ink-2)" }}>
          {["Section", "Passages", ""].map((h, i) => (
            <th
              key={h || i}
              className="border-b pb-2 text-left text-[13px] font-normal"
              style={{ borderColor: "var(--n-line)" }}
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sections.map((s) => (
          <tr key={s.section}>
            <td className="border-b py-3" style={{ borderColor: "var(--n-line)" }}>
              {s.section.replace(/_/g, " ")}
            </td>
            <td className="border-b py-3 tabular-nums" style={{ borderColor: "var(--n-line)" }}>
              {s.passages}
            </td>
            <td className="border-b py-3 text-right" style={{ borderColor: "var(--n-line)" }}>
              {s.first_chunk_id ? (
                <button
                  type="button"
                  onClick={(e) =>
                    inspector?.openCitation(`section-${s.section}`, s.first_chunk_id!, e.currentTarget)
                  }
                  className="rounded-full border px-[12px] py-[5px] text-[12px]"
                  style={{ borderColor: "var(--n-accent)", color: "var(--n-accent-deep)" }}
                >
                  Read this section
                </button>
              ) : (
                <span className="text-[12px]" style={{ color: "var(--n-ink-2)" }}>
                  no passage stored
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * The sections of one filing, each openable.
 *
 * The chunk id is used as the source number, so the same passage panel that
 * serves a citation on the Ask screen serves a section here, including the
 * stepper, which walks the section this passage belongs to.
 */
export function FilingSections({ sections }: { sections: Section[] }) {
  return (
    <InspectorProvider
      resolveSource={async (chunkId) => {
        const chunk = await fetchChunk(chunkId);
        return chunk?.chunk_id ? sectionFromChunk(chunk) : null;
      }}
      loadPassage={async (chunkId) => {
        const chunk = await fetchChunk(chunkId);
        if (!chunk?.chunk_id) return null;
        return {
          characters: `${chunk.text.length.toLocaleString()} characters`,
          provenance: "stored verbatim · no summarisation",
          paragraphs: splitPassage(chunk.text),
        };
      }}
    >
      <Rows sections={sections} />
      <PassageSheet />
    </InspectorProvider>
  );
}
