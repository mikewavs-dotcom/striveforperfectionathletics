import type {
  CollectorWithRuns,
  DashboardStats,
  OrganizationDetail,
  PaginatedOrganizations,
  PaginatedPolicyEvents,
} from "@/lib/types";

function apiBase(): string {
  const url = process.env.API_URL;
  if (!url) {
    throw new Error("API_URL is not set");
  }
  return url.replace(/\/$/, "");
}

async function apiGet<T>(path: string, params?: URLSearchParams): Promise<T> {
  const url = new URL(path, `${apiBase()}/`);
  if (params) {
    params.forEach((value, key) => {
      url.searchParams.append(key, value);
    });
  }
  const response = await fetch(url.toString(), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`API ${path} failed (${response.status})`);
  }
  return (await response.json()) as T;
}

export function fetchStats(): Promise<DashboardStats> {
  return apiGet<DashboardStats>("/stats");
}

export function fetchSources(): Promise<CollectorWithRuns[]> {
  return apiGet<CollectorWithRuns[]>("/sources");
}

export function fetchOrganizations(params: URLSearchParams): Promise<PaginatedOrganizations> {
  return apiGet<PaginatedOrganizations>("/organizations", params);
}

export function fetchOrganization(id: string): Promise<OrganizationDetail> {
  return apiGet<OrganizationDetail>(`/organizations/${id}`);
}

export function fetchPolicyEvents(page = 1): Promise<PaginatedPolicyEvents> {
  const params = new URLSearchParams({ page: String(page) });
  return apiGet<PaginatedPolicyEvents>("/policy-events", params);
}
