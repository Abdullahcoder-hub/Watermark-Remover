import { FileCheck, Laptop, Lock, Zap } from "lucide-react";

export function FeatureGrid() {
  const features = [
    {
      icon: Zap,
      iconColor: "text-blue-600 bg-blue-50 border-blue-100",
      title: "Fast Processing",
      description:
        "High-speed local engine ensures your document watermarks are detected and cleaned in seconds.",
    },
    {
      icon: Lock,
      iconColor: "text-emerald-600 bg-emerald-50 border-emerald-100",
      title: "256-Bit SSL Security",
      description:
        "Your files are processed locally on your machine and purged automatically. No data ever leaves your device.",
    },
    {
      icon: Laptop,
      iconColor: "text-indigo-600 bg-indigo-50 border-indigo-100",
      title: "All Platforms",
      description:
        "Runs smoothly on Windows, Mac, Linux, Android, iOS, and all modern web browsers without installation.",
    },
    {
      icon: FileCheck,
      iconColor: "text-amber-600 bg-amber-50 border-amber-100",
      title: "Original Quality",
      description:
        "Preserves document formatting, high-resolution images, fonts, and slide layout structures flawlessly.",
    },
  ];

  return (
    <section id="features" className="w-full py-10">
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {features.map((f, i) => (
          <div
            key={i}
            className="group rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:border-brand-300 hover:shadow-md"
          >
            <div
              className={`mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl border ${f.iconColor}`}
            >
              <f.icon className="h-5 w-5" />
            </div>
            <h3 className="text-base font-semibold text-slate-900">{f.title}</h3>
            <p className="mt-2 text-xs leading-relaxed text-slate-500">{f.description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
