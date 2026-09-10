"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { api, downloadFile, segment } from "@/lib/api/client";
import type { SharedResourceResponse } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { Column, DataTable } from "@/components/ui/data-table";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

export default function SharedWithMePage() {
  const timeZone = useDisplayTimeZone();

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["shared-with-me"],
    queryFn: () => api.get<SharedResourceResponse[]>("/shared-with-me"),
  });

  const columns: Column<SharedResourceResponse>[] = [
    {
      key: "name",
      header: "Resource",
      cell: (row) => <span className="font-medium">{row.resource_name ?? "Untitled"}</span>,
    },
    {
      key: "by",
      header: "Shared by",
      cell: (row) => row.shared_by_username ?? "—",
    },
    {
      key: "when",
      header: "Shared",
      secondary: true,
      cell: (row) => formatDateTime(row.created_at, { timeZone }),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      align: "right",
      cell: (row) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            void downloadFile(
              `/resources/${segment(row.resource_id)}/download`,
              row.resource_name ?? "resource",
            ).catch((caught) =>
              toast.error(caught instanceof Error ? caught.message : "Download failed."),
            )
          }
        >
          <Download /> Download
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Shared with me"
        description="Files someone shared with you directly. Anything reaching you through a course, batch or session grant appears under Resources instead."
      />
      <Card>
        {isPending ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : (
          <DataTable
            columns={columns}
            rows={data ?? []}
            rowKey={(row) => `${row.resource_id}-${row.created_at}`}
            emptyMessage="Nothing has been shared with you directly."
          />
        )}
      </Card>
    </div>
  );
}
