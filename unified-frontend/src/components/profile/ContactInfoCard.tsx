"use client";

import { Contact } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ContactInfoCardProps {
  email: string | undefined;
  alternateEmail: string;
  phone: string;
  officeLocation: string;
  onEdit: () => void;
}

export function ContactInfoCard({
  email,
  alternateEmail,
  phone,
  officeLocation,
  onEdit,
}: ContactInfoCardProps) {
  const fields = [
    { label: "Email", value: email || "—" },
    { label: "Alternate Email", value: alternateEmail || "Not set" },
    { label: "Phone", value: phone || "Not set" },
    { label: "Office Location", value: officeLocation || "Not set" },
  ];

  return (
    <Card className="rounded-md border-border shadow-sm">
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Contact className="h-4 w-4" />
          Contact Information
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={onEdit}>
          Edit
        </Button>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2">
          {fields.map((field) => (
            <div key={field.label}>
              <dt className="text-sm text-muted-foreground">{field.label}</dt>
              <dd className="mt-0.5 text-sm font-medium">{field.value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
