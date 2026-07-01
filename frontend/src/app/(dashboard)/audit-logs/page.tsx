"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { auditService } from "@/services";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";

export default function AuditLogsPage() {
  const [search, setSearch] = useState("");

  const auditQuery = useQuery({
    queryKey: ["audit-logs"],
    queryFn: () => auditService.list(),
  });

  const logs = useMemo(() => {
    const allLogs = auditQuery.data?.logs ?? [];

    if (!search.trim()) return allLogs;

    return allLogs.filter((log: any) => {
      const value = search.toLowerCase();

      return (
        log.action?.toLowerCase().includes(value) ||
        log.entity_type?.toLowerCase().includes(value) ||
        log.user_id?.toLowerCase().includes(value)
      );
    });
  }, [auditQuery.data, search]);

  if (auditQuery.isLoading) {
    return (
      <div className="p-6">
        Loading audit logs...
      </div>
    );
  }

  if (auditQuery.isError) {
    return (
      <div className="p-6 text-red-500">
        Failed to load audit logs.
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">

      <div>
        <h1 className="text-3xl font-bold">
          Audit Logs
        </h1>

        <p className="text-muted-foreground">
          Total Logs: {auditQuery.data?.total ?? 0}
        </p>
      </div>

      <Card>
        <CardContent className="p-4">

          <div className="relative">

            <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />

            <Input
              className="pl-10"
              placeholder="Search..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />

          </div>

        </CardContent>
      </Card>

      <div className="space-y-4">

        {logs.map((log: any) => (

          <Card key={log.audit_log_id}>

            <CardContent className="p-5">

              <div className="flex items-center justify-between">

                <div>

                  <h3 className="font-semibold">
                    {log.action}
                  </h3>

                  <p className="text-sm text-muted-foreground">
                    {log.entity_type}
                  </p>

                </div>

                <Badge>
                  {log.user_id?.substring(0, 8)}
                </Badge>

              </div>

              <div className="mt-4 text-sm text-muted-foreground">

                Entity ID:

                <span className="ml-2 font-medium">

                  {log.entity_id ?? "-"}

                </span>

              </div>

              <div className="mt-2 text-sm text-muted-foreground">

                Time:

                <span className="ml-2 font-medium">

                  {new Date(log.timestamp).toLocaleString()}

                </span>

              </div>

            </CardContent>

          </Card>

        ))}

        {logs.length === 0 && (

          <Card>

            <CardContent className="p-10 text-center text-muted-foreground">

              No audit logs found.

            </CardContent>

          </Card>

        )}

      </div>

    </div>
  );
}