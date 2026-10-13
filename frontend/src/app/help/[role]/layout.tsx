import { notFound } from "next/navigation";
import type { ReactNode } from "react";
import { GUIDES, guideBySlug } from "@/content/help";
import { GuideNav } from "@/components/help/guide-nav";

/** Both the guide landing page and every article are built at build time. */
export function generateStaticParams() {
  return GUIDES.map((guide) => ({ role: guide.slug }));
}

export default async function GuideLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ role: string }>;
}) {
  const { role } = await params;
  const guide = guideBySlug(role);
  if (!guide) notFound();

  return (
    <div className="mx-auto w-full max-w-[82rem] px-0 sm:px-6 lg:flex lg:gap-10 lg:py-8">
      <GuideNav guide={guide} />
      <div className="min-w-0 flex-1 px-4 py-6 sm:px-0 lg:py-0">{children}</div>
    </div>
  );
}
