import { NextRequest } from "next/server";

export async function GET(request: NextRequest): Promise<Response> {
  const apiUrl = process.env.API_URL;
  if (!apiUrl) {
    return new Response("API_URL is not set", { status: 500 });
  }
  const upstream = new URL("/export.csv", `${apiUrl.replace(/\/$/, "")}/`);
  request.nextUrl.searchParams.forEach((value, key) => {
    upstream.searchParams.append(key, value);
  });
  const response = await fetch(upstream.toString(), { cache: "no-store" });
  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": "attachment; filename=organizations.csv",
    },
  });
}
