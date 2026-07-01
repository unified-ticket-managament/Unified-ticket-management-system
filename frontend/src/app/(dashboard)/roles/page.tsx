"use client";

import { useQuery } from "@tanstack/react-query";

import { roleService } from "@/services";

export default function RolesPage() {
  const rolesQuery = useQuery({
    queryKey: ["roles"],
    queryFn: () => roleService.list(),
  });

  if (rolesQuery.isLoading) {
    return (
      <div className="p-6">
        Loading roles...
      </div>
    );
  }

  if (rolesQuery.isError) {
    return (
      <div className="p-6 text-red-500">
        Failed to load roles.
      </div>
    );
  }

  const roles = rolesQuery.data?.roles ?? [];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold">
          Roles
        </h1>

        <p className="text-muted-foreground">
          Total Roles: {rolesQuery.data?.total ?? 0}
        </p>
      </div>

      <div className="rounded-lg border overflow-hidden">
        <table className="w-full">
          <thead className="border-b bg-muted">
            <tr>
              <th className="p-3 text-left">
                Role Name
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
            {roles.map((role: any) => (
              <tr
                key={role.role_id}
                className="border-b"
              >
                <td className="p-3 font-medium">
                  {role.name}
                </td>

                <td className="p-3">
                  {role.description || "-"}
                </td>

                <td className="p-3">
                  {role.is_active ? "Yes" : "No"}
                </td>
              </tr>
            ))}

            {roles.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="p-6 text-center text-muted-foreground"
                >
                  No roles found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}