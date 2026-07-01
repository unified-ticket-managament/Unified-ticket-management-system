"use client";

import { useQuery } from "@tanstack/react-query";

import { permissionService } from "@/services";

export default function PermissionsPage() {
  const permissionsQuery = useQuery({
    queryKey: ["permissions"],
    queryFn: () => permissionService.list(),
  });

  if (permissionsQuery.isLoading) {
    return (
      <div className="p-6">
        Loading permissions...
      </div>
    );
  }

  if (permissionsQuery.isError) {
    return (
      <div className="p-6 text-red-500">
        Failed to load permissions.
      </div>
    );
  }

  const permissions =
    permissionsQuery.data?.permissions ?? [];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold">
          Permissions
        </h1>

        <p className="text-muted-foreground">
          Total Permissions:{" "}
          {permissionsQuery.data?.total ?? 0}
        </p>
      </div>

      <div className="rounded-lg border overflow-hidden">
        <table className="w-full">
          <thead className="border-b bg-muted">
            <tr>
              <th className="p-3 text-left">
                Permission
              </th>

              <th className="p-3 text-left">
                Description
              </th>

              <th className="p-3 text-left">
                Active
              </th>
            </tr>
          </thead>

          <tbody>
            {permissions.map((permission: any) => (
              <tr
                key={permission.permission_id}
                className="border-b"
              >
                <td className="p-3 font-medium">
                  {permission.permission_name}
                </td>

                <td className="p-3">
                  {permission.description || "-"}
                </td>

                <td className="p-3">
                  {permission.is_active
                    ? "Yes"
                    : "No"}
                </td>
              </tr>
            ))}

            {permissions.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="p-6 text-center text-muted-foreground"
                >
                  No permissions found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}