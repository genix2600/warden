export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="text-[19px] font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && (
          <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-ink-2">{subtitle}</p>
        )}
      </div>
      {actions}
    </header>
  );
}
