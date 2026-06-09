import type { ReactNode } from 'react'

export function PageHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string
  title: string
  description: string
}) {
  return (
    <header className="rounded-3xl border border-slate-200/80 bg-white/72 p-6 shadow-sm shadow-slate-950/5 backdrop-blur dark:border-slate-800 dark:bg-[#101312]/72">
      <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-emerald-700 dark:text-emerald-400">
        {eyebrow}
      </p>
      <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em] md:text-5xl">{title}</h1>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
    </header>
  )
}

export function Panel({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-3xl border border-dashed border-slate-300 bg-white/52 p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-[#101312]/52 dark:text-slate-400">
      {children}
    </div>
  )
}
