import { useEffect, useLayoutEffect } from "react";

// useLayoutEffect on the client (no SSR warning) so a build's initial hidden
// seed state is set before paint — no flash of the finished element. Falls back
// to useEffect during SSR, where layout effects don't run anyway.
export const useIsoLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;
