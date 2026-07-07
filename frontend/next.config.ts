import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    // The share token is a bearer credential in the URL — belt-and-braces beyond
    // the page's no-referrer/noindex metadata, as real response headers.
    return [
      {
        source: "/share/:path*",
        headers: [
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Robots-Tag", value: "noindex, nofollow" },
        ],
      },
    ];
  },
};

export default nextConfig;
