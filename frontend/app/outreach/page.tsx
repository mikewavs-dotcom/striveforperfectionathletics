import { OutreachWorkspace } from "@/components/outreach-workspace";
import { fetchOutreachAccounts, fetchOutreachCampaigns, fetchOutreachStatus } from "@/lib/api";
import type { OutreachAccount, OutreachCampaign } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function OutreachPage() {
  let configured = false;
  let statusError: string | null = null;
  try {
    const status = await fetchOutreachStatus();
    configured = status.configured;
  } catch (caught) {
    statusError = caught instanceof Error ? caught.message : "Failed to load outreach status";
  }

  if (statusError) {
    return (
      <div className="space-y-4">
        <h1 className="font-display text-3xl font-extrabold uppercase tracking-wide">Outreach</h1>
        <p className="rounded-md border border-brand-silver bg-brand-orange-light px-4 py-3 text-sm">
          {statusError}
        </p>
      </div>
    );
  }

  if (!configured) {
    return (
      <div className="space-y-4">
        <h1 className="font-display text-3xl font-extrabold uppercase tracking-wide">Outreach</h1>
        <p className="rounded-md border border-brand-silver bg-brand-orange-light px-4 py-3 text-sm">
          Add REACHINBOX_API_KEY to .env and restart the API.
        </p>
      </div>
    );
  }

  let error: string | null = null;
  let campaigns: OutreachCampaign[] = [];
  let accounts: OutreachAccount[] = [];
  try {
    campaigns = await fetchOutreachCampaigns();
    accounts = await fetchOutreachAccounts();
  } catch (caught) {
    error = caught instanceof Error ? caught.message : "Failed to load ReachInbox data";
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-display text-3xl font-extrabold uppercase tracking-wide">Outreach</h1>
        <p className="text-sm text-neutral-600">
          Control the client ReachInbox workspace: campaigns, sending accounts, start and pause.
        </p>
      </div>
      {error ? (
        <p className="rounded-md border border-brand-silver bg-brand-orange-light px-4 py-3 text-sm">{error}</p>
      ) : (
        <OutreachWorkspace campaigns={campaigns} accounts={accounts} />
      )}
    </div>
  );
}
