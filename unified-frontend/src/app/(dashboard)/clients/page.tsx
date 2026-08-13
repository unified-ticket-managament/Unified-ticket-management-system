"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Loader2, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { AccessDenied, ErrorState } from "@/components/shared/stats";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getApiErrorMessage } from "@/lib/utils";
import { ROLE_NAMES } from "@/lib/role-access";
import { useAuthStore } from "@/store/auth-store";
import { listClients, listConfiguredClientContacts } from "@tw/api/clients";

// Same three roles that manage Client creation on the Users page's
// Create User dialog (see role-access.ts's CREATABLE_ROLES_BY_ROLE) —
// this list-only page mirrors that visibility rather than introducing
// a separate access rule.
const CLIENTS_PAGE_ALLOWED_ROLES: string[] = [
  ROLE_NAMES.SUPER_ADMIN,
  ROLE_NAMES.SITE_LEAD,
  ROLE_NAMES.ACCOUNT_MANAGER,
];

function ClientContactsList({ clientId }: { clientId: string }) {
  const contactsQuery = useQuery({
    queryKey: ["client-contacts-configured", clientId],
    queryFn: () => listConfiguredClientContacts(clientId),
  });

  if (contactsQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading contacts...
      </div>
    );
  }

  if (contactsQuery.isError) {
    return (
      <p className="text-sm text-destructive">
        {getApiErrorMessage(contactsQuery.error, "Failed to load contact emails.")}
      </p>
    );
  }

  const contacts = contactsQuery.data ?? [];

  if (contacts.length === 0) {
    return <p className="text-sm text-muted-foreground">No contact emails on file.</p>;
  }

  return (
    <ul className="space-y-1">
      {contacts.map((contact) => (
        <li key={contact.email} className="text-sm text-muted-foreground">
          • {contact.email}
        </li>
      ))}
    </ul>
  );
}

export default function ClientsPage() {
  const currentUser = useAuthStore((s) => s.user);
  const [expandedClientId, setExpandedClientId] = useState<string | null>(null);

  const clientsQuery = useQuery({
    queryKey: ["clients-list"],
    queryFn: () => listClients(),
  });

  if (currentUser && !CLIENTS_PAGE_ALLOWED_ROLES.includes(currentUser.role)) {
    return <AccessDenied message="You do not have access to the Clients page." />;
  }

  if (clientsQuery.isError) {
    return (
      <ErrorState
        message={getApiErrorMessage(clientsQuery.error, "Failed to load clients. Please try again.")}
      />
    );
  }

  const clients = clientsQuery.data ?? [];

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Clients" }]} />

      <PageHeader
        title="Clients"
        description={`External client organizations, sourced from the clients table${
          clientsQuery.data ? ` — ${clients.length} total` : ""
        }.`}
        action={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={() => clientsQuery.refetch()}
              disabled={clientsQuery.isFetching}
              aria-label="Refresh"
              title="Refresh"
            >
              <RefreshCw className={`h-4 w-4 ${clientsQuery.isFetching ? "animate-spin" : ""}`} />
            </Button>
            <Button variant="outline" className="gap-2" asChild>
              <Link href="/users">
                <Plus className="h-4 w-4" />
                Create Client
              </Link>
            </Button>
          </div>
        }
      />

      <Card>
        <CardContent className="p-0">
          {clientsQuery.isLoading ? (
            <div className="flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading clients...
            </div>
          ) : clients.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              No clients found. Create one from the Users page with Role set to Client.
            </div>
          ) : (
            <div className="divide-y divide-border">
              {clients.map((client) => {
                const isExpanded = expandedClientId === client.client_id;
                return (
                  <div key={client.client_id}>
                    <button
                      type="button"
                      className="flex w-full items-center justify-between gap-3 p-4 text-left transition-colors hover:bg-muted/50"
                      onClick={() =>
                        setExpandedClientId(isExpanded ? null : client.client_id)
                      }
                    >
                      <div className="flex items-center gap-2">
                        {isExpanded ? (
                          <ChevronDown className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-muted-foreground" />
                        )}
                        <span className="font-medium">{client.name}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-sm text-muted-foreground">
                          {client.inbox_email ?? "No organization email"}
                        </span>
                        <Badge variant={client.is_active ? "success" : "destructive"}>
                          {client.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </div>
                    </button>

                    {isExpanded && (
                      <div className="space-y-3 border-t border-border bg-muted/30 p-4 pl-11">
                        <div>
                          <p className="text-xs font-medium text-muted-foreground">
                            Organization Email
                          </p>
                          <p className="text-sm">{client.inbox_email ?? "—"}</p>
                        </div>
                        <div>
                          <p className="text-xs font-medium text-muted-foreground">
                            Account Manager
                          </p>
                          <p className="text-sm">
                            {client.account_manager_name ?? "Unassigned"}
                            {!client.account_manager_active && (
                              <span className="ml-2 text-xs text-destructive">
                                (no longer an active Account Manager)
                              </span>
                            )}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs font-medium text-muted-foreground">
                            Contact Emails
                          </p>
                          <ClientContactsList clientId={client.client_id} />
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
