# ⚡ Synthia AI Agent
### *Personal Local AI Command Bridge · অফলাইন-ফার্স্ট পার্সোনাল এআই অ্যাসিস্ট্যান্ট*

<p align="center">
  <img src="synthia/assets/synthia.ico" alt="Synthia Logo" width="96" height="96" />
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg?logo=python" alt="Python Version" /></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg?logo=fastapi" alt="FastAPI" /></a>
  <a href="https://ollama.com/"><img src="https://img.shields.io/badge/Ollama-Offline%20First-black.svg?logo=ollama" alt="Ollama" /></a>
  <a href="https://github.com/sa-noman/Synthia-Ai-Agent"><img src="https://img.shields.io/badge/OS-Windows%2010%2F11-0078D6.svg?logo=windows" alt="Windows Support" /></a>
  <a href="https://github.com/sa-noman/Synthia-Ai-Agent/stargazers"><img src="https://img.shields.io/github/stars/sa-noman/Synthia-Ai-Agent?style=social" alt="Stars" /></a>
</p>

---

## 🌟 Overview (পরিচিতি)

**Synthia** হলো সম্পূর্ণ অফলাইন-ফার্স্ট ও হাইব্রিড আর্কিটেকচারে তৈরি একটি আধুনিক পার্সোনাল এআই কমান্ড ব্রিজ। এটি লোকাল এলএলএম (Ollama - Gemma 4) দিয়ে ইন্টারনেট ছাড়াই স্বয়ংক্রিয়ভাবে চলতে পারে, আবার ইন্টারনেট থাকলে বিভিন্ন ক্লাউড মডেলের (Google Gemini, Groq, Cerebras, ইত্যাদি) ফ্রি এপিআই স্বয়ংক্রিয়ভাবে ব্যবহার করতে পারে। 

বাংলা ও ইংরেজি উভয় ভাষায় নির্ভুল ভয়েস কমান্ড রিকগনিশন (STT) এবং প্রাকৃতিক বাংলাদেশি নিউরাল ভয়েস (TTS) সমৃদ্ধ সিনথিয়া একটি আধুনিক সাইবারপাঙ্ক স্টাইলের ডেক্সটপ কমান্ড ব্রিজ ইউজার ইন্টারফেসে পরিচালিত হয়।

---

## ✨ Key Features (মূল বৈশিষ্ট্যসমূহ)

### 🧠 1. Hybrid Brain Architecture (অফলাইন + ক্লাউড)
- **Offline-First:** ইন্টারনেট না থাকলেও লোকাল [Ollama](https://ollama.com/) মডেল (`gemma4:e4b`) দিয়ে সরাসরি সম্পূর্ণ প্রজেক্ট ও এআই কাজ চালানো যায়।
- **Smart Cloud Fallback:** কোটা শেষ হলে বা নেটওয়ার্ক থাকলে স্বয়ংক্রিয়ভাবে প্রায়োরিটি অনুযায়ী পরবর্তী এপিআই-তে সুইচ করে:
  - Google Gemini Flash (`gemini-2.5-flash`)
  - Groq Llama 3.3 70B
  - Cerebras Llama 3.3 70B
  - OpenRouter Free Models
  - Mistral Small
  - GitHub Models (GPT-4.1 mini)
  - NVIDIA NIM

### 🎙️ 2. Accurate Bilingual Voice (বাংলা ও ইংরেজি ভয়েস)
- **Hysteresis VAD & Gain Normalization:** মাইক্রোফোনের নয়েজ ফিল্টার করে বাংলা বাক্যের নরম স্বর এবং শেষের ক্রিয়াপদগুলো নির্ভুলভাবে ধারণ করে।
- **Anti-Hallucination STT:** নীরব বা অপ্রয়োজনীয় শব্দে ভুল বাক্য জেনারেট হওয়া বন্ধ করা হয়েছে।
- **Natural Bangladeshi Neural Voices:** মাইক্রোসফট এজ টিটিএস প্রযুক্তির মাধ্যমে খাঁটি বাংলাদেশি উচ্চারণে কথা বলে:
  - `bn-BD-NabanitaNeural` (নারী কণ্ঠ · ডিফল্ট)
  - `bn-BD-PradeepNeural` (পুরুষ কণ্ঠ)
  - অফলাইন Windows SAPI ও Google TTS ফলব্যাক সাপোর্ট।

### 🖥️ 3. Futuristic Desktop Command Bridge (ফিউচারিস্টিক ইউআই)
- **3D Interactive Particle Orb:** ব্রাউজার/ওয়েবভিউ-তে রিয়েল-টাইম ১১০০ পয়েন্টের গোল্ডেন স্পাইরাল পার্টিকেল অর্র্ব।
- **Audio-Reactive Waves:** কথা শোনা (Listening) ও কথা বলার (Speaking) সময় লাইভ অডিও-রিঅ্যাক্টিভ অ্যানিমেশন।
- **Resizable Stage & Splitters:** সম্পূর্ণ ড্র্যাগ-অ্যান্ড-ড্রপ সাইজ অ্যাডজাস্টেবল লেআউট।
- **Themes:** `3D Neon`, `Aurora`, এবং `Paper` ৩টি ভিন্ন থিম।

### 🛡️ 4. Safety & System Control (নিরাপত্তা ও সিস্টেম নিয়ন্ত্রণ)
- **Confirmation Gate:** স্পর্শকাতর কোনো সিস্টেম কমান্ড বা ফাইল ডিলিট করার আগে ইউজারের নিশ্চিতকরণ অনুমোদন প্রয়োজন হয়।
- **Safe Delete:** স্থায়ীভাবে ডিলিট করার পরিবর্তে ফাইল রিসাইকেল বিনে পাঠানো হয় (`send2trash`)।
- **Global Kill Switch:** যেকোনো মুহূর্তে অপারেশন থামাতে `Ctrl + Shift + X` হটকি সাপোর্ট।
- **System Tray:** ব্যাকগ্রাউন্ডে শান্তভাবে চলার জন্য উইন্ডোজ সিস্টেম ট্রে ইন্টিগ্রেশন।

---

## 📁 Project Structure (প্রজেক্ট কাঠামো)

```text
Synthia-Ai-Agent/
├── config/
│   ├── models.yaml          # AI মডেলের অগ্রাধিকার ও তালিকা
│   └── settings.yaml        # মূল কনফিগারেশন (পোর্ট, ভাষা, মোড)
├── scripts/
│   ├── build_app.py         # C# লঞ্চার ও অ্যাপ বিল্ড স্ক্রিপ্ট
│   └── launcher.cs          # ট্রানস্প্যারেন্ট ব্যাকগ্রাউন্ড লঞ্চার সোর্স
├── synthia/
│   ├── assets/              # আইকন ও স্ট্যাটিক মিডিয়া
│   ├── core/                # এজেন্ট কোর, এলএলএম রাউটার ও টুল ইঞ্জিন
│   ├── skills/              # ফাইল, সিস্টেম, মেমোরি, ভয়েস ও ওয়েব স্কিল
│   ├── ui/                  # ড্যাশবোর্ড (HTML, CSS, JS ও 3D ক্যানভাস)
│   ├── voice/               # STT, TTS, মাইক্রোফোন ও অডিও ম্যানেজার
│   ├── desktop.py           # উইন্ডোজ সিস্টেম ট্রে ও উইন্ডো ম্যানেজমেন্ট
│   ├── server.py            # FastAPI + WebSocket রিয়েল-টাইম ব্যাকএন্ড
│   └── main.py              # অ্যাপ্লিকেশন এন্ট্রি পয়েন্ট
├── .env.example             # পরিবেশগত ভেরিয়েবল টেমপ্লেট
├── .gitignore               # গিট ইগনোর রুলস
├── requirements.txt         # পাইথন ডিপেনডেন্সি
├── run_synthia.bat          # ওয়ান-ক্লিক স্টার্ট স্ক্রিপ্ট
├── Synthia.exe              # স্ট্যান্ডঅ্যালোন উইন্ডোজ লঞ্চার
└── README.md                # প্রজেক্ট ডকুমেন্টেশন
```

---

## 🚀 Getting Started (শুরু করার নিয়ম)

### ১. পূর্বশর্ত (Prerequisites)
- **Operating System:** Windows 10 অথবা 11
- **Python:** 3.10 বা তার বেশি ([Python ডাউনলোড করুন](https://www.python.org/downloads/))
- **Ollama (অফলাইন ব্যবহারের জন্য):** [Ollama ডাউনলোড ও ইন্সটল করুন](https://ollama.com/)
  ```bash
  ollama pull gemma4:e4b
  ```

### ২. রিপোজিটরি ক্লোন করুন
```bash
git clone https://github.com/sa-noman/Synthia-Ai-Agent.git
cd Synthia-Ai-Agent
```

### ৩. ভার্চুয়াল এনভায়রনমেন্ট তৈরি ও একটিভ করুন
```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### ৪. প্রয়োজনীয় লাইব্রেরি ইনস্টল করুন
```powershell
pip install -r requirements.txt
```

### ৫. এনভায়রনমেন্ট ভেরিয়েবল সেটআপ (ঐচ্ছিক - ক্লাউড API-এর জন্য)
`.env.example` ফাইলের একটি কপি তৈরি করে নাম দিন `.env`:
```powershell
copy .env.example .env
```
ফাইলটি এডিট করে আপনার যে যে ফ্রি এপিআই কি (Gemini, Groq ইত্যাদি) রয়েছে সেগুলো বসিয়ে দিন। কোনো কি না দিলেও সিনথিয়া সম্পূর্ণ লোকাল মোডে চলবে।

---

## 🎮 How to Run (চালানোর নিয়ম)

যেকোনো একটি পদ্ধতি অনুসরণ করুন:

- **পদ্ধতি ১ (সবচেয়ে সহজ):** `Synthia.exe` ফাইলে ডাবল ক্লিক করুন।
- **পদ্ধতি ২:** `run_synthia.bat` ফাইলটি ডাবল ক্লিক করে রান করুন।
- **পদ্ধতি ৩ (টার্মিনালে):**
  ```powershell
  python -m synthia.main
  ```

অ্যাপ্লিকেশন চালু হলে স্বয়ংক্রিয়ভাবে এর ফিউচারিস্টিক কমান্ড ব্রিজ উইন্ডো খুলে যাবে এবং উইন্ডোজ সিস্টেম ট্রেতে মিনিমাইজ হয়ে থাকবে।

---

## ⚙️ Configuration (কনফিগারেশন)

- **`config/settings.yaml`**: পোর্ট, অ্যাসিস্ট্যান্টের ভাষা (`auto` / `bn` / `en`), লোকাল সার্ভার হোস্ট এবং সেফটি কনফার্মেশন সেটিংস পরিবর্তন করা যায়।
- **`config/models.yaml`**: নতুন মডেল যুক্ত করতে বা মডেলের অগ্রাধিকার (priority) পরিবর্তন করতে এই ফাইলটি ব্যবহার করুন।

---

## 🔒 Safety & Privacy

- আপনার কোনো ডেটা কোথাও অযাচিতভাবে আপলোড হয় না।
- সব কনভারসেশন ও লোকাল মেমোরি আপনার পিসির `synthia_data/` ফোল্ডারে সংরক্ষিত থাকে।
- এপিআই কি-সমূহ `.env` ফাইলে সংরক্ষিত থাকে যা গিটহাবে শেয়ার করা হয় না।

---

## 👨‍💻 Author & Contributions

- **Author:** [Shah Abdullah Al Noman](https://github.com/sa-noman)
- **Issues & Support:** যেকোনো সমস্যা বা ফিচারের জন্য [GitHub Issues](https://github.com/sa-noman/Synthia-Ai-Agent/issues)-এ পোস্ট করতে পারেন।

---

<p align="center">Made with ❤️ for AI Automation & Offline Computing</p>
