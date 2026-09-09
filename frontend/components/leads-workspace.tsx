"use client";

import { useMemo, useState, useTransition, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table";

import { OrgDrawer } from "@/components/org-drawer";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { formatDate, ORG_TYPES, orgTypeLabel, roleLabel, scoreClass } from "@/lib/labels";
import { toPageParams, type LeadsFilters } from "@/lib/leads-params";
import type {
  OrganizationDetail,
  OrganizationListItem,
  OutreachCampaign,
  PushLeadsResult,
  SortField,
} from "@/lib/types";

function ScoreCell({ value }: { value: number | null }) {
  return (
    <span className={`inline-flex min-w-[2.5rem] justify-center rounded-sm px-2 py-0.5 text-xs font-bold tabular-nums ${scoreClass(value)}`}>
      {value === null ? "—" : value}
    </span>
  );
}

export function LeadsWorkspace({
  items,
  total,
  pageSize,
  filters,
  detail,
  outreachConfigured,
  campaigns,
}: {
  items: OrganizationListItem[];
  total: number;
  pageSize: number;
  filters: LeadsFilters;
  detail: OrganizationDetail | null;
  outreachConfigured: boolean;
  campaigns: OutreachCampaign[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [stateValue, setStateValue] = useState(filters.state);
  const [camps, setCamps] = useState(filters.minCamps);
  const [panels, setPanels] = useState(filters.minPanels);
  const [media, setMedia] = useState(filters.minMedia);
  const [campaignId, setCampaignId] = useState("");
  const [pushMessage, setPushMessage] = useState<string | null>(null);
  const [pushing, setPushing] = useState(false);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  function pushFilters(next: LeadsFilters) {
    startTransition(() => {
      router.push(`/leads?${toPageParams(next).toString()}`);
    });
  }

  function patch(partial: Partial<LeadsFilters>) {
    pushFilters({ ...filters, page: 1, ...partial });
  }

  const sorting: SortingState = [{ id: filters.sortBy, desc: filters.sortDir === "desc" }];

  const columns = useMemo<ColumnDef<OrganizationListItem>[]>(
    () => [
      {
        id: "select",
        enableSorting: false,
        header: ({ table }) => (
          <Checkbox
            checked={table.getIsAllPageRowsSelected()}
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(Boolean(value))}
            aria-label="Select all"
            onClick={(event) => event.stopPropagation()}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(value) => row.toggleSelected(Boolean(value))}
            aria-label="Select row"
            onClick={(event) => event.stopPropagation()}
          />
        ),
      },
      {
        accessorKey: "name",
        header: "Organization",
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
      },
      {
        accessorKey: "org_type",
        header: "Type",
        enableSorting: false,
        cell: ({ row }) => orgTypeLabel(row.original.org_type),
      },
      { accessorKey: "city", header: "City", cell: ({ row }) => row.original.city ?? "—" },
      { accessorKey: "state", header: "State", cell: ({ row }) => row.original.state ?? "—" },
      {
        id: "camps_score",
        accessorFn: (row) => row.scores.camps,
        header: "Camps",
        cell: ({ row }) => <ScoreCell value={row.original.scores.camps} />,
      },
      {
        id: "panels_score",
        accessorFn: (row) => row.scores.panels,
        header: "Panels",
        cell: ({ row }) => <ScoreCell value={row.original.scores.panels} />,
      },
      {
        id: "media_score",
        accessorFn: (row) => row.scores.media,
        header: "Media",
        cell: ({ row }) => <ScoreCell value={row.original.scores.media} />,
      },
      {
        id: "contact_name",
        header: "Top contact",
        enableSorting: false,
        cell: ({ row }) => row.original.top_contact?.full_name ?? "—",
      },
      {
        id: "contact_role",
        header: "Role",
        enableSorting: false,
        cell: ({ row }) => roleLabel(row.original.top_contact?.role ?? null),
      },
      {
        id: "last_verified",
        accessorFn: (row) => row.last_verified_at,
        header: "Last verified",
        cell: ({ row }) => formatDate(row.original.last_verified_at),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: items,
    columns,
    state: { rowSelection: selection, sorting },
    enableRowSelection: true,
    onRowSelectionChange: setSelection,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.id,
    manualPagination: true,
    manualSorting: true,
    pageCount,
  });

  const selectedIds = Object.entries(selection)
    .filter(([, selected]) => selected)
    .map(([id]) => id);

  function toggleOrgType(value: string, checked: boolean) {
    const orgTypes = checked
      ? [...filters.orgTypes, value]
      : filters.orgTypes.filter((item) => item !== value);
    patch({ orgTypes });
  }

  function onSort(field: SortField) {
    const sortDir = filters.sortBy === field && filters.sortDir === "asc" ? "desc" : "asc";
    patch({ sortBy: field, sortDir });
  }

  function onStateSubmit(event: FormEvent) {
    event.preventDefault();
    patch({ state: stateValue.trim().toUpperCase() });
  }

  async function exportSelected() {
    if (selectedIds.length === 0) {
      return;
    }
    const params = toPageParams(filters);
    params.delete("page");
    params.delete("org");
    for (const id of selectedIds) {
      params.append("organization_id", id);
    }
    const response = await fetch(`/export?${params.toString()}`);
    if (!response.ok) {
      throw new Error("Export failed");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "organizations.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function pushSelected() {
    if (selectedIds.length === 0 || campaignId === "") {
      return;
    }
    setPushing(true);
    setPushMessage(null);
    try {
      const response = await fetch(
        `/api/outreach/campaigns/${encodeURIComponent(campaignId)}/leads`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ organization_ids: selectedIds }),
        },
      );
      if (!response.ok) {
        setPushMessage(`Push failed (${response.status})`);
        return;
      }
      const result = (await response.json()) as PushLeadsResult;
      setPushMessage(
        `Pushed ${result.pushed}. Skipped minor: ${result.skipped_minor}. Skipped no email: ${result.skipped_no_email}.`,
      );
    } catch {
      setPushMessage("Push failed");
    } finally {
      setPushing(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <aside className="w-full shrink-0 space-y-4 rounded-lg border border-brand-silver bg-white p-4 lg:w-64">
        <h2 className="font-display text-sm font-bold uppercase tracking-wide">Filters</h2>
        <div className="space-y-2">
          <Label>Org type</Label>
          <div className="max-h-48 space-y-1.5 overflow-y-auto">
            {ORG_TYPES.map((item) => (
              <label key={item.value} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={filters.orgTypes.includes(item.value)}
                  onCheckedChange={(checked) => toggleOrgType(item.value, Boolean(checked))}
                />
                {item.label}
              </label>
            ))}
          </div>
        </div>
        <form className="space-y-1" onSubmit={onStateSubmit}>
          <Label htmlFor="state">State</Label>
          <Input
            id="state"
            value={stateValue}
            onChange={(event) => setStateValue(event.target.value)}
            onBlur={() => {
              if (stateValue.trim().toUpperCase() !== filters.state) {
                patch({ state: stateValue.trim().toUpperCase() });
              }
            }}
            placeholder="VA"
            maxLength={2}
          />
        </form>
        <div className="space-y-1">
          <Label>Camps min {camps}</Label>
          <Slider
            min={0}
            max={100}
            step={5}
            value={[camps]}
            onValueChange={(value) => setCamps(value[0] ?? 0)}
            onValueCommit={(value) => patch({ minCamps: value[0] ?? 0 })}
          />
        </div>
        <div className="space-y-1">
          <Label>Panels min {panels}</Label>
          <Slider
            min={0}
            max={100}
            step={5}
            value={[panels]}
            onValueChange={(value) => setPanels(value[0] ?? 0)}
            onValueCommit={(value) => patch({ minPanels: value[0] ?? 0 })}
          />
        </div>
        <div className="space-y-1">
          <Label>Media min {media}</Label>
          <Slider
            min={0}
            max={100}
            step={5}
            value={[media]}
            onValueChange={(value) => setMedia(value[0] ?? 0)}
            onValueCommit={(value) => patch({ minMedia: value[0] ?? 0 })}
          />
        </div>
        <div className="flex items-center justify-between">
          <Label htmlFor="has-email">Has email</Label>
          <Switch
            id="has-email"
            checked={filters.hasEmail}
            onCheckedChange={(checked) => patch({ hasEmail: checked })}
          />
        </div>
      </aside>

      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-neutral-600">
            {total} organizations
            {pending ? " · Updating…" : ""}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {outreachConfigured ? (
              <>
                <select
                  className="h-8 rounded-md border border-brand-silver bg-white px-2 text-xs"
                  value={campaignId}
                  onChange={(event) => setCampaignId(event.target.value)}
                  aria-label="ReachInbox campaign"
                >
                  <option value="">Campaign</option>
                  {campaigns
                    .filter((campaign) => campaign.id !== undefined)
                    .map((campaign) => (
                      <option key={String(campaign.id)} value={String(campaign.id)}>
                        {campaign.name ?? String(campaign.id)}
                      </option>
                    ))}
                </select>
                <Button
                  size="sm"
                  disabled={selectedIds.length === 0 || campaignId === "" || pushing}
                  onClick={() => void pushSelected()}
                >
                  Push to ReachInbox ({selectedIds.length})
                </Button>
              </>
            ) : null}
            <Button size="sm" variant="black" disabled={selectedIds.length === 0} onClick={() => void exportSelected()}>
              Export selected ({selectedIds.length})
            </Button>
          </div>
        </div>
        {pushMessage ? (
          <p className="rounded-md border border-brand-silver bg-brand-orange-light px-3 py-2 text-sm">
            {pushMessage}
          </p>
        ) : null}
        <div className="overflow-x-auto rounded-lg border border-brand-silver">
          <table className="w-full text-sm">
            <thead className="bg-black text-left text-xs font-bold uppercase tracking-wide text-white">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const canSort = header.column.getCanSort();
                    const field = header.column.id as SortField;
                    return (
                      <th key={header.id} className="px-2 py-2">
                        {canSort ? (
                          <button
                            type="button"
                            className="uppercase tracking-wide"
                            onClick={() => onSort(field)}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {filters.sortBy === field ? (filters.sortDir === "asc" ? " ↑" : " ↓") : ""}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.length === 0 ? (
                <tr>
                  <td className="px-3 py-8 text-center text-neutral-500" colSpan={columns.length}>
                    No organizations match these filters.
                  </td>
                </tr>
              ) : (
                table.getRowModel().rows.map((row) => (
                  <tr
                    key={row.id}
                    className="cursor-pointer border-t border-brand-silver hover:bg-brand-orange-light"
                    onClick={() => pushFilters({ ...filters, orgId: row.original.id })}
                  >
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id} className="px-2 py-1.5 align-middle">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="flex items-center justify-between text-sm">
          <Button
            variant="outline"
            size="sm"
            disabled={filters.page <= 1}
            onClick={() => pushFilters({ ...filters, page: filters.page - 1 })}
          >
            Previous
          </Button>
          <span>
            Page {filters.page} of {pageCount}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={filters.page >= pageCount}
            onClick={() => pushFilters({ ...filters, page: filters.page + 1 })}
          >
            Next
          </Button>
        </div>
      </div>

      <OrgDrawer
        open={filters.orgId !== null}
        pending={pending && filters.orgId !== null && (detail === null || detail.id !== filters.orgId)}
        detail={detail !== null && detail.id === filters.orgId ? detail : null}
        onOpenChange={(open) => {
          if (!open) {
            pushFilters({ ...filters, orgId: null });
          }
        }}
      />
    </div>
  );
}
