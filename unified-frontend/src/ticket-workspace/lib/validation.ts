import { z } from "zod";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidUUID(value: string): boolean {
  return UUID_PATTERN.test(value.trim());
}

export function isValidDateRange(from: string, to: string): boolean {
  if (!from || !to) return true;
  return new Date(from).getTime() <= new Date(to).getTime();
}

// Same validation convention as EditProfileDialog/user-form-dialog/the
// login form (a bare `z.string().email()` check) — centralized here
// (moved from ComposeView.tsx, which used to define this locally) so
// every "To" recipient field shares one implementation rather than
// each defining its own.
const emailAddressSchema = z.string().trim().email();

export function isValidEmailAddress(value: string): boolean {
  return emailAddressSchema.safeParse(value).success;
}
