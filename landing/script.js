// কিকি টক মুখপাতা — হালকা স্ক্রল অ্যানিমেশন (কোনো লাইব্রেরি নয়)।
(function () {
  var els = document.querySelectorAll(
    ".section, .voice-card, .steps li, .price-card, .rules li, .faq-list details"
  );
  if (!("IntersectionObserver" in window)) {
    els.forEach(function (el) { el.classList.add("visible"); });
    return;
  }
  els.forEach(function (el) { el.classList.add("reveal"); });
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  els.forEach(function (el) { io.observe(el); });
})();
