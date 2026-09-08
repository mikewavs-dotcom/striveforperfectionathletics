import type { SortDir, SortField } from "@/lib/types";

export type SearchValue = string | string[] | undefined;

export interface LeadsFilters {
  page: number;
  orgTypes: string[];
  state: string;
  minCamps: number;
  minPanels: number;
  minMedia: number;
  hasEmail: boolean;
  sortBy: SortField;
  sortDir: SortDir;
  orgId: string | null;
}

const SORT_FIELDS: SortField[] = [
  "name",
  "state",
  "city",
  "created_at",
  "last_verified",
  "camps_score",
  "panels_score",
  "media_score",
];

function first(value: SearchValue): string | undefined {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function all(value: SearchValue): string[] {
  if (value === undefined) {
    return [];
  }
  return Array.isArray(value) ? value : [value];
}

function asInt(value: string | undefined, fallback: number): number {
  if (value === undefined || value === "") {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function parseLeadsFilters(sp: Record<string, SearchValue>): LeadsFilters {
  const sortByRaw = first(sp.sort_by);
  const sortDirRaw = first(sp.sort_dir);
  return {
    page: Math.max(1, asInt(first(sp.page), 1)),
    orgTypes: all(sp.org_type),
    state: (first(sp.state) ?? "").trim(),
    minCamps: asInt(first(sp.min_camps_score), 0),
    minPanels: asInt(first(sp.min_panels_score), 0),
    minMedia: asInt(first(sp.min_media_score), 0),
    hasEmail: first(sp.has_email) === "true",
    sortBy: SORT_FIELDS.includes(sortByRaw as SortField) ? (sortByRaw as SortField) : "name",
    sortDir: sortDirRaw === "desc" ? "desc" : "asc",
    orgId: first(sp.org) ?? null,
  };
}

export function toApiParams(filters: LeadsFilters): URLSearchParams {
  const params = new URLSearchParams();
  params.set("page", String(filters.page));
  params.set("sort_by", filters.sortBy);
  params.set("sort_dir", filters.sortDir);
  for (const orgType of filters.orgTypes) {
    params.append("org_type", orgType);
  }
  if (filters.state !== "") {
    params.set("state", filters.state);
  }
  if (filters.minCamps > 0) {
    params.set("min_camps_score", String(filters.minCamps));
  }
  if (filters.minPanels > 0) {
    params.set("min_panels_score", String(filters.minPanels));
  }
  if (filters.minMedia > 0) {
    params.set("min_media_score", String(filters.minMedia));
  }
  if (filters.hasEmail) {
    params.set("has_email", "true");
  }
  return params;
}

export function toPageParams(filters: LeadsFilters): URLSearchParams {
  const params = toApiParams(filters);
  if (filters.orgId) {
    params.set("org", filters.orgId);
  }
  return params;
}
