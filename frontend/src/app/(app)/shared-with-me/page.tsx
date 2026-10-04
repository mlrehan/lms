"use client";

import { useQuery } from "@tanstack/react-query";
import { Download, Share2 } from "lucide-react";
import { toast } from "sonner";
import { api, downloadFile, segment } from "@/lib/api/client";
import type { ResourceSummary, SharedResourceResponse } from "@/lib/api/types";
import { PageHeader } from "@/components/page-header";
import {
  DriveToolbar,
  DriveView,
  type DriveActions,
  useDriveLayout,
} from "@/components/domain/resources/drive-view";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { useDisplayTimeZone } from "@/lib/preferences";
import { formatDateTime } from "@/lib/format/datetime";

/**
 * Files shared with this person directly.
 *
 * Rendered through the **same** `DriveView` as Resources, so a shared file looks
 * and behaves like any other file rather than like a row in a different product.
 * That is the point of sharing a component rather than styling two screens to
 * match: they cannot drift apart.
 *
 * `canWrite` is false throughout. A share grants access to somebody else's file;
 * it does not make the recipient its owner, so there is no rename, no move and
 * no bin here — and the actions the view offers are exactly the ones the API
 * will honour.
 */

/**
 * A shared record described as a file the view can draw.
 *
 * `SharedResourceResponse` carries no type, size or MIME — the share endpoint
 * reports the *grant*, not the file. Rather than invent values, the unknown
 * fields stay null and the view renders them as "—": a plausible-looking
 * "0 B" would be a fabrication, and the generic icon is honest about what is
 * known.
 */
function asResource(share: SharedResourceResponse): ResourceSummary {
  return {
    public_id: share.resource_id,
    name: share.resource_name ?? "Untitled",
    resource_type: "Document",
    mime_type: null,
    size: null,
    is_restricted: false,
    created_at: share.created_at,
  };
}

export default function SharedWithMePage() {
  const timeZone = useDisplayTimeZone();
  const [layout, setLayout] = useDriveLayout("list");

  const { data, isPending, error, refetch } = useQuery({
    queryKey: ["shared-with-me"],
    queryFn: () => api.get<SharedResourceResponse[]>("/shared-with-me"),
  });

  const shares = data ?? [];

  function download(resourceId: string, name: string) {
    void downloadFile(`/resources/${segment(resourceId)}/download`, name).catch((caught) =>
      toast.error(caught instanceof Error ? caught.message : "Download failed."),
    );
  }

  const noop = () => undefined;
  const actions: DriveActions = {
    onOpenFolder: noop,
    // There is no owner-style detail panel here: the recipient may read the
    // file, not administer it. Opening it downloads it, which is the only
    // thing the grant actually permits.
    onOpenResource: (resource) => download(resource.public_id, resource.name ?? "resource"),
    onMoveResource: noop,
    onUploadFiles: noop,
    onDownload: (resource) => download(resource.public_id, resource.name ?? "resource"),
    onCopy: noop,
    onShare: noop,
    onDelete: noop,
    onRestore: noop,
    onRenameFolder: noop,
    onDeleteFolder: noop,
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Shared with me"
        description="Files someone shared with you directly. Anything reaching you through a course, batch or session grant appears under Resources instead."
      />

      <DriveToolbar layout={layout} onLayoutChange={setLayout}>
        <span className="flex items-center gap-2 text-base font-semibold">
          <Share2 className="size-4 text-muted-foreground" aria-hidden />
          Shared with me
        </span>
      </DriveToolbar>

      {isPending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <>
          <DriveView
            layout={layout}
            folders={[]}
            resources={shares.map(asResource)}
            canWrite={false}
            inBin={false}
            emptyMessage="Nothing has been shared with you directly."
            actions={actions}
            formatDate={(iso) => formatDateTime(iso, { timeZone })}
          />

          {shares.length > 0 ? (
            <section className="rounded-xl border border-border-subtle p-3">
              {/* Who shared each file and what it permits. `SharedResourceResponse`
                  carries this and the file view cannot show it, so it is stated
                  here rather than dropped -- "can I download this?" is the first
                  thing a recipient wants to know. */}
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Who shared these, and what you may do
              </h3>
              <ul className="space-y-1 text-xs text-muted-foreground">
              {shares.map((share) => (
                <li key={`${share.resource_id}-${share.created_at}`}>
                  <span className="font-medium text-foreground">
                    {share.resource_name ?? "Untitled"}
                  </span>{" "}
                  — shared by {share.shared_by_username ?? "someone"} on{" "}
                  {formatDateTime(share.created_at, { timeZone })}
                  {share.level ? ` · ${share.level.toLowerCase()} access` : ""}
                  <button
                    type="button"
                    className="ml-2 inline-flex items-center gap-1 hover:underline"
                    onClick={() =>
                      download(share.resource_id, share.resource_name ?? "resource")
                    }
                  >
                    <Download className="size-3" aria-hidden /> Download
                  </button>
                </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
