"use client";

import { useState } from "react";
import Link from "next/link";
import { BookOpen, Check, Link2 } from "lucide-react";
import { guideForRoles } from "@/content/help";
import { cn } from "@/lib/utils";

/**
 * The "Help" group in the sidebar.
 *
 * **The guide follows the role the server reports**, not the screens the
 * sidebar happens to be rendering. A Super Admin gets the Super Admin guide;
 * somebody holding several roles gets the one that covers what they actually
 * see. Roles come from `/auth/me`, so this cannot be changed by editing
 * anything in the browser -- though it does not need to be secure, because
 * the guide is public anyway.
 *
 * Nothing is rendered for a role whose guide is not written yet. A sidebar
 * link to an empty guide teaches people that the help is useless.
 *
 * The link opens in a new tab: somebody reading an instruction usually wants
 * to follow it on the screen they were already on.
 */
export function HelpNavItem({
  roles,
  onNavigate,
}: {
  roles: readonly string[];
  onNavigate?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const guide = guideForRoles(roles);
  if (!guide) return null;

  const path = `/help/${guide.slug}`;

  async function copyLink() {
    const url = `${window.location.origin}${path}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this link:", url);
    }
  }

  return (
    <div className="space-y-1">
      <p className="eyebrow px-2.5 pb-0.5">Help</p>
      <ul className="space-y-0.5">
        <li className="flex items-center gap-1">
          <Link
            href={path}
            target="_blank"
            rel="noopener noreferrer"
            onClick={onNavigate}
            title={`${guide.title} — opens in a new tab`}
            className={cn(
              "group flex min-w-0 flex-1 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px]",
              "font-normal text-muted-foreground transition-all duration-200 ease-out",
              "hover:bg-surface/70 hover:text-foreground",
            )}
          >
            <BookOpen
              className="size-4 shrink-0 text-subtle-foreground transition-colors duration-200 group-hover:text-muted-foreground"
              aria-hidden
            />
            {/*
              The rail is narrow, and "Super Admin User Guide" truncates to
              "Super Admin User G...". The role plus "guide" fits, stays
              specific to who is reading, and the full title is one hover away.
            */}
            <span className="truncate">{guide.role} guide</span>
          </Link>
          <button
            type="button"
            onClick={() => void copyLink()}
            title="Copy a link to this guide that anyone can open"
            aria-label="Copy a link to this guide"
            className="shrink-0 rounded-md p-1.5 text-subtle-foreground transition-colors hover:bg-surface/70 hover:text-foreground"
          >
            {copied ? (
              <Check className="size-3.5 text-success" aria-hidden />
            ) : (
              <Link2 className="size-3.5" aria-hidden />
            )}
          </button>
        </li>
      </ul>
    </div>
  );
}
