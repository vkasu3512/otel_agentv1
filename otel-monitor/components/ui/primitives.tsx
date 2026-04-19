'use client';
import clsx from 'clsx';

// ── Badge ───────────────────────────────────────────────────────────────────

type BadgeVariant = 'ok' | 'error' | 'warn' | 'info' | 'muted' | 'purple';

const BADGE_CLASSES: Record<BadgeVariant, string> = {
  ok:     'bg-accent-green/10  text-accent-green  border-accent-green/20',
  error:  'bg-accent-red/10    text-accent-red    border-accent-red/20',
  warn:   'bg-accent-amber/10  text-accent-amber  border-accent-amber/20',
  info:   'bg-accent-blue/10   text-accent-blue   border-accent-blue/20',
  purple: 'bg-accent-purple/10 text-accent-purple border-accent-purple/20',
  muted:  'bg-bg-hover         text-text-secondary border-bg-border-mid',
};

export function Badge({
  variant = 'muted', children, className,
}: {
  variant?: BadgeVariant; children: React.ReactNode; className?: string;
}) {
  return (
    <span className={clsx(
      'inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium border tracking-wide',
      BADGE_CLASSES[variant], className,
    )}>
      {children}
    </span>
  );
}

// ── Status Dot ──────────────────────────────────────────────────────────────

export function StatusDot({ active = true }: { active?: boolean }) {
  return (
    <span className={clsx(
      'inline-block w-2 h-2 rounded-full',
      active ? 'bg-accent-green animate-pulse-dot' : 'bg-text-muted',
    )} />
  );
}

// ── Card ────────────────────────────────────────────────────────────────────

export function Card({
  children, className, onClick,
}: {
  children: React.ReactNode; className?: string; onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        'bg-bg-card border border-bg-border rounded-lg',
        onClick && 'cursor-pointer hover:border-bg-border-mid transition-colors duration-150',
        className,
      )}
    >
      {children}
    </div>
  );
}

// ── KPI Card ────────────────────────────────────────────────────────────────

export function KpiCard({
  label, value, sub, subColor = 'muted',
}: {
  label: string; value: string | number; sub?: string; subColor?: 'green' | 'red' | 'muted';
}) {
  const subColorClass = {
    green: 'text-accent-green',
    red:   'text-accent-red',
    muted: 'text-text-muted',
  }[subColor];

  return (
    <Card className="p-4">
      <p className="text-[10px] font-mono uppercase tracking-widest text-text-muted mb-2">{label}</p>
      <p className="text-2xl font-semibold text-text-primary leading-none">{value}</p>
      {sub && <p className={clsx('text-[11px] mt-1.5 font-mono', subColorClass)}>{sub}</p>}
    </Card>
  );
}

// ── Button ──────────────────────────────────────────────────────────────────

type ButtonVariant = 'default' | 'ghost' | 'danger';

const BTN_CLASSES: Record<ButtonVariant, string> = {
  default: 'bg-bg-hover border-bg-border-mid text-text-primary hover:border-accent-blue/40 hover:text-accent-blue',
  ghost:   'bg-transparent border-transparent text-text-secondary hover:text-text-primary hover:bg-bg-hover',
  danger:  'bg-accent-red/10 border-accent-red/20 text-accent-red hover:bg-accent-red/20',
};

export function Button({
  children, onClick, variant = 'default', size = 'sm', className, disabled,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  size?: 'xs' | 'sm' | 'md';
  className?: string;
  disabled?: boolean;
}) {
  const sizeClass = { xs: 'px-2 py-1 text-[11px]', sm: 'px-3 py-1.5 text-xs', md: 'px-4 py-2 text-sm' }[size];
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'inline-flex items-center gap-1.5 border rounded font-mono transition-all duration-150 active:scale-95',
        sizeClass, BTN_CLASSES[variant],
        disabled && 'opacity-40 pointer-events-none',
        className,
      )}
    >
      {children}
    </button>
  );
}

// ── Section Header ──────────────────────────────────────────────────────────

export function SectionHeader({
  title, right,
}: {
  title: string; right?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between mb-3">
      <span className="text-[10px] font-mono uppercase tracking-widest text-text-muted">{title}</span>
      {right}
    </div>
  );
}

// ── Empty State ─────────────────────────────────────────────────────────────

export function EmptyState({ msg }: { msg: string }) {
  return (
    <div className="flex items-center justify-center py-12">
      <span className="text-text-muted font-mono text-xs">{msg}</span>
    </div>
  );
}
