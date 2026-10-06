export function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center h-full bg-temper-bg text-temper-text gap-4">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <a href="/app/" className="text-temper-accent hover:underline text-sm">
        Back to workflows
      </a>
    </div>
  );
}
