"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MockTicket, TicketPriority, TicketStatus } from "@/lib/mock-tickets";

const CATEGORY_OPTIONS = ["Billing", "Technical", "Account Access", "Bug Report", "Feature Request", "General Inquiry"];
const PRIORITY_OPTIONS: TicketPriority[] = ["Low", "Medium", "High", "Critical"];
const STATUS_OPTIONS: TicketStatus[] = ["Open", "In Progress", "Resolved", "Closed"];
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

const ticketSchema = z.object({
  subject: z.string().min(3, "Subject must be at least 3 characters"),
  client: z.string().min(1, "Client is required"),
  category: z.string().min(1, "Select a category"),
  priority: z.enum(["Low", "Medium", "High", "Critical"]),
  status: z.enum(["Open", "In Progress", "Resolved", "Closed"]),
  assignedTo: z.string().min(1, "Select an assignee"),
});

type TicketFormValues = z.infer<typeof ticketSchema>;

interface TicketFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreate: (
    ticket: Omit<MockTicket, "id" | "assignedBy" | "createdBy" | "createdDate" | "updatedDate" | "slaBreached" | "escalated" | "waitingMinutes">
  ) => void;
}

export function TicketFormDialog({ open, onOpenChange, onCreate }: TicketFormDialogProps) {
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors },
  } = useForm<TicketFormValues>({
    resolver: zodResolver(ticketSchema),
    defaultValues: {
      subject: "",
      client: "",
      category: "",
      priority: "Medium",
      status: "Open",
      assignedTo: "",
    },
  });

  useEffect(() => {
    if (open) reset();
  }, [open, reset]);

  const category = watch("category");
  const priority = watch("priority");
  const status = watch("status");
  const assignedTo = watch("assignedTo");

  const onSubmit = (values: TicketFormValues) => {
    onCreate(values);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create Ticket</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <div className="space-y-2">
            <Label htmlFor="subject">Subject</Label>
            <Input id="subject" placeholder="Brief summary of the issue" {...register("subject")} />
            {errors.subject && <p className="text-sm text-destructive">{errors.subject.message}</p>}
          </div>

          <div className="space-y-2">
            <Label htmlFor="client">Client</Label>
            <Input id="client" placeholder="Company or account name" {...register("client")} />
            {errors.client && <p className="text-sm text-destructive">{errors.client.message}</p>}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Category</Label>
              <Select value={category} onValueChange={(v) => setValue("category", v, { shouldValidate: true })}>
                <SelectTrigger>
                  <SelectValue placeholder="Select category" />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((c) => (
                    <SelectItem key={c} value={c}>
                      {c}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.category && <p className="text-sm text-destructive">{errors.category.message}</p>}
            </div>

            <div className="space-y-2">
              <Label>Priority</Label>
              <Select value={priority} onValueChange={(v) => setValue("priority", v as TicketPriority)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRIORITY_OPTIONS.map((p) => (
                    <SelectItem key={p} value={p}>
                      {p}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Status</Label>
              <Select value={status} onValueChange={(v) => setValue("status", v as TicketStatus)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Assigned To</Label>
              <Select value={assignedTo} onValueChange={(v) => setValue("assignedTo", v, { shouldValidate: true })}>
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
              {errors.assignedTo && <p className="text-sm text-destructive">{errors.assignedTo.message}</p>}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit">Create Ticket</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
