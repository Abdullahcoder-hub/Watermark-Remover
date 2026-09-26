import { ShieldCheck, Sparkles, Wrench, Zap } from "lucide-react";

export function Footer() {
  return (
    <footer className="w-full border-t border-slate-200 bg-white pt-12 pb-10">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6 pb-8 border-b border-slate-100">
          {/* Brand Info */}
          <div className="space-y-2 text-center md:text-left">
            <div className="flex items-center justify-center md:justify-start gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm shadow-brand-500/20">
                <Wrench className="h-4 w-4" />
              </div>
              <span className="text-lg font-bold tracking-tight text-slate-900">
                The Developers Hub
              </span>
            </div>
            <p className="text-sm text-slate-500 max-w-md">
              Fast, privacy-first, and token-free document watermark removal for PDF and PowerPoint presentations.
            </p>
          </div>

          {/* Developer Tag & Active Features */}
          <div className="flex flex-wrap items-center justify-center gap-3">
            <span className="inline-flex items-center gap-1.5 rounded-xl bg-brand-50 px-3.5 py-2 text-xs font-bold text-brand-700 border border-brand-100">
              <Sparkles className="h-3.5 w-3.5 text-brand-500" />
              Developed by Abdullah Waqar
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 border border-emerald-100">
              <ShieldCheck className="h-3.5 w-3.5" />
              100% Local & Private
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-xl bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 border border-blue-100">
              <Zap className="h-3.5 w-3.5" />
              0 API Tokens Used
            </span>
          </div>
        </div>

        {/* ========================================================================= */}
        {/* FUTURE FOOTER COLUMNS: Uncomment when multi-page site directories are added */}
        {/*
        <div className="grid grid-cols-1 gap-10 md:grid-cols-4 my-8">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Categories</h3>
            <ul className="mt-4 space-y-2 text-sm text-slate-600">
              <li><a href="#pdf-tools" className="hover:text-brand-600">PDF Tools</a></li>
              <li><a href="#pptx-tools" className="hover:text-brand-600">PowerPoint Tools</a></li>
              <li><a href="#image-tools" className="hover:text-brand-600">Image Tools</a></li>
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Legal</h3>
            <ul className="mt-4 space-y-2 text-sm text-slate-600">
              <li><a href="#privacy" className="hover:text-brand-600">Privacy Policy</a></li>
              <li><a href="#terms" className="hover:text-brand-600">Terms of Service</a></li>
            </ul>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Company</h3>
            <ul className="mt-4 space-y-2 text-sm text-slate-600">
              <li><a href="#about" className="hover:text-brand-600">About Us</a></li>
              <li><a href="#contact" className="hover:text-brand-600">Contact</a></li>
            </ul>
          </div>
        </div>
        */}
        {/* ========================================================================= */}

        {/* Copyright Bar */}
        <div className="pt-6 text-center text-xs text-slate-400">
          <p>© 2026 The Developers Hub. Developed by Abdullah Waqar. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
