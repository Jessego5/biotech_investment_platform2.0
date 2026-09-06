"use client";

import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { PassagePanel } from "@/components/readbase/passage-panel";
import { useInspector } from "@/components/readbase/inspector-provider";
import { OriginalDocument } from "@/components/readbase/original-document";

/**
 * This is the inspector as a drawer, for screens with no room for a docked
 * panel. It is the same panel and the same two checks, and only the container
 * differs. Splitting panel from drawer this way follows the structure in
 * miurla/morphic, Apache-2.0. Used on narrow screens and on the filing pages.
 */
export function PassageSheet({ children }: { children?: React.ReactNode }) {
  const { open, close, sections } = useInspector();
  const original = open ? sections[open.sectionId]?.original : undefined;

  return (
    <Sheet open={Boolean(open)} onOpenChange={(next) => !next && close()}>
      <SheetContent
        side="right"
        className="flex w-[583px] max-w-[92vw] flex-col gap-0 bg-secondary p-0 sm:max-w-[583px]"
      >
        <SheetTitle className="sr-only">Stored passage</SheetTitle>
        <PassagePanel />
        {/* the second check travels with the first — a drawer that showed only
            what we read would drop the half that lets you disagree with it */}
        {original && <OriginalDocument record={original} />}
        {children}
      </SheetContent>
    </Sheet>
  );
}
