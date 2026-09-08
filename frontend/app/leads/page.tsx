import { LeadsWorkspace } from "@/components/leads-workspace";
import { fetchOrganization, fetchOrganizations } from "@/lib/api";
import { parseLeadsFilters, toApiParams } from "@/lib/leads-params";
import type { OrganizationDetail, PaginatedOrganizations } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function LeadsPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const filters = parseLeadsFilters(searchParams);
  let list: PaginatedOrganizations = { items: [], page: filters.page, page_size: 50, total: 0 };
  let detail: OrganizationDetail | null = null;
  let error: string | null = null;
  try {
    list = await fetchOrganizations(toApiParams(filters));
    if (filters.orgId) {
      try {
        detail = await fetchOrganization(filters.orgId);
      } catch {
        detail = null;
      }
    }
  } catch (caught) {
    error = caught instanceof Error ? caught.message : "Failed to load leads";
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-3xl font-extrabold uppercase tracking-wide">Leads</h1>
        <p className="text-sm text-neutral-600">Sort, filter, and verify organizations. Click a row for full detail.</p>
      </div>
      {error ? (
        <p className="rounded-md border border-brand-silver bg-brand-orange-light px-4 py-3 text-sm">{error}</p>
      ) : null}
      <LeadsWorkspace
        items={list.items}
        total={list.total}
        pageSize={list.page_size}
        filters={filters}
        detail={detail}
      />
    </div>
  );
}
