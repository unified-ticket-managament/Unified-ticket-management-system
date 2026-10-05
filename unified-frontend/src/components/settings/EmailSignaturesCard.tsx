"use client";

import { useMutation } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { ImagePlus, Loader2, PenLine, Plus } from "lucide-react";
import { useRef, useState } from "react";

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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useEmailSignatures, useInvalidateEmailSignatures } from "@/hooks/use-email-signatures";
import { useToast } from "@/hooks/use-toast";
import { useTranslation } from "@/hooks/use-translation";
import { signatureService } from "@/services";
import type { EmailSignature } from "@/types";
import { RichTextEditor, isRichTextEmpty } from "@tw/components/mail/RichTextEditor";
import { RENDERED_MESSAGE_HTML_CLASS, escapeHtml, hasFailedImageUpload } from "@tw/lib/richText";
import { fromEditorSignatureHtml, toEditorSignatureHtml } from "@tw/lib/signatures";

type ApiError = AxiosError<{ detail?: unknown }>;

// FastAPI's `detail` is a string for an HTTPException but a list of
// {type, loc, msg, input} objects for a 422 validation error — never
// render it raw (an object is not a valid React child).
function errorDetail(error: unknown, fallback: string): string {
  const detail = (error as ApiError)?.response?.data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : null))
      .filter(Boolean);
    if (messages.length) return messages.join(" ");
  }
  return fallback;
}

// Profile → Settings → Email Signatures: the user's saved signatures
// (Outlook-style — many, exactly one default). The default is what every
// new email/reply/forward starts with; the composers' own signature
// picker only changes the one email being written. Server-side is the
// source of truth (GET /auth/me/signatures) — shared with the composers
// through the same cached query, so a change here shows up in the next
// composer without a page refresh.
export function EmailSignaturesCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { data, isLoading } = useEmailSignatures();
  const invalidate = useInvalidateEmailSignatures();

  const [editing, setEditing] = useState<EmailSignature | "new" | null>(null);
  const [deleting, setDeleting] = useState<EmailSignature | null>(null);

  const imageUrls = data?.image_urls ?? {};
  const signatures = data?.signatures ?? [];

  const onError = (title: string) => (error: ApiError) =>
    toast({
      variant: "destructive",
      title,
      description: errorDetail(error, t("common.checkDetailsError")),
    });

  const setDefaultMutation = useMutation({
    mutationFn: (id: string) => signatureService.setDefault(id),
    onSuccess: async () => {
      await invalidate();
      toast({ title: t("settings.defaultSignatureUpdatedToast") });
    },
    onError: onError(t("settings.signatureUpdateFailedToast")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => signatureService.delete(id),
    onSuccess: async () => {
      setDeleting(null);
      await invalidate();
      toast({ title: t("settings.signatureDeletedToast") });
    },
    onError: onError(t("settings.signatureUpdateFailedToast")),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <PenLine className="h-4 w-4" />
          {t("settings.emailSignatures")}
        </CardTitle>
        <CardDescription>{t("settings.emailSignaturesDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && (
          <div className="flex justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        )}

        {!isLoading && signatures.length === 0 && (
          <div className="rounded-lg border border-dashed border-border p-3 text-sm text-muted-foreground">
            <p>{t("settings.noSignatures")}</p>
            {data?.fallback_signature_html && (
              <>
                <p className="mt-1">{t("settings.noSignaturesFallback")}</p>
                <SignaturePreview html={data.fallback_signature_html} imageUrls={imageUrls} />
              </>
            )}
          </div>
        )}

        {signatures.map((signature) => (
          <div key={signature.signature_id} className="rounded-lg border border-border p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="min-w-0 truncate text-sm font-medium">{signature.name}</p>
              {signature.is_default && (
                <span className="flex-none rounded bg-primary/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
                  {t("settings.defaultBadge")}
                </span>
              )}
            </div>
            <SignaturePreview html={signature.html} imageUrls={imageUrls} />
            <div className="mt-3 flex flex-wrap justify-end gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => setEditing(signature)}>
                {t("common.edit")}
              </Button>
              {!signature.is_default && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={setDefaultMutation.isPending}
                  onClick={() => setDefaultMutation.mutate(signature.signature_id)}
                >
                  {t("settings.setAsDefault")}
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={() => setDeleting(signature)}
              >
                {t("common.delete")}
              </Button>
            </div>
          </div>
        ))}

        <Button type="button" variant="outline" className="gap-1.5" onClick={() => setEditing("new")}>
          <Plus className="h-4 w-4" />
          {t("settings.addSignature")}
        </Button>
      </CardContent>

      {editing && (
        <SignatureEditorDialog
          signature={editing === "new" ? null : editing}
          isFirst={signatures.length === 0}
          imageUrls={imageUrls}
          onClose={() => setEditing(null)}
          onSaved={invalidate}
        />
      )}

      <AlertDialog open={!!deleting} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.deleteSignatureTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.deleteSignatureDescription", { name: deleting?.name ?? "" })}
              {deleting?.is_default && signatures.length > 1 && (
                <> {t("settings.deleteSignatureDefaultNote")}</>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteMutation.isPending}
              onClick={(event) => {
                event.preventDefault();
                if (deleting) deleteMutation.mutate(deleting.signature_id);
              }}
            >
              {t("common.delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}

// Rendered, never raw HTML — `html` is already sanitized server-side
// (same allow-list as an outgoing email body).
function SignaturePreview({ html, imageUrls }: { html: string; imageUrls: Record<string, string> }) {
  return (
    <div
      className={`rounded-md bg-muted/30 px-3 py-2 text-sm ${RENDERED_MESSAGE_HTML_CLASS}`}
      dangerouslySetInnerHTML={{ __html: toEditorSignatureHtml(html, imageUrls) }}
    />
  );
}

interface SignatureEditorDialogProps {
  signature: EmailSignature | null;
  isFirst: boolean;
  imageUrls: Record<string, string>;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}

function SignatureEditorDialog({ signature, isFirst, imageUrls, onClose, onSaved }: SignatureEditorDialogProps) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [name, setName] = useState(signature?.name ?? "");
  const [html, setHtml] = useState(() => (signature ? toEditorSignatureHtml(signature.html, imageUrls) : ""));
  const [makeDefault, setMakeDefault] = useState(false);
  const [hasPendingUploads, setHasPendingUploads] = useState(false);
  const [isUploadingImage, setIsUploadingImage] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = { name: name.trim(), html: fromEditorSignatureHtml(html) };
      return signature
        ? signatureService.update(signature.signature_id, payload)
        : signatureService.create({ ...payload, is_default: makeDefault });
    },
    onSuccess: async () => {
      await onSaved();
      toast({ title: t("settings.signatureCreatedToast") });
      onClose();
    },
    onError: (error: ApiError) =>
      toast({
        variant: "destructive",
        title: t("settings.signatureUpdateFailedToast"),
        description: errorDetail(error, t("common.checkDetailsError")),
      }),
  });

  // Pasted/dropped images go through the editor's own upload pipeline;
  // this uploads through the same signature-image endpoint.
  async function uploadImage(file: File) {
    try {
      const image = await signatureService.uploadImage(file);
      return { attachmentId: image.image_id, contentId: image.content_id };
    } catch (error) {
      // The editor only outlines a failed image in red — say why.
      toast({
        variant: "destructive",
        title: t("settings.signatureImageUploadFailed"),
        description: errorDetail(error, t("common.checkDetailsError")),
      });
      throw error;
    }
  }

  async function handleAddImage(file: File) {
    setIsUploadingImage(true);
    try {
      const image = await signatureService.uploadImage(file);
      const src = image.preview_url ?? `cid:${image.content_id}`;
      setHtml(
        (prev) =>
          `${prev}<p><img src="${escapeHtml(src)}" alt="${escapeHtml(image.filename)}" width="150" ` +
          `data-local-id="sig-${image.content_id}" data-content-id="${image.content_id}"></p>`
      );
    } catch (error) {
      toast({
        variant: "destructive",
        title: t("settings.signatureImageUploadFailed"),
        description: errorDetail(error, t("common.checkDetailsError")),
      });
    } finally {
      setIsUploadingImage(false);
    }
  }

  function handleSave() {
    if (!name.trim()) {
      setValidationError(t("settings.signatureNameRequired"));
      return;
    }
    if (isRichTextEmpty(html) && !/<img\b/i.test(html)) {
      setValidationError(t("settings.signatureContentRequired"));
      return;
    }
    setValidationError(null);
    saveMutation.mutate();
  }

  const hasFailedImage = hasFailedImageUpload(html);
  const blocked = hasPendingUploads || hasFailedImage || isUploadingImage;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{signature ? t("settings.editSignature") : t("settings.newSignature")}</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="signature-name">{t("settings.signatureName")}</Label>
            <Input
              id="signature-name"
              value={name}
              maxLength={100}
              placeholder={t("settings.signatureNamePlaceholder")}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label>{t("settings.signatureContent")}</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 text-xs"
                disabled={isUploadingImage}
                onClick={() => fileInputRef.current?.click()}
              >
                {isUploadingImage ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <ImagePlus className="h-3.5 w-3.5" />
                )}
                {t("settings.addImage")}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/bmp,image/webp"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void handleAddImage(file);
                  e.target.value = "";
                }}
              />
            </div>
            <RichTextEditor
              value={html}
              onChange={setHtml}
              placeholder={t("settings.signaturePlaceholder")}
              minHeight="8rem"
              onImageUpload={uploadImage}
              onPendingImageUploadsChange={setHasPendingUploads}
            />
            <p className="text-xs text-muted-foreground">{t("settings.signatureImageHint")}</p>
          </div>

          {!signature && !isFirst && (
            <label className="flex items-center gap-2 text-sm">
              <Checkbox checked={makeDefault} onCheckedChange={(checked) => setMakeDefault(checked === true)} />
              {t("settings.useAsDefault")}
            </label>
          )}

          {hasFailedImage && (
            <p className="text-sm text-destructive">{t("settings.signatureImageFailedHint")}</p>
          )}
          {validationError && <p className="text-sm text-destructive">{validationError}</p>}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="button" disabled={saveMutation.isPending || blocked} onClick={handleSave}>
            {saveMutation.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
