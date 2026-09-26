import { Sparkles, Wrench } from "lucide-react";

export function Navbar() {
  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200/80 bg-white/90 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand Logo */}
        <a href="/" className="flex items-center gap-3 group">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-brand-700 to-brand-500 text-white shadow-md shadow-brand-500/20 transition-transform group-hover:scale-105">
            <Wrench className="h-5 w-5" />
          </div>
          <div className="flex flex-col">
            <span className="text-lg font-bold tracking-tight text-slate-900 group-hover:text-brand-600 transition-colors">
              The Developers Hub
            </span>
            <span className="text-[10px] font-medium uppercase tracking-wider text-slate-400">
              Developed by Abdullah Waqar
            </span>
          </div>
        </a>

        {/* Navigation Links - Only showing active working features */}
        <nav className="flex items-center gap-6">
          <a
            href="#how-to-use"
            className="text-sm font-medium text-slate-600 transition-colors hover:text-brand-600"
          >
            How It Works
          </a>
          <a
            href="#features"
            className="text-sm font-medium text-slate-600 transition-colors hover:text-brand-600"
          >
            Features
          </a>

          {/* ========================================================================= */}
          {/* FUTURE LINKS: Uncomment when additional categories / tools are built      */}
          {/*
          <a href="#categories" className="text-sm font-medium text-slate-600 hover:text-brand-600">
            Categories
          </a>
          <a href="#all-tools" className="text-sm font-medium text-slate-600 hover:text-brand-600">
            All Tools
          </a>
          */}
          {/* ========================================================================= */}
        </nav>

        {/* Right Active Status Badge */}
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 border border-emerald-200/80">
            <Sparkles className="h-3 w-3 text-emerald-600" />
            PDF & PPTX Engine
          </span>
        </div>
      </div>
    </header>
  );
}
