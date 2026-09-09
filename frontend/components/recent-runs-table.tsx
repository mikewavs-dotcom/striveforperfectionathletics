import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime, statusLabel } from "@/lib/labels";
import type { CollectorWithRuns, SourceRun, SourceRunStatus } from "@/lib/types";

function statusClass(status: SourceRunStatus): string {
  if (status === "success") {
    return "bg-black text-white";
  }
  if (status === "partial") {
    return "bg-brand-orange text-black";
  }
  return "bg-brand-silver text-black";
}

export function RecentRunsTable({ sources }: { sources: CollectorWithRuns[] }) {
  const runs: SourceRun[] = sources
    .flatMap((source) => source.runs)
    .sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
    .slice(0, 5);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent source runs</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead className="bg-black text-left text-xs font-bold uppercase tracking-wide text-white">
            <tr>
              <th className="px-4 py-2">Collector</th>
              <th className="hidden px-4 py-2 sm:table-cell">Started</th>
              <th className="px-4 py-2">Status</th>
              <th className="hidden px-4 py-2 md:table-cell">Found</th>
              <th className="px-4 py-2">New</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-neutral-500" colSpan={5}>
                  No runs yet.
                </td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr key={run.id} className="border-t border-brand-silver">
                  <td className="px-4 py-2 font-medium">{run.collector_name}</td>
                  <td className="hidden px-4 py-2 sm:table-cell">{formatDateTime(run.started_at)}</td>
                  <td className="px-4 py-2">
                    <Badge className={statusClass(run.status)}>{statusLabel(run.status)}</Badge>
                  </td>
                  <td className="hidden px-4 py-2 tabular-nums md:table-cell">{run.records_found ?? "—"}</td>
                  <td className="px-4 py-2 tabular-nums">{run.records_new ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
