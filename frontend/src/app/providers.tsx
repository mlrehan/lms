"use client";

import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { ApiError } from "@/lib/api/client";
import { SessionProvider } from "@/lib/auth/session";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Administrative data changes because a person changed it, not on a
        // timer -- refetching every window focus turns a roster of 500 users
        // into a request every time someone alt-tabs.
        refetchOnWindowFocus: false,
        staleTime: 30_000,
        retry: (failureCount, error) => {
          if (error instanceof ApiError) {
            // 401/403/404/409/422 are answers. Retrying them is three more
            // round trips to be told the same thing, and on a 429 it is
            // actively counterproductive.
            if (error.status < 500) return false;
          }
          return failureCount < 2;
        },
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children }: { children: ReactNode }): ReactNode {
  // Created in state, not at module scope: a module-level client would be
  // shared between every request the server renders, so one user's cached
  // roster could be handed to the next.
  const [queryClient] = useState(makeQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        <SessionProvider>{children}</SessionProvider>
        <Toaster position="bottom-right" richColors closeButton />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
