export function HowToUse() {
  const steps = [
    {
      num: 1,
      title: "Select or Drop File",
      description:
        'Click the "Drag and Drop Your File" button above or drag your PDF / PowerPoint file directly into the upload dropzone.',
    },
    {
      num: 2,
      title: "Automatic Conversion",
      description:
        "Our engine instantly detects watermarks from CamScanner, Gamma, Canva, and stamps with maximum precision and zero quality loss.",
    },
    {
      num: 3,
      title: "Download Output",
      description:
        "Download your converted document or presentation directly to your device with 100% original quality intact.",
    },
  ];

  return (
    <section id="how-to-use" className="my-10 w-full">
      <div className="rounded-3xl bg-[#0B132B] px-6 py-12 text-center text-white shadow-2xl sm:px-10 sm:py-16">
        <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
          How to Use Watermark Remover
        </h2>
        <p className="mt-2 text-sm text-slate-300 sm:text-base">
          Follow these 3 simple steps to process your file or presentation
        </p>

        <div className="mt-10 grid grid-cols-1 gap-5 text-left md:grid-cols-3">
          {steps.map((step) => (
            <div
              key={step.num}
              className="rounded-2xl bg-white/[0.06] p-6 border border-white/10 backdrop-blur-sm transition-all hover:bg-white/[0.09]"
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white shadow-md shadow-brand-500/30">
                {step.num}
              </div>
              <h3 className="mt-4 text-base font-semibold text-white">{step.title}</h3>
              <p className="mt-2 text-xs leading-relaxed text-slate-300">{step.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
