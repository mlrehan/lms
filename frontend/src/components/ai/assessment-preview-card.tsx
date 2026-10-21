"use client";

import Link from "next/link";
import { BookOpen, CheckCircle, ExternalLink, HelpCircle, Layers, Send } from "lucide-react";
import { Badge } from "@/components/ui/primitives";
import { Button } from "@/components/ui/button";

export interface AssessmentDraftData {
  assessment_id: string;
  title: string;
  status: string;
  question_count?: number;
  total_marks?: number;
  scope?: string;
  course?: string;
  batch?: string;
  message?: string;
}

interface AssessmentPreviewCardProps {
  draft: AssessmentDraftData;
  onPublishClick?: (draft: AssessmentDraftData) => void;
}

export function AssessmentPreviewCard({ draft, onPublishClick }: AssessmentPreviewCardProps) {
  const isDraft = draft.status?.toUpperCase() === "DRAFT";

  return (
    <div className="my-2.5 overflow-hidden rounded-xl border border-primary/20 bg-muted/30 p-3.5 shadow-xs transition-all hover:border-primary/40">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Badge tone={isDraft ? "warning" : "success"} className="text-2xs px-1.5 py-0.5">
              {draft.status || "DRAFT"}
            </Badge>
            {draft.scope && (
              <span className="text-2xs text-muted-foreground uppercase font-medium">
                {draft.scope} Scope
              </span>
            )}
          </div>
          <h4 className="mt-1 font-semibold text-sm text-foreground truncate" title={draft.title}>
            {draft.title}
          </h4>
        </div>
      </div>

      <div className="mt-2.5 grid grid-cols-2 gap-2 border-y border-border-subtle py-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <HelpCircle className="size-3.5 text-primary shrink-0" />
          <span>{draft.question_count ?? "?"} Questions</span>
        </div>
        <div className="flex items-center gap-1.5">
          <CheckCircle className="size-3.5 text-primary shrink-0" />
          <span>{draft.total_marks ?? "?"} Total Marks</span>
        </div>
        {draft.course && (
          <div className="flex items-center gap-1.5 col-span-2 truncate">
            <BookOpen className="size-3.5 text-muted-foreground shrink-0" />
            <span className="truncate">{draft.course}</span>
          </div>
        )}
        {draft.batch && (
          <div className="flex items-center gap-1.5 col-span-2 truncate">
            <Layers className="size-3.5 text-muted-foreground shrink-0" />
            <span className="truncate">Batch: {draft.batch}</span>
          </div>
        )}
      </div>

      <div className="mt-3 flex items-center justify-end gap-2">
        <Link
          href={`/quizzes/${draft.assessment_id}`}
          className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          target="_blank"
        >
          <span>Open in Editor</span>
          <ExternalLink className="size-3" />
        </Link>
        {isDraft && onPublishClick && (
          <Button
            size="sm"
            variant="primary"
            className="h-7 text-xs px-2.5 gap-1"
            onClick={() => onPublishClick(draft)}
          >
            <Send className="size-3" />
            Publish Live
          </Button>
        )}
      </div>
    </div>
  );
}
