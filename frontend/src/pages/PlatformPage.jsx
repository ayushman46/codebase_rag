const PlatformPage = () => (
  <main className="content-shell flex min-h-[calc(100svh-5rem)] items-center justify-center py-12 sm:py-16">
    <section className="mx-auto max-w-3xl text-center">
      <span className="text-caption font-semibold uppercase tracking-widest text-ember-orange">The platform</span>
      <h1 className="heading-lg page-title mt-5 text-ink-black">A focused workspace for understanding unfamiliar systems.</h1>
      <p className="mx-auto mt-7 max-w-2xl text-lg leading-relaxed text-pewter">
        Codebase Intel turns a public GitHub repository into a private, searchable workspace. It indexes source files, symbols, and line ranges; combines semantic and keyword retrieval to find relevant evidence; and returns clear answers with citations to the code that supports them. Each workspace is tied to the signed-in user.
      </p>
    </section>
  </main>
);

export default PlatformPage;
