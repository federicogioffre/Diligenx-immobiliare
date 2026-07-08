import type { MetadataRoute } from "next";

const SITE = "https://diligenx.it";

// Public, indexable pages — mirrors the public routes in src/middleware.ts.
const PUBLIC_PATHS = [
  "/",
  "/login",
  "/privacy",
  "/cookies",
  "/terms",
  "/dpa",
  "/security",
];

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_PATHS.map((path) => ({
    url: `${SITE}${path === "/" ? "" : path}`,
    changeFrequency: "monthly",
    priority: path === "/" ? 1 : 0.6,
  }));
}
