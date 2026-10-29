# EduPilot Immersive – Book → 3D Lesson → Pictures → Video (Django)

Is project mein teacher **book ka content paste (ya PDF upload)** karta hai, aur system khud banata hai:

| Output | Kaise |
|---|---|
| 📚 Chapters → Lessons | Headings (`Chapter 1: …`) se auto-split |
| 🧠 Storyboard (scenes, narration, key points, objective) | Offline engine (koi API key nahi chahiye) ya optional Claude API |
| 🌐 **3D interactive scenes** | Three.js: solar system, cell, atom, circuit (switch click), DNA, geometry, concept-cluster |
| 🥽 **VR** | WebXR – "Enter VR" button (Quest Browser etc.); desktop/tablet par bhi chalta hai |
| 🖼️ **Pictures** | Har scene ki 1280×720 slide image (Pillow) |
| 🎬 **Video (MP4)** | Slides + slow zoom + voice-over (gTTS online / espeak-ng offline) via ffmpeg |
| 📝 Quiz | Text se auto MCQs, **server-side grading** |
| ✅ Workflow | Draft → Review → Approved → Published (blueprint s.8) |
| 📈 Progress | Quiz attempts + 3D scene events (blueprint s.18, dedup by `event_id`) |

## Update: teacher → student flow
Teacher: *New book* → PDF/text → tick Publish / Quiz / Video → **Generate lessons**. Har unit ka alag topic-wise lesson (3D + pictures + quiz + video) banta hai aur **student dashboard par foran aa jata hai** (review ab default OFF; `EDUPILOT_REQUIRE_REVIEW=1` se ON).
Teacher lesson page par quiz generate/give/hide karta hai, *Assignments & quizzes* se assignment/quiz/diary deta hai aur marks lagata hai; *Students & analytics* mein har student ki progress. Student dashboard: To-do, Learn now (3D/video/quiz), quiz score chart, assignment marks.
Naye tables ke liye `python manage.py migrate` chalayen. Quick test: `DB_ENGINE=sqlite`.

## Quick start
```bash
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
# Video ke liye ffmpeg zaroori hai:  Windows: winget install ffmpeg | Ubuntu: sudo apt install ffmpeg | Mac: brew install ffmpeg
python manage.py migrate
python manage.py seed_demo          # demo users + 3 sample lessons
python manage.py runserver
```
Browser: http://127.0.0.1:8000

| User | Password | Role |
|---|---|---|
| teacher | teacher12345 | Teacher (lessons banata, publish karta) |
| student | student12345 | Student |
| admin | admin12345 | Reviewer/Admin (approve karta) |

**Flow:** teacher login → *New book* → text paste → *Generate lessons* → lesson kholo → **Submit for review** → admin **Approve** → teacher **Publish** → student 3D dekhe, video dekhe, quiz de.
(Testing mein review skip karna ho: `EDUPILOT_REQUIRE_REVIEW=0`.)

## Video / voice
- **gTTS** (internet chahiye) English, Urdu (`ur`), Hindi (`hi`) voice-over deta hai.
- Internet na ho to **espeak-ng** (offline) try hota hai; dono na hon to video silent banti hai (page par note aata hai).
- Video background thread mein render hoti hai; lesson page auto-update hota hai. Production mein Celery/RQ use karein.

## Optional: AI storyboard (Claude)
```bash
export ANTHROPIC_API_KEY=sk-ant-...           # Windows: set ANTHROPIC_API_KEY=...
export EDUPILOT_LLM_MODEL=claude-sonnet-5-5   # optional
```
LLM ko sirf aapka paste kiya hua text diya jata hai (grounded), output validate hota hai, aur koi bhi error ho to offline engine fallback ban jata hai. Lesson hamesha **Draft** banta hai – teacher/reviewer approve kiye baghair students ko nahi dikhta.
⚠️ Ye LLM path live API ke saath test nahi hua (key available nahi thi) – apni key se ek baar zaroor try karein.

## Blueprint se mapping
- s.10 Lesson manifest → `Lesson.manifest()` / `GET /v1/vr/lessons/<id>/manifest`
- s.13 "clients never grade themselves" → quiz scoring sirf server par
- s.17/18 APIs → `GET /v1/vr/catalog`, `POST /v1/vr/events/batch` (max 100, dedup)
- s.4 roles → Teacher / Student / Reviewer(+admin); owner-only edit, students sirf published lessons dekhte hain
- s.21 comfort → forced motion nahi, orbit camera, desktop fallback, narration on/off
- s.22 privacy → sirf learning events (scene viewed, object selected) store hote hain; head/hand tracking nahi
- Cross-device: ek hi manifest VR, desktop aur tablet teeno chalate hain

## Code map
```
config/                  settings, urls
immersive/models.py      Book, Lesson, Scene, Question, LessonVideo, QuizAttempt, LearningEvent
immersive/views.py       dashboard, studio, workflow, viewer, quiz, API
immersive/services/
   textproc.py           chapters, sentences, keywords
   storyboard.py         scenes + visual picker + quiz generator
   llm.py                optional Claude storyboard
   media.py              Pillow pictures, TTS, ffmpeg video
   pipeline.py           book -> lessons -> images -> video job
immersive/static/immersive/js/viewer.js   Three.js 3D/VR viewer
immersive/static/immersive/vendor/three   Three.js r160 (local copy, offline chalta hai)
```
Tests: `python manage.py test immersive` (8 tests; video test tab chalta hai jab ffmpeg installed ho).

## Limitations (sach-sach)
- Offline storyboard *extractive* hai (aapke text se key sentences uthata hai); 3D shape keyword se chunti hai. Sirf 7 built-in 3D templates hain – naye topics (heart, volcano …) ke liye `viewer.js` mein builder aur `storyboard.VISUAL_RULES` mein rule add karein, ya licensed `.glb` models integrate karein.
- Scanned PDFs ke liye OCR nahi hai.
- Urdu script video mein sahi dikhne ke liye `arabic-reshaper` + `python-bidi` (requirements mein hain) aur Urdu-supporting font chahiye; Linux par `fonts-noto` install karein.
- Real VR headset par test nahi hua (desktop browser par test hua). Pre-junior bachon ke liye headset nahi, projected/desktop mode use karein (blueprint s.5).
- Ye development setup hai: production ke liye `DJANGO_DEBUG=0`, secret key, PostgreSQL, media storage (S3), Celery, aur teacher signup ko admin-approval se control karein (abhi koi bhi "Teacher" banke signup kar sakta hai).
