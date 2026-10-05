"use client";

import { Link } from "react-router-dom";
import {
  Archive,
  Check,
  FilePlus,
  Flag,
  FolderInput,
  Forward as ForwardIcon,
  Link2,
  Mail,
  MailOpen,
  MoreVertical,
  Pin,
  PinOff,
  Reply as ReplyIcon,
  ReplyAll,
} from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useMailBulk } from "@tw/components/mail/MailBulkContext";
import { useAuthContext } from "@tw/context/AuthContext";
import {
  buildMessageMenu,
  hasMessageMenu,
  type MessageActionKey,
} from "@tw/lib/messageActions";
import type { InboxItem, MailFolder } from "@tw/types";

interface MessageActionsMenuProps {
  item: InboxItem;
  isUnread: boolean;
  folders: MailFolder[];
  // Actions the reading pane owns (reply/forward/ticket/archive) —
  // InboxPage opens the message and hands the action to
  // MessageDetailsView, so there is still exactly one implementation
  // of each.
  onMessageAction: (interactionId: string, action: MessageActionKey) => void;
  // Same handlers MessageDetailsView's own toolbar receives.
  onMarkRead: (interactionId: string) => void;
  onMarkUnread: (interactionId: string) => void;
  onAssignFolder: (interactionId: string, folderId: string | null) => Promise<boolean>;
  // Lets the row keep its hover overlay visible while this menu is open.
  onOpenChange?: (open: boolean) => void;
}

export function MessageActionsMenu({
  item,
  isUnread,
  folders,
  onMessageAction,
  onMarkRead,
  onMarkUnread,
  onAssignFolder,
  onOpenChange,
}: MessageActionsMenuProps) {
  const { currentUser } = useAuthContext();
  const bulk = useMailBulk();

  if (!hasMessageMenu({ ...item, isUnread })) return null;

  const has = (permission: string) => !!currentUser?.permissions.includes(permission);
  const openId = item.open_interaction_id ?? item.interaction_id;
  const menu = buildMessageMenu(
    { ...item, isUnread },
    {
      replyExternal: has("communication:reply_external"),
      createTicket: has("ticket:create"),
      attachToTicket: has("communication:attach_to_ticket"),
      archive: has("communication:archive"),
      moveToFolder: has("communication:move_to_folder"),
    }
  );

  const showTicketGroup = menu.viewTicket || menu.createTicket || menu.linkTicket;

  return (
    <DropdownMenu onOpenChange={onOpenChange}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="More actions"
              className="flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            >
              <MoreVertical className="h-4 w-4" />
            </button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>More actions</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" collisionPadding={8} className="w-56">
        {(menu.reply || menu.replyAll || menu.forward) && (
          <>
            {menu.reply && (
              <DropdownMenuItem onSelect={() => onMessageAction(openId, "reply")}>
                <ReplyIcon className="mr-2 h-4 w-4" />
                Reply
              </DropdownMenuItem>
            )}
            {menu.replyAll && (
              <DropdownMenuItem onSelect={() => onMessageAction(openId, "replyAll")}>
                <ReplyAll className="mr-2 h-4 w-4" />
                Reply All
              </DropdownMenuItem>
            )}
            {menu.forward && (
              <DropdownMenuItem onSelect={() => onMessageAction(openId, "forward")}>
                <ForwardIcon className="mr-2 h-4 w-4" />
                Forward
              </DropdownMenuItem>
            )}
            <DropdownMenuSeparator />
          </>
        )}

        <DropdownMenuItem
          onSelect={() =>
            menu.toggleRead === "markRead" ? onMarkRead(openId) : onMarkUnread(openId)
          }
        >
          {menu.toggleRead === "markRead" ? (
            <Mail className="mr-2 h-4 w-4" />
          ) : (
            <MailOpen className="mr-2 h-4 w-4" />
          )}
          {menu.toggleRead === "markRead" ? "Mark as read" : "Mark as unread"}
        </DropdownMenuItem>
        {bulk && (
          <>
            <DropdownMenuItem onSelect={() => void bulk.markMessage(openId, menu.toggleFlag)}>
              <Flag className="mr-2 h-4 w-4" />
              {menu.toggleFlag === "flag" ? "Flag" : "Unflag"}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void bulk.markMessage(openId, menu.togglePin)}>
              {menu.togglePin === "pin" ? (
                <Pin className="mr-2 h-4 w-4" />
              ) : (
                <PinOff className="mr-2 h-4 w-4" />
              )}
              {menu.togglePin === "pin" ? "Pin" : "Unpin"}
            </DropdownMenuItem>
          </>
        )}
        {menu.archive && (
          <DropdownMenuItem onSelect={() => onMessageAction(openId, "archive")}>
            <Archive className="mr-2 h-4 w-4" />
            Archive
          </DropdownMenuItem>
        )}
        {menu.moveToFolder && (
          <DropdownMenuSub>
            <DropdownMenuSubTrigger className="flex items-center rounded-sm px-2 py-2 text-sm outline-none focus:bg-accent data-[state=open]:bg-accent">
              <FolderInput className="mr-2 h-4 w-4" />
              Move to
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="max-h-72 overflow-y-auto">
              {folders.length === 0 ? (
                <DropdownMenuItem disabled>No folders yet — create one from the sidebar</DropdownMenuItem>
              ) : (
                <>
                  <DropdownMenuLabel>Move to folder</DropdownMenuLabel>
                  {folders.map((folder) => (
                    <DropdownMenuItem
                      key={folder.folder_id}
                      onSelect={() => onAssignFolder(openId, folder.folder_id)}
                    >
                      <Check
                        className={cn(
                          "mr-2 h-3.5 w-3.5",
                          item.folder_id === folder.folder_id ? "opacity-100" : "opacity-0"
                        )}
                      />
                      {folder.name.trim()}
                    </DropdownMenuItem>
                  ))}
                  {item.folder_id && (
                    <>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onSelect={() => onAssignFolder(openId, null)}>
                        Unfiled
                      </DropdownMenuItem>
                    </>
                  )}
                </>
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        )}

        {showTicketGroup && (
          <>
            <DropdownMenuSeparator />
            {menu.viewTicket && (
              <DropdownMenuItem asChild>
                <Link to={`/tickets/${item.ticket_id}`}>
                  <FilePlus className="mr-2 h-4 w-4" />
                  View Ticket
                </Link>
              </DropdownMenuItem>
            )}
            {menu.createTicket && (
              <DropdownMenuItem onSelect={() => onMessageAction(openId, "createTicket")}>
                <FilePlus className="mr-2 h-4 w-4" />
                Create Ticket
              </DropdownMenuItem>
            )}
            {menu.linkTicket && (
              <DropdownMenuItem onSelect={() => onMessageAction(openId, "linkTicket")}>
                <Link2 className="mr-2 h-4 w-4" />
                Link to Existing Ticket
              </DropdownMenuItem>
            )}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
