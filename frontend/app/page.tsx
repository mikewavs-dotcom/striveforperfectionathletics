import { RecentRunsTable } from "@/components/recent-runs-table";
import { SourceBarChart } from "@/components/source-bar-chart";
import { StatCards } from "@/components/stat-cards";
import { fetchSources, fetchStats } from "@/lib/api";
import type { CollectorWithRuns, DashboardStats } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  let error: string | null = null;
  let stats: DashboardStats = {
    organization_count: 0,
    contact_count: 0,
    new_records_last_30_days: 0,
    policy_event_count: 0,
  };
  let sources: CollectorWithRuns[] = [];
  try {
    [stats, sources] = await Promise.all([fetchStats(), fetchSources()]);
  } catch (caught) {
    error = caught instanceof Error ? caught.message : "Failed to load dashboard";
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-extrabold uppercase tracking-wide sm:text-3xl">Overview</h1>
        <p className="text-sm text-neutral-600">Live pipeline totals for Strive For Perfection Athletics.</p>
      </div>
      {error ? (
        <p className="rounded-md border border-brand-silver bg-brand-orange-light px-4 py-3 text-sm">{error}</p>
      ) : null}
      <StatCards stats={stats} />
      <div className="grid gap-4 lg:grid-cols-2">
        <SourceBarChart sources={sources} />
        <RecentRunsTable sources={sources} />
      </div>
    </div>
  );
}
