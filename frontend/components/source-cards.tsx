"use client";

import { useTransition } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime, humanizeKey, statusLabel } from "@/lib/labels";
import type { CollectorWithRuns, SourceRun, SourceRunStatus } from "@/lib/types";

function statusClass(status: SourceRunStatus | undefined): string {
  if (status === "success") {
    return "bg-black text-white";
  }
  if (status === "partial") {
    return "bg-brand-orange text-black";
  }
  if (status === "failed") {
    return "bg-red-700 text-white";
  }
  return "bg-brand-silver text-black";
}

function Sparkline({ values }: { values: number[] }) {
  const series = values.length === 0 ? [0] : values;
  const max = Math.max(1, ...series);
  const last = series.length - 1;
  const points = series
    .map((value, index) => {
      const x = last === 0 ? 0 : (index / last) * 120;
      const y = 32 - (value / max) * 28;
      return `${x},${y}`;
    })
    .join(" ");
  const flat = series.every((value) => value === series[0]);
  return (
    <svg viewBox="0 0 120 36" className="h-10 w-full" aria-label="Records found, last 10 runs">
      <polyline
        fill="none"
        stroke={flat ? "#8A8D8F" : "#F38B21"}
        strokeWidth="2"
        points={points}
      />
    </svg>
  );
}

function RunButton({ name }: { name: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function runNow() {
    startTransition(() => {
      void (async () => {
        await fetch(`/api/sources/${encodeURIComponent(name)}/run`, { method: "POST" });
        router.refresh();
      })();
    });
  }

  return (
    <Button type="button" size="sm" disabled={pending} onClick={runNow}>
      {pending ? "Starting…" : "Run now"}
    </Button>
  );
}

export function SourceCards({ sources }: { sources: CollectorWithRuns[] }) {
  if (sources.length === 0) {
    return <p className="text-sm text-neutral-500">No collectors registered.</p>;
  }
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {sources.map((source) => {
        const latest: SourceRun | undefined = source.runs[0];
        const chronological = [...source.runs].slice(0, 10).reverse();
        const spark = chronological.map((run) => run.records_found ?? 0);
        const failed = latest?.status === "failed";
        return (
          <Card key={source.name} className={failed ? "border-red-700" : undefined}>
            <CardHeader className="flex flex-row items-start justify-between gap-2">
              <div>
                <CardTitle>{humanizeKey(source.name)}</CardTitle>
                <p className="text-xs text-neutral-500">{formatDateTime(latest?.finished_at ?? latest?.started_at ?? null)}</p>
              </div>
              <Badge className={statusClass(latest?.status)}>{latest ? statusLabel(latest.status) : "Never run"}</Badge>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm">
                Records found:{" "}
                <span className="font-semibold tabular-nums">{latest?.records_found ?? "—"}</span>
              </p>
              {failed && latest?.error_message ? (
                <p className="text-xs text-red-700">{latest.error_message}</p>
              ) : null}
              <Sparkline values={spark} />
              <RunButton name={source.name} />
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
