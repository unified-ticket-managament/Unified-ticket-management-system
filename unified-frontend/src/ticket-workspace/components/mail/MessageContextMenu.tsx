"use client";

import { Link } from "react-router-dom";
import {
  Archive,
  Bell,
  FilePlus,
  Flag,
  FolderInput,
  Forward as ForwardIcon,
  Link2,
  Mail,
  MailOpen,
  Pin,
  PinOff,
  Reply as ReplyIcon,
  ReplyAll,
  Trash2,
  Undo2,
  X,
} from "lucide-react";

import {
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
} from "@/components/ui/context-menu";
import { FolderMoveItems } from "@tw/components/mail/FolderMoveItems";
import { useMailBulk } from "@tw/components/mail/MailBulkContext";
import { useMailReminder } from "@tw/components/mail/MailReminderContext";
import { selectionLabel } from "@tw/lib/mailSelection";
import {
  buildBulkMenu,
  buildMessageMenu,
  type MessageActionKey,
  type MessageActionRow,
} from "@tw/lib/messageActions";
import type { InboxItem, MailFolder } from "@tw/types";

interface MessageContextMenuContentProps {
  item: InboxItem;
  isUnread: boolean;
  folders: MailFolder[];
  // The selected rows at the moment the menu is open. More than one →
  // the bulk menu for the whole selection; otherwise the single-message
  // menu for `item` (the same items as the row's ⋮ menu).
  selectedRows: readonly MessageActionRow[];
  onMessageAction: (interactionId: string, action: MessageActionKey) => void;
  onMarkRead: (interactionId: string) => void;
  onMarkUnread: (interactionId: string) => void;
  onAssignFolder: (interactionId: string, folderId: string | null) => Promise<boolean>;
}

export function MessageContextMenuContent({
  item,
  isUnread,
  folders,
  selectedRows,
  onMessageAction,
  onMarkRead,
  onMarkUnread,
  onAssignFolder,
}: MessageContextMenuContentProps) {
  const bulk = useMailBulk();
  const reminders = useMailReminder();
  if (!bulk) return null;
  const { perms, runBulk, clear } = bulk;

  // Trash: Restore only (single or whole selection).
  if (bulk.isTrash) {
    const canRestore = buildBulkMenu(selectedRows, perms).restore;
    return (
      <ContextMenuContent className="w-56">
        {selectedRows.length > 1 && (
          <>
            <ContextMenuLabel>{selectionLabel(selectedRows.length)}</ContextMenuLabel>
            <ContextMenuSeparator />
          </>
        )}
        {canRestore ? (
          <ContextMenuItem onSelect={() => runBulk("restore", selectedRows)}>
            <Undo2 className="mr-2 h-4 w-4" />
            Restore
          </ContextMenuItem>
        ) : (
          <ContextMenuItem disabled>No actions available</ContextMenuItem>
        )}
        {selectedRows.length > 1 && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem onSelect={clear}>
              <X className="mr-2 h-4 w-4" />
              Clear selection
            </ContextMenuItem>
          </>
        )}
      </ContextMenuContent>
    );
  }

  if (selectedRows.length > 1) {
    const menu = buildBulkMenu(selectedRows, perms);
    const run = (key: Parameters<typeof runBulk>[0]) => runBulk(key, selectedRows);
    return (
      <ContextMenuContent className="w-56">
        <ContextMenuLabel>{selectionLabel(selectedRows.length)}</ContextMenuLabel>
        <ContextMenuSeparator />
        {menu.reply && (
          <ContextMenuItem onSelect={() => run("reply")}>
            <ReplyIcon className="mr-2 h-4 w-4" />
            Reply
          </ContextMenuItem>
        )}
        {menu.replyAll && (
          <ContextMenuItem onSelect={() => run("replyAll")}>
            <ReplyAll className="mr-2 h-4 w-4" />
            Reply All
          </ContextMenuItem>
        )}
        {menu.forward && (
          <ContextMenuItem onSelect={() => run("forward")}>
            <ForwardIcon className="mr-2 h-4 w-4" />
            Forward
          </ContextMenuItem>
        )}
        {(menu.createTicket || menu.linkTicket) && <ContextMenuSeparator />}
        {menu.createTicket && (
          <ContextMenuItem onSelect={() => run("createTicket")}>
            <FilePlus className="mr-2 h-4 w-4" />
            Create Ticket
          </ContextMenuItem>
        )}
        {menu.linkTicket && (
          <ContextMenuItem onSelect={() => run("linkTicket")}>
            <Link2 className="mr-2 h-4 w-4" />
            Link / Attach to Ticket
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        {menu.archive && (
          <ContextMenuItem onSelect={() => run("archive")}>
            <Archive className="mr-2 h-4 w-4" />
            Archive
          </ContextMenuItem>
        )}
        {menu.move && (
          <ContextMenuSub>
            <ContextMenuSubTrigger>
              <FolderInput className="mr-2 h-4 w-4" />
              Move to
            </ContextMenuSubTrigger>
            <ContextMenuSubContent className="max-h-72 overflow-y-auto">
              {folders.length === 0 ? (
                <ContextMenuItem disabled>No folders yet</ContextMenuItem>
              ) : (
                <>
                  <FolderMoveItems
                    kind="context"
                    folders={folders}
                    onPick={(folderId) => runBulk("move", selectedRows, { folderId })}
                  />
                  <ContextMenuSeparator />
                  <ContextMenuItem onSelect={() => runBulk("move", selectedRows, { folderId: null })}>
                    Unfiled
                  </ContextMenuItem>
                </>
              )}
            </ContextMenuSubContent>
          </ContextMenuSub>
        )}
        {menu.markRead && (
          <ContextMenuItem onSelect={() => run("markRead")}>
            <MailOpen className="mr-2 h-4 w-4" />
            Mark as read
          </ContextMenuItem>
        )}
        {menu.markUnread && (
          <ContextMenuItem onSelect={() => run("markUnread")}>
            <Mail className="mr-2 h-4 w-4" />
            Mark as unread
          </ContextMenuItem>
        )}
        {menu.flag && (
          <ContextMenuItem onSelect={() => run("flag")}>
            <Flag className="mr-2 h-4 w-4" />
            Flag
          </ContextMenuItem>
        )}
        {menu.unflag && (
          <ContextMenuItem onSelect={() => run("unflag")}>
            <Flag className="mr-2 h-4 w-4" />
            Unflag
          </ContextMenuItem>
        )}
        {menu.pin && (
          <ContextMenuItem onSelect={() => run("pin")}>
            <Pin className="mr-2 h-4 w-4" />
            Pin
          </ContextMenuItem>
        )}
        {menu.unpin && (
          <ContextMenuItem onSelect={() => run("unpin")}>
            <PinOff className="mr-2 h-4 w-4" />
            Unpin
          </ContextMenuItem>
        )}
        {menu.delete && (
          <ContextMenuItem
            className="text-destructive focus:text-destructive"
            onSelect={() => run("delete")}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            Delete
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem onSelect={clear}>
          <X className="mr-2 h-4 w-4" />
          Clear selection
        </ContextMenuItem>
      </ContextMenuContent>
    );
  }

  // Single message — same gating as the ⋮ menu (buildMessageMenu).
  const openId = item.open_interaction_id ?? item.interaction_id;
  const menu = buildMessageMenu({ ...item, isUnread }, perms);
  const showTicketGroup = menu.viewTicket || menu.createTicket || menu.linkTicket;

  return (
    <ContextMenuContent className="w-56">
      {menu.reply && (
        <ContextMenuItem onSelect={() => onMessageAction(openId, "reply")}>
          <ReplyIcon className="mr-2 h-4 w-4" />
          Reply
        </ContextMenuItem>
      )}
      {menu.replyAll && (
        <ContextMenuItem onSelect={() => onMessageAction(openId, "replyAll")}>
          <ReplyAll className="mr-2 h-4 w-4" />
          Reply All
        </ContextMenuItem>
      )}
      {menu.forward && (
        <ContextMenuItem onSelect={() => onMessageAction(openId, "forward")}>
          <ForwardIcon className="mr-2 h-4 w-4" />
          Forward
        </ContextMenuItem>
      )}
      <ContextMenuSeparator />
      <ContextMenuItem
        onSelect={() => (menu.toggleRead === "markRead" ? onMarkRead(openId) : onMarkUnread(openId))}
      >
        {menu.toggleRead === "markRead" ? (
          <Mail className="mr-2 h-4 w-4" />
        ) : (
          <MailOpen className="mr-2 h-4 w-4" />
        )}
        {menu.toggleRead === "markRead" ? "Mark as read" : "Mark as unread"}
      </ContextMenuItem>
      <ContextMenuItem onSelect={() => void bulk.markMessage(openId, menu.toggleFlag)}>
        <Flag className="mr-2 h-4 w-4" />
        {menu.toggleFlag === "flag" ? "Flag" : "Unflag"}
      </ContextMenuItem>
      <ContextMenuItem onSelect={() => void bulk.markMessage(openId, menu.togglePin)}>
        {menu.togglePin === "pin" ? (
          <Pin className="mr-2 h-4 w-4" />
        ) : (
          <PinOff className="mr-2 h-4 w-4" />
        )}
        {menu.togglePin === "pin" ? "Pin" : "Unpin"}
      </ContextMenuItem>
      {reminders && (
        <ContextMenuItem
          onSelect={() => {
            const existing = reminders.reminderFor(openId);
            if (existing?.status === "ACTIVE") reminders.edit(existing);
            else reminders.remind(openId);
          }}
        >
          <Bell className="mr-2 h-4 w-4" />
          {reminders.reminderFor(openId)?.status === "ACTIVE" ? "Edit reminder" : "Remind me"}
        </ContextMenuItem>
      )}
      {menu.archive && (
        <ContextMenuItem onSelect={() => onMessageAction(openId, "archive")}>
          <Archive className="mr-2 h-4 w-4" />
          Archive
        </ContextMenuItem>
      )}
      {menu.moveToFolder && (
        <ContextMenuSub>
          <ContextMenuSubTrigger>
            <FolderInput className="mr-2 h-4 w-4" />
            Move to
          </ContextMenuSubTrigger>
          <ContextMenuSubContent className="max-h-72 overflow-y-auto">
            {folders.length === 0 ? (
              <ContextMenuItem disabled>No folders yet — create one from the sidebar</ContextMenuItem>
            ) : (
              <>
                <FolderMoveItems
                  kind="context"
                  folders={folders}
                  currentFolderId={item.folder_id}
                  onPick={(folderId) => onAssignFolder(openId, folderId)}
                />
                {item.folder_id && (
                  <>
                    <ContextMenuSeparator />
                    <ContextMenuItem onSelect={() => onAssignFolder(openId, null)}>Unfiled</ContextMenuItem>
                  </>
                )}
              </>
            )}
          </ContextMenuSubContent>
        </ContextMenuSub>
      )}
      {showTicketGroup && <ContextMenuSeparator />}
      {menu.viewTicket && (
        <ContextMenuItem asChild>
          <Link to={`/tickets/${item.ticket_id}`}>
            <FilePlus className="mr-2 h-4 w-4" />
            View Ticket
          </Link>
        </ContextMenuItem>
      )}
      {menu.createTicket && (
        <ContextMenuItem onSelect={() => onMessageAction(openId, "createTicket")}>
          <FilePlus className="mr-2 h-4 w-4" />
          Create Ticket
        </ContextMenuItem>
      )}
      {menu.linkTicket && (
        <ContextMenuItem onSelect={() => onMessageAction(openId, "linkTicket")}>
          <Link2 className="mr-2 h-4 w-4" />
          Link to Existing Ticket
        </ContextMenuItem>
      )}
    </ContextMenuContent>
  );
}
