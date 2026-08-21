"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { PermissionGuard } from "@/components/auth/PermissionGuard";
import { Breadcrumbs } from "@/components/shared/breadcrumbs";
import { EmptyState, ErrorState } from "@/components/shared/stats";
import { PageHeader } from "@/components/layout/dashboard-shell";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CategoryFormDialog } from "@/components/categories/category-form-dialog";
import { useToast } from "@/hooks/use-toast";
import { getApiErrorMessage } from "@/lib/utils";
import { categoryService } from "@/services";
import { Category } from "@/types";

export default function CategoriesPage() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [formOpen, setFormOpen] = useState(false);
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [deletingCategory, setDeletingCategory] = useState<Category | null>(null);

  const categoriesQuery = useQuery({
    queryKey: ["categories-options"],
    queryFn: () => categoryService.list({ page_size: 100 }),
  });

  const categories: Category[] = categoriesQuery.data?.categories ?? [];

  const deleteMutation = useMutation({
    mutationFn: (id: string) => categoryService.delete(id),
    onSuccess: () => {
      toast({ title: "Category deleted" });
      setDeletingCategory(null);
      queryClient.invalidateQueries({ queryKey: ["categories-options"] });
    },
    onError: (error) => {
      toast({
        variant: "destructive",
        title: "Failed to delete category",
        description: getApiErrorMessage(
          error,
          "This category could not be deleted. Please try again."
        ),
      });
    },
  });

  return (
    <div className="space-y-6">
      <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Categories" }]} />

      <PageHeader
        title="Categories"
        description="Work-specialization categories used to route tickets and scope Staff/Team Lead visibility. Anyone can view this list; creating, editing, and deleting require the Create Category permission."
        action={
          <PermissionGuard permission="category:create">
            <Button
              className="gap-2"
              onClick={() => {
                setEditingCategory(null);
                setFormOpen(true);
              }}
            >
              <Plus className="h-4 w-4" />
              Create Category
            </Button>
          </PermissionGuard>
        }
      />

      {categoriesQuery.isError ? (
        <ErrorState
          message={getApiErrorMessage(
            categoriesQuery.error,
            "Failed to load categories. Please try again."
          )}
        />
      ) : (
        <Card>
          <CardContent className="p-0">
            {categoriesQuery.isLoading ? (
              <div className="space-y-3 p-6">
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
                <Skeleton className="h-10 w-full" />
              </div>
            ) : categories.length === 0 ? (
              <EmptyState
                title="No categories yet"
                description="Create one to get started."
              />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Category Name</TableHead>
                    <TableHead>Assigned Users</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {categories.map((category) => (
                    <TableRow key={category.category_id}>
                      <TableCell className="font-medium">{category.category_name}</TableCell>
                      <TableCell>{category.assigned_user_count ?? 0}</TableCell>
                      <TableCell className="text-right">
                        <PermissionGuard permission="category:create">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => {
                              setEditingCategory(category);
                              setFormOpen(true);
                            }}
                            aria-label={`Edit ${category.category_name}`}
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                            onClick={() => setDeletingCategory(category)}
                            aria-label={`Delete ${category.category_name}`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </PermissionGuard>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}

      <CategoryFormDialog
        open={formOpen}
        onOpenChange={(open) => {
          setFormOpen(open);
          if (!open) setEditingCategory(null);
        }}
        category={editingCategory}
      />

      <AlertDialog
        open={!!deletingCategory}
        onOpenChange={(open) => !open && setDeletingCategory(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Category</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete <strong>{deletingCategory?.category_name}</strong>?
              {deletingCategory && (deletingCategory.assigned_user_count ?? 0) > 0 ? (
                <>
                  {" "}
                  This category currently has{" "}
                  <strong>{deletingCategory.assigned_user_count}</strong> assigned user(s) — remove
                  them via Edit first, or this will be rejected.
                </>
              ) : (
                " This cannot be undone."
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteMutation.isPending}
              onClick={() => deletingCategory && deleteMutation.mutate(deletingCategory.category_id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
