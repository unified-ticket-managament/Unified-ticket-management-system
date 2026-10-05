"use client";

import { Check, ChevronDown, PenLine } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ComposerSignatureOption } from "@tw/lib/signatures";

interface SignatureSelectorProps {
  options: ComposerSignatureOption[];
  // The signature in THIS email's body (null = none) — not the user's
  // permanent default, which is only marked with a "Default" tag here.
  selectedId: string | null;
  hasSavedSignatures: boolean;
  onSelect: (signatureId: string | null) => void;
  disabled?: boolean;
}

// Compact, Outlook-style "Signature ▾" picker shared by every composer
// (Compose, Forward, Reply, Reply All, Ticket Reply). Choosing an entry
// only swaps the signature block in the current email — see
// useComposerSignature; the permanent default is changed only from
// Profile → Settings → Email Signatures.
export function SignatureSelector({
  options,
  selectedId,
  hasSavedSignatures,
  onSelect,
  disabled = false,
}: SignatureSelectorProps) {
  const selected = selectedId ? options.find((o) => o.id === selectedId) : null;
  const label = selected ? selected.name : selectedId ? "Current signature" : "None";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="h-7 max-w-[16rem] gap-1.5 px-2 text-xs text-muted-foreground"
          aria-label="Choose signature"
        >
          <PenLine className="h-3.5 w-3.5 flex-none" />
          <span className="flex-none">Signature:</span>
          <span className="truncate font-medium text-foreground">{label}</span>
          <ChevronDown className="h-3 w-3 flex-none" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        {!hasSavedSignatures && (
          <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
            No saved signatures — add them in Profile → Settings.
          </DropdownMenuLabel>
        )}
        {options.map((option) => (
          <DropdownMenuItem
            key={option.id}
            onSelect={() => onSelect(option.id)}
            className="gap-2 text-xs"
          >
            <Check
              className={option.id === selectedId ? "h-3.5 w-3.5 flex-none" : "h-3.5 w-3.5 flex-none opacity-0"}
            />
            <span className="min-w-0 flex-1 truncate">{option.name}</span>
            {option.isDefault && !option.isFallback && (
              <span className="flex-none rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                Default
              </span>
            )}
          </DropdownMenuItem>
        ))}
        {(options.length > 0 || selectedId) && <DropdownMenuSeparator />}
        <DropdownMenuItem onSelect={() => onSelect(null)} className="gap-2 text-xs">
          <Check className={selectedId === null ? "h-3.5 w-3.5 flex-none" : "h-3.5 w-3.5 flex-none opacity-0"} />
          No signature
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
