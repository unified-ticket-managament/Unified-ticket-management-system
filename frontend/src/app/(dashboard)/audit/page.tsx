"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/dashboard-shell";
import { EmptyState, ErrorState } from "@/components/shared/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";
import { auditService } from "@/services";

export default function AuditPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

  const auditQuery = useQuery({
    queryKey: ["audit", page, search],
    queryFn: () => auditService.list({ page, page_size: 10, search: search || undefined }),
  });

  return (
    <div>
      <PageHeader
        title="Audit Logs"
        description="Track all system actions and changes"
      />

      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="pl-10"
              placeholder="Search by action, entity type, or ID..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </CardContent>
      </Card>

      {auditQuery.isError && <ErrorState message="Failed to load audit logs" />}

      {auditQuery.isLoading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : auditQuery.data?.items.length === 0 ? (
        <EmptyState title="No audit logs" description="No activity matches your search." />
      ) : (
        <div className="space-y-3">
          {auditQuery.data?.items.map((log) => (
            <Card key={log.id}>
              <CardContent className="grid gap-4 p-4 md:grid-cols-4">
                <div>
                  <p className="text-xs text-muted-foreground">Action</p>
                  <Badge variant="secondary">{log.action}</Badge>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Entity</p>
                  <p className="text-sm font-medium">
                    {log.entity_type}
                    {log.entity_id ? ` · ${log.entity_id.slice(0, 8)}...` : ""}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Timestamp</p>
                  <p className="text-sm">{formatDate(log.timestamp)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">User ID</p>
                  <p className="text-sm">{log.user_id?.slice(0, 8) || "System"}...</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {auditQuery.data && auditQuery.data.total_pages > 1 && (
        <div className="mt-6 flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Page {auditQuery.data.page} of {auditQuery.data.total_pages}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Button
              variant="outline"
              disabled={page >= auditQuery.data.total_pages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
