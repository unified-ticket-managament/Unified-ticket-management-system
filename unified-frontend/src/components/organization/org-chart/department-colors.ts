// Single source of truth mapping a person's `department` (an
// OrganizationNode field — see root CLAUDE.md's "Profile module"
// section: independent of `category_id`, display-only) onto a color
// and label, shared by the node-card chip and the legend/stats bar.
//
// The 8 real values come from shared_models' `CategoryName` enum
// (shared_models/shared_models/models/category.py) — kept as a plain
// literal list here rather than imported, since the frontend has no
// existing generated binding for that backend enum. "leadership"
// covers `department: null` (Super Admin/Site Lead/Account
// Manager/Team Lead with no category); "other" is the fallback for
// any department string that doesn't match a known category — e.g.
// the backend enum widening ahead of this file being updated — so a
// legend/stat total never silently drops a person.

export type DepartmentKey =
  | "ar"
  | "referral"
  | "authorization"
  | "iv"
  | "credentialing"
  | "coding"
  | "payment_posting"
  | "quality"
  | "leadership"
  | "other";

export interface DepartmentInfo {
  key: DepartmentKey;
  label: string;
  /** Tailwind utility classes — literal strings so the JIT compiler picks them up (see tailwind.config.ts). */
  fillClass: string;
  textClass: string;
  bgClass: string;
}

const KNOWN_DEPARTMENTS: Record<Exclude<DepartmentKey, "leadership" | "other">, DepartmentInfo> = {
  ar: { key: "ar", label: "AR", fillClass: "fill-dept-ar", textClass: "text-dept-ar", bgClass: "bg-dept-ar" },
  referral: {
    key: "referral",
    label: "Referral",
    fillClass: "fill-dept-referral",
    textClass: "text-dept-referral",
    bgClass: "bg-dept-referral",
  },
  authorization: {
    key: "authorization",
    label: "Authorization",
    fillClass: "fill-dept-authorization",
    textClass: "text-dept-authorization",
    bgClass: "bg-dept-authorization",
  },
  iv: { key: "iv", label: "IV", fillClass: "fill-dept-iv", textClass: "text-dept-iv", bgClass: "bg-dept-iv" },
  credentialing: {
    key: "credentialing",
    label: "Credentialing",
    fillClass: "fill-dept-credentialing",
    textClass: "text-dept-credentialing",
    bgClass: "bg-dept-credentialing",
  },
  coding: {
    key: "coding",
    label: "Coding",
    fillClass: "fill-dept-coding",
    textClass: "text-dept-coding",
    bgClass: "bg-dept-coding",
  },
  payment_posting: {
    key: "payment_posting",
    label: "Payment Posting",
    fillClass: "fill-dept-payment-posting",
    textClass: "text-dept-payment-posting",
    bgClass: "bg-dept-payment-posting",
  },
  quality: {
    key: "quality",
    label: "Quality",
    fillClass: "fill-dept-quality",
    textClass: "text-dept-quality",
    bgClass: "bg-dept-quality",
  },
};

const LEADERSHIP_INFO: DepartmentInfo = {
  key: "leadership",
  label: "Leadership",
  fillClass: "fill-dept-leadership",
  textClass: "text-dept-leadership",
  bgClass: "bg-dept-leadership",
};

const OTHER_INFO: DepartmentInfo = {
  key: "other",
  label: "Other",
  fillClass: "fill-dept-other",
  textClass: "text-dept-other",
  bgClass: "bg-dept-other",
};

// Case-insensitive lookup by the department string's display value
// (e.g. "Payment Posting") — OrganizationNode.department is the
// human-readable CategoryName value, not the enum member name.
const BY_LABEL = new Map<string, DepartmentInfo>(
  Object.values(KNOWN_DEPARTMENTS).map((info) => [info.label.toLowerCase(), info])
);

/** Resolves a node's `department` field to display info. `null` (no category — Leadership roles) and any unrecognized string are both handled without dropping the person from totals. */
export function getDepartmentInfo(department: string | null): DepartmentInfo {
  if (department === null) return LEADERSHIP_INFO;
  return BY_LABEL.get(department.toLowerCase()) ?? OTHER_INFO;
}

/** Ordered list of every department bucket (real categories, then Leadership, then Other) — the legend renders in this order, omitting zero-count entries. */
export const ALL_DEPARTMENTS: DepartmentInfo[] = [
  ...Object.values(KNOWN_DEPARTMENTS),
  LEADERSHIP_INFO,
  OTHER_INFO,
];
