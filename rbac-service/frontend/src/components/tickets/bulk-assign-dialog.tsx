"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const AGENT_OPTIONS = [
  "Priya Sharma",
  "Daniel Cho",
  "Maria Gomez",
  "James Walker",
  "Fatima Noor",
  "Liam O'Connor",
  "Aiko Tanaka",
  "Noah Bennett",
];

interface BulkAssignDialogProps {
  open: boolean;
  count: number;
  onOpenChange: (open: boolean) => void;
  onAssign: (agent: string) => void;
}

export function BulkAssignDialog({ open, count, onOpenChange, onAssign }: BulkAssignDialogProps) {
  const [agent, setAgent] = useState("");

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setAgent("");
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Bulk Assign Tickets</DialogTitle>
        </DialogHeader>

        <div className="space-y-2">
          <Label>Assign {count} selected ticket{count === 1 ? "" : "s"} to</Label>
          <Select value={agent} onValueChange={setAgent}>
            <SelectTrigger>
              <SelectValue placeholder="Select agent" />
            </SelectTrigger>
            <SelectContent>
              {AGENT_OPTIONS.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!agent}
            onClick={() => {
              onAssign(agent);
              setAgent("");
            }}
          >
            Assign
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
