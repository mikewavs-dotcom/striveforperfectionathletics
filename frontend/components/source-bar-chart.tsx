import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/labels";
import type { CollectorWithRuns } from "@/lib/types";

export function SourceBarChart({ sources }: { sources: CollectorWithRuns[] }) {
  const bars = sources.map((source) => {
    const latest = source.runs[0];
    return {
      name: source.name,
      count: latest?.records_found ?? 0,
    };
  });
  const max = Math.max(1, ...bars.map((bar) => bar.count));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Records by source</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {bars.length === 0 ? (
          <p className="text-sm text-neutral-500">No source runs yet.</p>
        ) : (
          bars.map((bar) => (
            <div key={bar.name} className="space-y-1">
              <div className="flex items-baseline justify-between text-sm">
                <span className="font-medium">{bar.name}</span>
                <span className="tabular-nums">{formatNumber(bar.count)}</span>
              </div>
              <div className="h-6 rounded-sm bg-neutral-100">
                <div
                  className="h-full rounded-sm bg-brand-orange"
                  style={{ width: `${Math.max(4, (bar.count / max) * 100)}%` }}
                />
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
