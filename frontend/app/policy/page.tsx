import { fetchPolicyEvents } from "@/lib/api";
import { formatDate, humanizeKey } from "@/lib/labels";
import type { PaginatedPolicyEvents } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function PolicyPage() {
  let error: string | null = null;
  let data: PaginatedPolicyEvents = { items: [], page: 1, page_size: 50, total: 0 };
  try {
    data = await fetchPolicyEvents(1);
  } catch (caught) {
    error = caught instanceof Error ? caught.message : "Failed to load policy events";
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-2xl font-extrabold uppercase tracking-wide sm:text-3xl">Policy</h1>
        <p className="text-sm text-neutral-600">
          Reverse-chronological NIL, eligibility, and compliance changes.
        </p>
      </div>
      {error ? (
        <p className="rounded-md border border-brand-silver bg-brand-orange-light px-4 py-3 text-sm">{error}</p>
      ) : null}
      <div className="overflow-x-auto rounded-lg border border-brand-silver bg-white">
        <table className="w-full text-sm">
          <thead className="bg-black text-left text-xs font-bold uppercase tracking-wide text-white">
            <tr>
              <th className="px-4 py-2">Detected</th>
              <th className="hidden px-4 py-2 sm:table-cell">Jurisdiction</th>
              <th className="hidden px-4 py-2 md:table-cell">Type</th>
              <th className="px-4 py-2">Summary</th>
              <th className="hidden px-4 py-2 md:table-cell">Effective</th>
              <th className="px-4 py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 ? (
              <tr>
                <td className="px-4 py-8 text-center text-neutral-500" colSpan={6}>
                  No policy events yet.
                </td>
              </tr>
            ) : (
              data.items.map((event) => (
                <tr key={event.id} className="border-t border-brand-silver">
                  <td className="px-4 py-2 whitespace-nowrap">{formatDate(event.detected_at)}</td>
                  <td className="hidden px-4 py-2 font-medium sm:table-cell">{event.jurisdiction}</td>
                  <td className="hidden px-4 py-2 capitalize md:table-cell">{humanizeKey(event.event_type)}</td>
                  <td className="px-4 py-2">{event.summary ?? "—"}</td>
                  <td className="hidden px-4 py-2 whitespace-nowrap md:table-cell">{formatDate(event.effective_date)}</td>
                  <td className="px-4 py-2">
                    <a
                      href={event.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex rounded-md bg-brand-orange px-2 py-1 text-xs font-semibold text-black hover:bg-brand-orange-dark hover:text-white"
                    >
                      Verify source
                    </a>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <p className="text-sm text-neutral-500">{data.total} events</p>
    </div>
  );
}
