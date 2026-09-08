import type { ContactRole, OrgType, SourceRunStatus } from "@/lib/types";

export const ORG_TYPES: { value: OrgType; label: string }[] = [
  { value: "booster_club", label: "Booster club" },
  { value: "nil_collective", label: "NIL collective" },
  { value: "youth_sports_org", label: "Youth sports" },
  { value: "travel_program", label: "Travel program" },
  { value: "showcase_operator", label: "Showcase operator" },
  { value: "high_school", label: "High school" },
  { value: "school_district", label: "School district" },
  { value: "college", label: "College" },
  { value: "business", label: "Business" },
  { value: "other", label: "Other" },
];

const ORG_TYPE_LABELS: Record<OrgType, string> = Object.fromEntries(
  ORG_TYPES.map((item) => [item.value, item.label]),
) as Record<OrgType, string>;

export function orgTypeLabel(value: OrgType): string {
  return ORG_TYPE_LABELS[value] ?? value;
}

export function roleLabel(value: ContactRole | null): string {
  if (value === null) {
    return "—";
  }
  return value.replace(/_/g, " ");
}

export function statusLabel(value: SourceRunStatus): string {
  if (value === "success") {
    return "Success";
  }
  if (value === "partial") {
    return "Partial";
  }
  return "Failed";
}

export function humanizeKey(key: string): string {
  return key.replace(/_/g, " ");
}

export function formatDate(value: string | null): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "—";
  }
  return parsed.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(value: string | null): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "—";
  }
  return parsed.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export function scoreClass(score: number | null): string {
  if (score === null) {
    return "bg-neutral-100 text-neutral-500";
  }
  if (score >= 80) {
    return "bg-brand-orange-dark text-white";
  }
  if (score >= 60) {
    return "bg-brand-orange text-black";
  }
  return "bg-brand-orange-light text-black";
}
