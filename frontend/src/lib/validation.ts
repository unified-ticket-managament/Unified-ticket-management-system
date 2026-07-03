const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidUUID(value: string): boolean {
  return UUID_PATTERN.test(value.trim());
}

export function isValidDateRange(from: string, to: string): boolean {
  if (!from || !to) return true;
  return new Date(from).getTime() <= new Date(to).getTime();
}
