import type { Metadata } from "next";
import { SharedSurface } from "@/components/SharedSurface";

// The token is a credential carried in the URL — never leak it via the Referer
// header when the viewer clicks out or an embedded asset loads (DESIGN-sharing §4g).
export const metadata: Metadata = { referrer: "no-referrer" };

// Next 16: route params are async.
export default async function SharedPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <SharedSurface token={token} />;
}
