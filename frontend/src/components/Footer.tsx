import { Wrench } from "lucide-react";

export function Footer() {
  return (
    <footer className="w-full border-t border-slate-200 bg-white pt-16 pb-12">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-10 md:grid-cols-5">
          {/* Brand Col */}
          <div className="md:col-span-2 space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm shadow-brand-500/20">
                <Wrench className="h-4 w-4" />
              </div>
              <span className="text-lg font-bold tracking-tight text-slate-900">
                The Developers Hub
              </span>
            </div>
            <p className="text-sm leading-relaxed text-slate-500 max-w-sm">
              126+ Free Online Tools for PDF, PPTX, Images, AI, Developers & More. Fast, Secure, and 100% Free.
            </p>
            <div className="pt-2">
              <span className="inline-block rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700">
                Developed by Abdullah Waqar
              </span>
            </div>
          </div>

          {/* Categories */}
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Categories</h3>
            <ul className="mt-4 space-y-2.5 text-sm text-slate-600">
              <li>
                <a href="#tools" className="hover:text-brand-600 transition-colors">
                  PDF Tools
                </a>
              </li>
              <li>
                <a href="#tools" className="hover:text-brand-600 transition-colors">
                  PowerPoint Tools
                </a>
              </li>
              <li>
                <a href="#tools" className="hover:text-brand-600 transition-colors">
                  Image Tools
                </a>
              </li>
              <li>
                <a href="#tools" className="hover:text-brand-600 transition-colors">
                  AI Tools
                </a>
              </li>
              <li>
                <a href="#tools" className="hover:text-brand-600 transition-colors">
                  Developer Tools
                </a>
              </li>
            </ul>
          </div>

          {/* Legal */}
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Legal</h3>
            <ul className="mt-4 space-y-2.5 text-sm text-slate-600">
              <li>
                <a href="#privacy" className="hover:text-brand-600 transition-colors">
                  Privacy Policy
                </a>
              </li>
              <li>
                <a href="#terms" className="hover:text-brand-600 transition-colors">
                  Terms of Service
                </a>
              </li>
              <li>
                <a href="#disclaimer" className="hover:text-brand-600 transition-colors">
                  Disclaimer
                </a>
              </li>
            </ul>
          </div>

          {/* Company */}
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Company</h3>
            <ul className="mt-4 space-y-2.5 text-sm text-slate-600">
              <li>
                <a href="#about" className="hover:text-brand-600 transition-colors">
                  About Us
                </a>
              </li>
              <li>
                <a href="#contact" className="hover:text-brand-600 transition-colors">
                  Contact
                </a>
              </li>
              <li>
                <a href="#blog" className="hover:text-brand-600 transition-colors">
                  Blog
                </a>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom Bar */}
        <div className="mt-12 border-t border-slate-100 pt-8 text-center text-xs text-slate-500">
          <p>© 2026 The Developers Hub. Developed by Abdullah Waqar. All rights reserved.</p>
        </div>
      </div>
    </footer>
  );
}
