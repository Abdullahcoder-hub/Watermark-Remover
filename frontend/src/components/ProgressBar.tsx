interface ProgressBarProps {
  percent: number;
  label?: string;
}

export function ProgressBar({ percent, label }: ProgressBarProps) {
  return (
    <div className="w-full">
      {label && <p className="mb-2 text-sm text-ink/70">{label}</p>}
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2 w-full overflow-hidden rounded-full bg-ink/10"
      >
        <div className="h-full rounded-full bg-accent transition-all duration-300" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
