import { NextRequest } from "next/server";

export async function POST(request: NextRequest): Promise<Response> {
  const apiUrl = process.env.API_URL;
  if (!apiUrl) {
    return new Response("API_URL is not set", { status: 500 });
  }
  const upstream = new URL("/outreach/campaigns", `${apiUrl.replace(/\/$/, "")}/`);
  const response = await fetch(upstream.toString(), {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
  });
  return new Response(response.body, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}
