"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { flushSync } from "react-dom";
import type {
  PassageSection,
  SourceLocation,
  StoredPassage,
} from "@/lib/readbase/passages";

/**
 * This owns which citation is open and how it got opened. The context shape
 * follows the approach in miurla/morphic, Apache-2.0, where a provider holds the
 * open state and the panel reads it and renders nothing when there is nothing
 * open. It is reimplemented rather than copied, because this one addresses
 * stored passages rather than tool artifacts and it tracks the chip as well as
 * the source, since one source can be cited twice and only the chip actually
 * clicked should read as open. Wrap a screen in it and read it with
 * useInspector.
 */
export type OpenCitation = {
  chipId: string;
  source: number;
  /** What to show in the panel's chip. Absent where the panel was not opened
   *  from a citation — a section opened from a filing has no citation number,
   *  and showing the chunk id there would put an internal identifier in the
   *  one mark that means provenance. */
  label?: string;
  sectionId: string;
  /** Which passage of the section is showing. The stepper moves this. */
  index: number;
};

type InspectorValue = {
  open: OpenCitation | null;
  openCitation: (chipId: string, source: number, origin?: HTMLElement, label?: string) => void;
  /** Step to another passage within the open section. */
  showPassage: (index: number) => void;
  sections: Record<string, PassageSection>;
  /** A passage whose text is still being fetched. */
  loading: boolean;
  close: () => void;
  /** Hovering a citation lights its row in the source index. No motion. */
  hovered: number | null;
  setHovered: (source: number | null) => void;
  /** The panel header's chip, the far end of the open transition. */
  registerHeaderChip: (el: HTMLElement | null) => void;
};

const InspectorContext = createContext<InspectorValue | null>(null);

const TRANSITION_NAME = "rdb-cite";

export function InspectorProvider({
  sections: fixedSections = {},
  locate = {},
  resolveSource,
  loadPassage,
  initialSource = null,
  initialChipId,
  children,
}: {
  /** Sections known up front. Supplied per screen so the panel is not bound
   *  to one dataset. */
  sections?: Record<string, PassageSection>;
  locate?: Record<number, SourceLocation>;
  /** For live data, where the section is not known until the citation is
   *  opened and has to be fetched. */
  resolveSource?: (
    source: number,
  ) => Promise<{ section: PassageSection; index: number } | null>;
  /** Fetches one passage's text when the stepper reaches it. */
  loadPassage?: (chunkId: number) => Promise<Partial<StoredPassage> | null>;
  initialSource?: number | null;
  initialChipId?: string;
  children: React.ReactNode;
}) {
  const [fetched, setFetched] = useState<Record<string, PassageSection>>({});
  const [loading, setLoading] = useState(false);
  const sections = useMemo(
    () => ({ ...fixedSections, ...fetched }),
    [fixedSections, fetched],
  );
  const [open, setOpen] = useState<OpenCitation | null>(() => {
    if (!initialSource) return null;
    const at = locate[initialSource];
    return at
      ? { chipId: initialChipId ?? `source-${initialSource}`, source: initialSource, ...at }
      : null;
  });
  const [hovered, setHovered] = useState<number | null>(null);
  const headerChip = useRef<HTMLElement | null>(null);

  const registerHeaderChip = useCallback((el: HTMLElement | null) => {
    headerChip.current = el;
  }, []);

  /**
   * Clicking a chip moves that chip into the panel header rather than making a
   * panel appear. The point is to make "this number came from that document"
   * physical, so the number is the thing that travels.
   *
   * Only ever one element carries the transition name at a time: the clicked
   * chip holds it for the old snapshot, the header chip for the new one.
   * Two elements sharing it would abort the transition.
   */
  const openCitation = useCallback(
    (chipId: string, source: number, origin?: HTMLElement, label?: string) => {
      const at = locate[source];
      if (!at) {
        // Live data: the section is not known until it is fetched, so the
        // morph has nothing to land on yet and the panel opens plainly.
        if (!resolveSource) return;
        setLoading(true);
        resolveSource(source)
          .then((found) => {
            if (!found) return;
            setFetched((all) => ({ ...all, [found.section.id]: found.section }));
            setOpen({ chipId, source, label, sectionId: found.section.id, index: found.index });
          })
          .finally(() => setLoading(false));
        return;
      }
      const next = { chipId, source, label: label ?? String(source), ...at };
      const canMorph =
        origin &&
        typeof document !== "undefined" &&
        typeof document.startViewTransition === "function" &&
        !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

      if (!canMorph) {
        setOpen(next);
        return;
      }

      origin.style.viewTransitionName = TRANSITION_NAME;
      headerChip.current?.style.removeProperty("view-transition-name");

      const transition = document.startViewTransition(() => {
        flushSync(() => setOpen(next));
        origin.style.removeProperty("view-transition-name");
        if (headerChip.current) {
          headerChip.current.style.viewTransitionName = TRANSITION_NAME;
        }
      });

      transition.finished.finally(() => {
        origin.style.removeProperty("view-transition-name");
        headerChip.current?.style.removeProperty("view-transition-name");
      });
    },
    [locate, resolveSource],
  );

  /**
   * Step within the open section. A passage whose text is not held yet is
   * fetched on arrival; one that genuinely has no stored text stays empty and
   * the panel says so.
   */
  const showPassage = useCallback(
    (index: number) => {
      setOpen((current) => (current ? { ...current, index } : current));
      if (!loadPassage) return;
      setOpen((current) => {
        if (!current) return current;
        const section = fetched[current.sectionId];
        const passage = section?.passages[index - 1];
        if (!section || !passage?.chunkId || passage.paragraphs?.length) return current;
        setLoading(true);
        loadPassage(passage.chunkId)
          .then((loaded) => {
            if (!loaded) return;
            setFetched((all) => {
              const target = all[section.id];
              if (!target) return all;
              const passages = target.passages.map((p) =>
                p.index === index ? { ...p, ...loaded } : p,
              );
              return { ...all, [section.id]: { ...target, passages } };
            });
          })
          .finally(() => setLoading(false));
        return current;
      });
    },
    [fetched, loadPassage],
  );

  const close = useCallback(() => setOpen(null), []);

  const value = useMemo(
    () => ({
      open,
      openCitation,
      showPassage,
      sections,
      loading,
      close,
      hovered,
      setHovered,
      registerHeaderChip,
    }),
    [open, openCitation, showPassage, sections, loading, close, hovered, registerHeaderChip],
  );

  return <InspectorContext.Provider value={value}>{children}</InspectorContext.Provider>;
}

export function useInspector(): InspectorValue {
  const value = useContext(InspectorContext);
  if (!value) {
    throw new Error("useInspector must be used inside an InspectorProvider");
  }
  return value;
}

/**
 * For components that appear both with and without an inspector. On the Ask
 * screen there is no passage panel, so a chip there is a marker rather than a
 * control — it should render inert instead of pretending to open something.
 */
export function useOptionalInspector(): InspectorValue | null {
  return useContext(InspectorContext);
}
