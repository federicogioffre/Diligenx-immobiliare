import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "DealMind AI",
  description: "AI-powered deal intelligence platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
