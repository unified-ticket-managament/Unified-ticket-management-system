"use client";

import { useEffect, useState } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listClients } from "@tw/api/clients";
import type { ClientResponse } from "@tw/types";

interface ClientPickerProps {
  // Mail Rules: single choice (still stored as a 1-element array).
  // OTP Rules: true multi-select — see the spec's "Client (Multi
  // Select)" condition.
  multiple: boolean;
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}

export function ClientPicker({ multiple, selectedIds, onChange }: ClientPickerProps) {
  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [query, setQuery] = useState("");

  useEffect(() => {
    listClients().then(setClients).catch(() => setClients([]));
  }, []);

  if (!multiple) {
    return (
      <Select
        value={selectedIds[0] ?? ""}
        onValueChange={(value) => onChange(value ? [value] : [])}
      >
        <SelectTrigger>
          <SelectValue placeholder="Select a client…" />
        </SelectTrigger>
        <SelectContent>
          {clients.map((client) => (
            <SelectItem key={client.client_id} value={client.client_id}>
              {client.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  const filtered = clients.filter((c) => c.name.toLowerCase().includes(query.trim().toLowerCase()));

  function toggle(clientId: string) {
    if (selectedIds.includes(clientId)) {
      onChange(selectedIds.filter((id) => id !== clientId));
    } else {
      onChange([...selectedIds, clientId]);
    }
  }

  return (
    <div className="rounded-lg border border-border">
      <div className="border-b border-border p-2">
        <Input
          placeholder="Search clients…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="h-8"
        />
      </div>
      <div className="max-h-48 overflow-y-auto p-2">
        {filtered.length === 0 ? (
          <p className="px-1 py-2 text-xs text-muted-foreground">No matching clients.</p>
        ) : (
          filtered.map((client) => (
            <label
              key={client.client_id}
              className="flex items-center gap-2 rounded-md px-1 py-1.5 text-sm hover:bg-muted/50"
            >
              <Checkbox
                checked={selectedIds.includes(client.client_id)}
                onCheckedChange={() => toggle(client.client_id)}
              />
              {client.name}
            </label>
          ))
        )}
      </div>
    </div>
  );
}
