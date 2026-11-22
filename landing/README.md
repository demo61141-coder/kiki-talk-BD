# কিকি টক — মুখপাতা (Vercel)

স্ট্যাটিক পেজ — `index.html` + `style.css` + `script.js`, কোনো বিল্ড ধাপ নেই।
মোবাইল-ফার্স্ট, ক্রিম/কমলা/কালো রং, CSS keyframes অ্যানিমেশন, দুটি ডেমো
ভয়েস (ট্যাপ করে শোনা যায়), দাম ৳৫০/মাস, ফ্রি ট্রায়ালের বাটন।

## Vercel-এ ডেপ্লয়

1. Vercel-এ নতুন প্রজেক্ট → GitHub রেপো `demo61141-coder/kiki-talk-BD` import করুন।
2. **Root Directory: `landing`** বেছে নিন (এই ফোল্ডারটাই মুখপাতা)।
3. Deploy করুন — ফ্রি সাবডোমেইন পাবেন (যেমন `kiki-talk.vercel.app` ধরনের)।
4. Streamlit অ্যাপ ডেপ্লয় হলে `index.html`-এর ৫ জায়গায় থাকা
   `STREAMLIT_APP_URL` লেখাটা আসল Streamlit লিংক দিয়ে বদলে আবার পুশ করুন।

## ফাইল

- `index.html` — হিরো, ডেমো কণ্ঠ, ধাপ, মূল্য, নিয়ম, FAQ, শেষ CTA।
- `style.css` — ডিজাইন + অ্যানিমেশন (fade-up, বোতামের ঝলক, কার্ড হোভার)।
- `script.js` — স্ক্রলে ভেসে ওঠা (IntersectionObserver, কোনো লাইব্রেরি নয়)।
- `audio/` — দুটি ডেমো ভয়েসের স্থানীয় কপি (আকিব / কিকি বিগ রিরেকর্ড, একই ঢাকা বাক্য)।
  লাইভ পেজে অডিও আসে পাবলিক Hugging Face মডেল রেপো থেকে (GitHub-এ পুশ
  শুধু টেক্সট ফাইল নেয়, তাই wav ফাইল রেপোতে ওঠে না):
  `demoqqq/banglatts-akib/demo_akib.wav` ও
  `demoqqq/banglatts-kiki-big-rerecord/demo_kiki.wav`।
- `vercel.json` — clean URLs।
