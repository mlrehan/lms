import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="font-mono text-sm text-muted-foreground">404</p>
      <h1 className="text-xl font-semibold tracking-tight">This page does not exist</h1>
      <p className="max-w-md text-sm text-muted-foreground">
        The link may be out of date, or the record it pointed at may have been deleted.
      </p>
      <Link href="/" className="text-sm font-medium text-primary underline-offset-4 hover:underline">
        Back to the dashboard
      </Link>
    </main>
  );
}
