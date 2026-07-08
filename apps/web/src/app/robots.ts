import type { MetadataRoute } from "next";

const SITE = "https://diligenx.it";

// Public robots policy. The app's private areas are gated server-side by the
// middleware; only the public marketing/legal pages are meaningfully indexable.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Keep authenticated app areas out of the index.
      disallow: ["/dashboard", "/deals", "/api"],
    },
    sitemap: `${SITE}/sitemap.xml`,
    host: SITE,
  };
}
