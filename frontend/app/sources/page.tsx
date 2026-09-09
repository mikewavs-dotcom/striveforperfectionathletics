import { SourceCards } from "@/components/source-cards";
import { fetchSources } from "@/lib/api";
import type { CollectorWithRuns } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  let error: string | null = null;
  let sources: CollectorWithRuns[] = [];
  try {
    sources = await fetchSources();
  } catch (caught) {
    error = caught instanceof Error ? caught.message : "Failed to load sources";
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-extrabold uppercase tracking-wide sm:text-3xl">Sources</h1>
        <p className="text-sm text-neutral-600">
          Last ten runs per collector. A flat or zero sparkline is the break signal.
        </p>
      </div>
      {error ? (
        <p className="rounded-md border border-brand-silver bg-brand-orange-light px-4 py-3 text-sm">{error}</p>
      ) : null}
      <SourceCards sources={sources} />
    </div>
  );
}
