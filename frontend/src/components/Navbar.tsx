import { Menu, Sparkles, Wrench, X } from "lucide-react";
import { useEffect, useState } from "react";

import { checkHealth } from "../services/api";

export function Navbar() {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [pingMs, setPingMs] = useState<number | null>(null);
  const [isOnline, setIsOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    let refreshTimeout: ReturnType<typeof setTimeout> | null = null;

    const refreshPing = async () => {
      const ping = await checkHealth();
      if (!active) return;

      setPingMs(ping);
      setIsOnline(ping !== null);
      refreshTimeout = setTimeout(() => void refreshPing(), 5000);
    };

    void refreshPing();

    return () => {
      active = false;
      if (refreshTimeout !== null) clearTimeout(refreshTimeout);
    };
  }, []);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-slate-200/80 bg-white/90 backdrop-blur-md">
      <div className="mx-auto flex min-h-16 max-w-6xl flex-wrap items-center justify-between gap-y-2 px-3 py-2 sm:h-16 sm:flex-nowrap sm:px-6 sm:py-0 lg:px-8">
        {/* Brand Logo */}
        <a href="/" className="group flex shrink-0 items-center gap-2 sm:gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-tr from-brand-700 to-brand-500 text-white shadow-md shadow-brand-500/20 transition-transform group-hover:scale-105 sm:h-10 sm:w-10">
            <Wrench className="h-4 w-4 sm:h-5 sm:w-5" />
          </div>
          <div className="flex flex-col">
            <span className="whitespace-nowrap text-sm font-bold leading-tight tracking-tight text-slate-900 transition-colors group-hover:text-brand-600 sm:text-lg">
              The Developers Hub
            </span>
            <span className="whitespace-nowrap text-[8px] font-medium uppercase tracking-wider text-slate-400 sm:text-[10px]">
              Developed by Abdullah Waqar
            </span>
          </div>
        </a>

        <button
          type="button"
          className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 transition-colors hover:bg-slate-100 hover:text-brand-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 sm:hidden"
          aria-label={isMobileMenuOpen ? "Close navigation menu" : "Open navigation menu"}
          aria-expanded={isMobileMenuOpen}
          aria-controls="primary-navigation"
          onClick={() => setIsMobileMenuOpen((isOpen) => !isOpen)}
        >
          {isMobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>

        {/* Navigation Links - Only showing active working features */}
        <nav
          id="primary-navigation"
          className={`${isMobileMenuOpen ? "flex" : "hidden"} w-full items-center justify-center gap-6 border-t border-slate-100 pt-2 sm:flex sm:w-auto sm:border-0 sm:pt-0`}
        >
          <a
            href="#how-to-use"
            className="whitespace-nowrap text-sm font-medium text-slate-600 transition-colors hover:text-brand-600 focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            onClick={() => setIsMobileMenuOpen(false)}
          >
            How It Works
          </a>
          <a
            href="#features"
            className="whitespace-nowrap text-sm font-medium text-slate-600 transition-colors hover:text-brand-600 focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            onClick={() => setIsMobileMenuOpen(false)}
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
        <div className="hidden shrink-0 items-center gap-3 sm:flex">
          <span
            className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-semibold ${
              isOnline === null
                ? "border-slate-200 bg-slate-50 text-slate-500"
                : isOnline
                  ? "border-emerald-200/80 bg-emerald-50 text-emerald-700"
                  : "border-rose-200 bg-rose-50 text-rose-700"
            }`}
            role="status"
            aria-live="polite"
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                isOnline === null ? "bg-slate-400" : isOnline ? "bg-emerald-500" : "bg-rose-500"
              }`}
            />
            {isOnline === null ? "Checking API..." : isOnline ? `API ${pingMs} ms` : "API offline"}
          </span>
          <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-emerald-200/80 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
            <Sparkles className="h-3 w-3 text-emerald-600" />
            PDF & PPTX Engine
          </span>
        </div>
      </div>
    </header>
  );
}
