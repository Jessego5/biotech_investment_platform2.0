"use client";

/**
 * This is choosing a company by typing rather than by already knowing its
 * ticker. Until it existed the only way into the corpus was editing the URL,
 * which left 786 of 787 issuers unreachable from the interface. Used by the
 * watchlist, and it takes an exclude list so a company already on the list is
 * not offered twice.
 */

import { useEffect, useState } from "react";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

export type PickedCompany = { ticker: string; name: string; sector?: string | null };

export function CompanyPicker({
  open,
  onOpenChange,
  onPick,
  exclude = [],
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (company: PickedCompany) => void;
  /** Tickers already on the list, so the picker does not offer them twice. */
  exclude?: string[];
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<PickedCompany[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    const id = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/companies?q=${encodeURIComponent(query)}`);
        const body = await res.json();
        setResults(body.companies ?? []);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 160);
    return () => clearTimeout(id);
  }, [query, open]);

  const offered = results.filter((c) => !exclude.includes(c.ticker));

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Add a company">
      <CommandInput
        placeholder="Search 787 companies by ticker or name…"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        {/* cmdk filters client-side by default; the search already happened
            server-side, so everything returned should be offered */}
        <CommandEmpty>
          {loading ? "Searching…" : "No company held under that name."}
        </CommandEmpty>
        <CommandGroup>
          {offered.map((c) => (
            <CommandItem
              key={c.ticker}
              value={`${c.ticker} ${c.name}`}
              onSelect={() => {
                onPick(c);
                onOpenChange(false);
                setQuery("");
              }}
            >
              <span className="w-[68px] font-mono text-[12px]">{c.ticker}</span>
              <span className="flex-1 text-[13.5px]">{c.name}</span>
              {c.sector && (
                <span className="font-mono text-[10px] text-muted-foreground">
                  {c.sector}
                </span>
              )}
            </CommandItem>
          ))}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
