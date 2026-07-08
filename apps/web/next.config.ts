import type { NextConfig } from "next";

// The API origin the browser talks to. In prod the SSE EventSource connects
// directly to this origin (cross-origin), so the CSP connect-src must allow it;
// all other calls go through the same-origin /api proxy.
const API_ORIGIN = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").origin;
  } catch {
    return "http://localhost:8000";
  }
})();

const isDev = process.env.NODE_ENV !== "production";

// Content-Security-Policy. 'unsafe-inline' is required because Next injects
// inline hydration scripts and Tailwind/sonner emit inline styles (a nonce
// would need per-request wiring we don't have). Dev additionally needs
// 'unsafe-eval' + ws: for HMR, so those are gated on NODE_ENV.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  // globals.css imports the Inter webfont from Google Fonts (stylesheet from
  // fonts.googleapis.com, font files from fonts.gstatic.com).
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "img-src 'self' data:",
  `connect-src 'self' ${API_ORIGIN}${isDev ? " ws: http://localhost:8000" : ""}`,
  "font-src 'self' data: https://fonts.gstatic.com",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
];

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone/server.js) — the
  // web Dockerfile copies it and runs `node server.js`, which only exists
  // when standalone output is enabled.
  output: "standalone",
  experimental: {},
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
