"use client";

import { useState, useTransition, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { OutreachAccount, OutreachCampaign } from "@/lib/types";

function campaignKey(campaign: OutreachCampaign, index: number): string {
  if (campaign.id !== undefined) {
    return String(campaign.id);
  }
  return `campaign-${index}`;
}

function statusClass(status: string | undefined): string {
  const value = (status ?? "").toLowerCase();
  if (value.includes("pause") || value === "paused") {
    return "bg-brand-orange text-black";
  }
  if (value.includes("active") || value.includes("sending")) {
    return "bg-black text-white";
  }
  return "bg-brand-silver text-black";
}

export function OutreachWorkspace({
  campaigns,
  accounts,
}: {
  campaigns: OutreachCampaign[];
  accounts: OutreachAccount[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [name, setName] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  function refresh() {
    startTransition(() => {
      router.refresh();
    });
  }

  async function createCampaign(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "") {
      return;
    }
    setMessage(null);
    const response = await fetch("/api/outreach/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: trimmed }),
    });
    if (!response.ok) {
      setMessage(`Create failed (${response.status})`);
      return;
    }
    setName("");
    refresh();
  }

  async function setCampaignState(campaignId: number | string, action: "start" | "pause") {
    setMessage(null);
    const response = await fetch(
      `/api/outreach/campaigns/${encodeURIComponent(String(campaignId))}/${action}`,
      { method: "POST" },
    );
    if (!response.ok) {
      setMessage(`${action} failed (${response.status})`);
      return;
    }
    refresh();
  }

  return (
    <div className="space-y-6">
      {message ? (
        <p className="rounded-md border border-brand-silver bg-brand-orange-light px-4 py-3 text-sm">
          {message}
        </p>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Create campaign</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end" onSubmit={(event) => void createCampaign(event)}>
            <div className="min-w-0 w-full flex-1 space-y-1 sm:min-w-[16rem]">
              <Label htmlFor="campaign-name">Name</Label>
              <Input
                id="campaign-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Campaign name"
              />
            </div>
            <Button type="submit" className="w-full sm:w-auto" disabled={pending || name.trim() === ""}>
              Create
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Campaigns</CardTitle>
        </CardHeader>
        <CardContent>
          {campaigns.length === 0 ? (
            <p className="text-sm text-neutral-500">No campaigns in this workspace.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-black text-left text-xs font-bold uppercase tracking-wide text-white">
                  <tr>
                    <th className="px-3 py-2">Name</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {campaigns.map((campaign, index) => (
                    <tr key={campaignKey(campaign, index)} className="border-t border-brand-silver">
                      <td className="px-3 py-2 font-medium">{campaign.name ?? "—"}</td>
                      <td className="px-3 py-2">
                        <Badge className={statusClass(campaign.status)}>{campaign.status ?? "—"}</Badge>
                      </td>
                      <td className="px-3 py-2">
                        {campaign.id !== undefined ? (
                          <div className="flex flex-col gap-2 sm:flex-row">
                            <Button
                              type="button"
                              size="sm"
                              disabled={pending}
                              onClick={() => void setCampaignState(campaign.id as number | string, "start")}
                            >
                              Start
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="black"
                              disabled={pending}
                              onClick={() => void setCampaignState(campaign.id as number | string, "pause")}
                            >
                              Pause
                            </Button>
                          </div>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sending accounts</CardTitle>
        </CardHeader>
        <CardContent>
          {accounts.length === 0 ? (
            <p className="text-sm text-neutral-500">No sending accounts.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-black text-left text-xs font-bold uppercase tracking-wide text-white">
                  <tr>
                    <th className="px-3 py-2">Email</th>
                    <th className="px-3 py-2">Active</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((account, index) => (
                    <tr key={account.id !== undefined ? String(account.id) : `account-${index}`} className="border-t border-brand-silver">
                      <td className="max-w-[14rem] break-all px-3 py-2 sm:max-w-none">{account.email ?? "—"}</td>
                      <td className="px-3 py-2">
                        {account.isActive === undefined ? "—" : account.isActive ? "Yes" : "No"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
