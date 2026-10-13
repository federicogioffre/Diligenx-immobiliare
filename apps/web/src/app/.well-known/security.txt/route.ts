// RFC 9116 security.txt — served at /.well-known/security.txt.
// A route handler (not a static file) so it also works in the standalone build.
// A legitimacy signal for reputation scanners and a channel for vulnerability
// reports.

const SITE = "https://diligenx.it";

export const dynamic = "force-static";

export function GET(): Response {
  // Absolute expiry per the spec. Reviewed roughly yearly.
  const expires = "2027-01-01T00:00:00.000Z";
  const body = [
    `Contact: mailto:f.gioffre@nmlex.it`,
    `Expires: ${expires}`,
    `Preferred-Languages: it, en`,
    `Canonical: ${SITE}/.well-known/security.txt`,
    `Policy: ${SITE}/security`,
    "",
  ].join("\n");

  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=86400",
    },
  });
}
