import { FileSpreadsheet, FileText, MonitorPlay, Presentation, ScanText, Sparkles } from "lucide-react";

export function QuickTools() {
  const tools = [
    {
      icon: FileSpreadsheet,
      name: "Excel to PDF",
      desc: "Convert Excel sheets (.xls, .xlsx) to clean formatted PDF documents.",
      color: "text-emerald-600 bg-emerald-50",
    },
    {
      icon: Presentation,
      name: "PDF to PowerPoint",
      desc: "Turn PDF slides and documents into fully editable PowerPoint (.pptx).",
      color: "text-orange-600 bg-orange-50",
    },
    {
      icon: MonitorPlay,
      name: "PowerPoint to PDF",
      desc: "Convert PowerPoint presentations into high-resolution, secure PDF files.",
      color: "text-blue-600 bg-blue-50",
    },
    {
      icon: ScanText,
      name: "Scanned PDF OCR",
      desc: "Extract text and make scanned document pages completely searchable.",
      color: "text-purple-600 bg-purple-50",
    },
    {
      icon: FileText,
      name: "Word to PDF",
      desc: "Convert Word documents (.doc, .docx) into standard PDF format seamlessly.",
      color: "text-indigo-600 bg-indigo-50",
    },
    {
      icon: Sparkles,
      name: "Scanned Inpainter",
      desc: "AI Telea inpainting to seamlessly erase baked-in watermarks from scans.",
      color: "text-teal-600 bg-teal-50",
    },
  ];

  return (
    <section id="tools" className="my-10 w-full">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
            Popular Document & Presentation Tools
          </h2>
          <p className="mt-1 text-xs text-slate-500 sm:text-sm">
            Explore more free, privacy-first conversion and cleaning tools by The Developers Hub.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tools.map((t, idx) => (
          <div
            key={idx}
            className="group flex items-start gap-4 rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-md cursor-pointer"
          >
            <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${t.color}`}>
              <t.icon className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-900 group-hover:text-brand-600 transition-colors">
                {t.name}
              </h3>
              <p className="mt-1 text-xs text-slate-500 leading-relaxed">{t.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
