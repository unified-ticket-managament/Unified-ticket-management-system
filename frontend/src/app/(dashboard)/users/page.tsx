"use client";

import { useQuery } from "@tanstack/react-query";

import { userService } from "@/services";

export default function UsersPage() {
  const usersQuery = useQuery({
    queryKey: ["users"],
    queryFn: () =>
      userService.list({
        page: 1,
        page_size: 20,
      }),
  });

  if (usersQuery.isLoading) {
    return (
      <div className="p-6">
        Loading users...
      </div>
    );
  }

  if (usersQuery.isError) {
    return (
      <div className="p-6 text-red-500">
        Failed to load users.
      </div>
    );
  }

  const users = usersQuery.data?.users ?? [];

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold">
          Users
        </h1>

        <p className="text-muted-foreground">
          Total Users: {usersQuery.data?.total ?? 0}
        </p>
      </div>

      <div className="rounded-lg border">
        <table className="w-full">
          <thead>
            <tr className="border-b">
              <th className="p-3 text-left">
                Name
              </th>

              <th className="p-3 text-left">
                Email
              </th>

              <th className="p-3 text-left">
                Active
              </th>
            </tr>
          </thead>

          <tbody>
            {users.map((user: any) => (
              <tr
                key={user.user_id}
                className="border-b"
              >
                <td className="p-3">
                  {user.name}
                </td>

                <td className="p-3">
                  {user.email}
                </td>

                <td className="p-3">
                  {user.is_active
                    ? "Yes"
                    : "No"}
                </td>
              </tr>
            ))}

            {users.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="p-6 text-center text-muted-foreground"
                >
                  No users found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}