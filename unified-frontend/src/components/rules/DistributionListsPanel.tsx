"use client";

import { useEffect, useState } from "react";
import axios from "axios";
import { Pencil, Plus, Trash2 } from "lucide-react";

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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import {
  deleteDistributionList,
  getDistributionList,
  listDistributionLists,
  setDistributionListActive,
  type DistributionListResponse,
  type DistributionListSummaryResponse,
} from "@tw/api/distributionLists";

import { DistributionListDialog } from "./DistributionListDialog";

// Admin management surface for Distribution Lists — a third Card
// alongside Mail Rules/OTP Rules inside RulesPanel.tsx (same Mail →
// Rules entry point, gated by the same rule:manage permission — see
// RulesPanel.tsx's own top-of-file comment on why this is the one
// canonical entry point rather than a new standalone route).
export function DistributionListsPanel() {
  const { toast } = useToast();

  const [lists, setLists] = useState<DistributionListSummaryResponse[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingList, setEditingList] = useState<DistributionListResponse | null>(null);
  const [pendingDelete, setPendingDelete] = useState<DistributionListSummaryResponse | null>(null);

  function refresh(signal?: AbortSignal) {
    listDistributionLists(signal)
      .then((data) => {
        setLists(data);
        setLoadError(null);
      })
      .catch((error) => {
        if (axios.isCancel(error)) return;
        setLoadError("Failed to load distribution lists. Please try again.");
      });
  }

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, []);

  async function handleNew() {
    setEditingList(null);
    setDialogOpen(true);
  }

  async function handleEdit(summary: DistributionListSummaryResponse) {
    try {
      const detail = await getDistributionList(summary.distribution_list_id);
      setEditingList(detail);
      setDialogOpen(true);
    } catch {
      toast({ title: "Couldn't load this distribution list", variant: "destructive" });
    }
  }

  async function handleToggleActive(summary: DistributionListSummaryResponse, isActive: boolean) {
    try {
      await setDistributionListActive(summary.distribution_list_id, isActive);
      refresh();
    } catch {
      toast({ title: "Couldn't update this distribution list", variant: "destructive" });
    }
  }

  async function handleDelete() {
    if (!pendingDelete) return;
    try {
      await deleteDistributionList(pendingDelete.distribution_list_id);
      toast({ title: "Distribution list deleted" });
      setPendingDelete(null);
      refresh();
    } catch {
      toast({ title: "Couldn't delete this distribution list", variant: "destructive" });
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Distribution Lists</CardTitle>
        <Button size="sm" onClick={handleNew}>
          <Plus className="mr-2 h-4 w-4" />
          New Distribution List
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        {loadError ? (
          <p className="px-6 py-8 text-sm text-destructive">{loadError}</p>
        ) : lists === null ? (
          <div className="space-y-3 p-6">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : lists.length === 0 ? (
          <p className="px-6 py-8 text-sm text-muted-foreground">No distribution lists yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="w-24">Members</TableHead>
                <TableHead className="w-20">Active</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {lists.map((list) => (
                <TableRow key={list.distribution_list_id}>
                  <TableCell className="font-medium">{list.name}</TableCell>
                  <TableCell className="max-w-xs text-sm text-muted-foreground">
                    {list.description || "—"}
                  </TableCell>
                  <TableCell>{list.member_count}</TableCell>
                  <TableCell>
                    <Switch
                      checked={list.is_active}
                      onCheckedChange={(checked) => handleToggleActive(list, checked)}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Edit distribution list"
                        onClick={() => handleEdit(list)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label="Delete distribution list"
                        onClick={() => setPendingDelete(list)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <DistributionListDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        distributionList={editingList}
        onSaved={refresh}
      />

      <AlertDialog open={pendingDelete != null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete "{pendingDelete?.name}"?</AlertDialogTitle>
            <AlertDialogDescription>
              Any Rule or recipient picker referencing this list will stop finding it. This cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}
