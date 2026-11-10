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

## Update (voice, lesson CRUD, one-time quiz/assignment, teacher marks, retry)
**Voice (3D viewer + lesson page)** – scene narration ab khud bolti hai (pehle tap/key par start, browser ki rule hai). Controls: Mute/Unmute, Pause/Resume (Space), Repeat, voice choose karna, speed slider, *Voice commands* (🎤: "next", "previous", "repeat", "key points", "stop", "tour" – Urdu/Hindi words bhi: "agla", "pichla", "dobara", "ruko", "اگلا", "رکو"…; Chrome/Edge chahiye, headphones behtar). Agar device par lesson ki language (Urdu/Hindi) ki voice nahi hai to server ki audio (`/lessons/<id>/scenes/<n>/audio/`, gTTS/espeak, cache hoti hai) automatic use hoti hai. Lesson page par har scene ke saath **Listen** button hai.

**Lesson plan CRUD (teacher)** – Lesson page / book page / dashboard par **Edit** aur **Delete**. Edit page par title, objective, har scene edit, **➕ Add a scene**, **🗑 Delete this scene**. Lesson delete karne se uske scenes, pictures, video, quiz, assignments, student results aur files sab hat jate hain (confirm ke baad). Poori **book** bhi delete ho sakti hai. Edit ke baad lesson Draft ban jata hai (version +1) – dobara Publish karein.

**Quiz / assignment sirf ek baar** – student ek quiz/assignment sirf ek baar submit kar sakta hai (dobara URL kholne ya POST karne par bhi server rok deta hai). Submit ke baad student ko "Submitted – waiting for marks" dikhta hai.
**Teacher marks** – Submitted quizzes/assignments teacher dashboard ("Waiting for your marks") aur quiz/assignment page par aate hain. Quiz ka auto-check sirf suggestion hai; teacher final marks (0 – total) + feedback deta hai. Marks student dashboard (*Marks given by teacher*), progress page aur quiz-result page par dikhte hain; average/best sirf teacher-marked quizzes se banta hai.
**Retry** – 50% se kam marks (`EDUPILOT_LOW_MARKS_PERCENT`) "low marks" flag hote hain; teacher **🔁 Allow retry** dabata hai (kisi bhi graded attempt par) tab hi student ko "Retry quiz" milta hai, ek hi extra attempt; use karte hi permission khatam. Assignment ke liye bhi **Allow re-submission** hai.
Teacher ka quiz preview ab save nahi hota.
⚠️ `python manage.py migrate` zaroor chalayen (migration 0004). Purane quiz attempts ke marks automatic score ke barabar set ho jate hain taake purani history "waiting" na dikhe.


## Update (roadmap document: plan first -> pictures -> 3D, + roadmap features)
**Book -> lesson plan -> 3D.** Upload now works in this order: (1) a *lesson plan* is written per topic (objective, 5 phases with minutes: introduction / prediction / guided activity / discussion / short assessment, vocabulary, probe questions, rubric, screen-based fallback, quiz); (2) **pictures inside the PDF are extracted** (`services/bookimages.py`) and placed on the scene whose text they belong to (logos/icons/repeated header pictures are skipped); (3) every scene that still has no picture gets one **drawn from its own content** (`services/diagrams.py`: flow / cycle / concept map, or a built-in illustration for solar system, cell, atom, circuit, DNA, geometry; Urdu text supported); (4) the teacher reviews the plan on the lesson page and clicks **Watch lesson plan in 3D**. Nothing is published until the teacher publishes (tick "publish" on the form to skip that).
**3D viewer:** picture board next to the scene (click = enlarge, `P` = next picture, thumbnails), 3D flow/cycle/map built from the lesson text for any subject, optional teacher-supplied `.glb` per scene, lesson-plan panel, accessibility (text size, captions, high contrast, reduce motion), "Save for offline" (service worker + lesson pack), events kept in localStorage while offline. Video slides also use the scene picture.
**Roadmap features:** content passport page; per-pathway curriculum mappings approved by someone other than the proposer; immutable published-version snapshots (`?version=N`); curriculum new-version + change register (flags affected lessons); content issues; creators cannot approve their own lesson; roles Creator / Device supervisor / Institution admin (`python manage.py seed_roadmap`); market scoring + country readiness (`/markets/`); pilot scorecard (`/pilot/`); PDF report (`/reports/export.pdf`) + Chart.js chart; lab capacity planner; audit log of sensitive record access.
Run `python manage.py migrate` (migration 0006). Not built (needs a decision/customer first): multi-institution tenant isolation, LTI/QTI/OneRoster/xAPI, MFA, object storage/CDN.

## Update (student = teacher 3D viewer, voice fix)
- **Ek hi viewer** teacher aur student dono ke liye (`viewer.html` + `viewer.js`): same 3D scene, picture board, lesson plan panel, voice. Student browser purani cached `viewer.js` na use kare is liye ab sab js/css `?v=<mtime>` ke saath load hote hain (`context.asset_version`).
- Agar kisi scene ka diagram data na ho to viewer key points se wahi card-style 3D scene khud bana deta hai (pehle sirf gol spheres aate the).
- **Voice**: `voice.js` dobara likha – utterance GC bug, cancel→speak race, silent engine watchdog, device voice ↔ server voice automatic fallback, status message (`🔊 Playing (device voice)` / reason). Pehli awaaz ke liye page par **"Click here to start the voice narration"** button ya koi bhi click/key.
- Server voice: gTTS (internet) → espeak-ng → **Windows built-in voice (SAPI, offline, English)** – Windows par kuch install karne ki zaroorat nahi.

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
immersive/static/immersive/js/viewer.js   Three.js 3D/VR viewer (+ voice commands)
immersive/static/immersive/js/voice.js    voice engine (browser voice / server audio, speed, voice choice)
immersive/static/immersive/vendor/three   Three.js r160 (local copy, offline chalta hai)
```
Tests: `python manage.py test immersive` (28 tests; video test tab chalta hai jab ffmpeg installed ho).

## Limitations (sach-sach)
- Offline storyboard *extractive* hai (aapke text se key sentences uthata hai); 3D shape keyword se chunti hai. Sirf 7 built-in 3D templates hain – naye topics (heart, volcano …) ke liye `viewer.js` mein builder aur `storyboard.VISUAL_RULES` mein rule add karein, ya licensed `.glb` models integrate karein.
- Scanned PDFs ke liye OCR nahi hai.
- Urdu script video mein sahi dikhne ke liye `arabic-reshaper` + `python-bidi` (requirements mein hain) aur Urdu-supporting font chahiye; Linux par `fonts-noto` install karein.
- Real VR headset par test nahi hua (desktop browser par test hua). Pre-junior bachon ke liye headset nahi, projected/desktop mode use karein (blueprint s.5).
- Ye development setup hai: production ke liye `DJANGO_DEBUG=0`, secret key, PostgreSQL, media storage (S3), Celery, aur teacher signup ko admin-approval se control karein (abhi koi bhi "Teacher" banke signup kar sakta hai).


## Immersive LMS workflow (added from `Immersive_LMS_Complete_Workflow.docx`)

| Workflow section | Where in the app |
| --- | --- |
| s.2 Curriculum, subjects, outcomes (versioned) | **Curriculum** (`/curriculum/`) |
| s.1, s.6, s.7 Learning modes, lesson builder, alternative route, release checklist | **Lesson design** (`/lessons/<id>/design/`) |
| s.5 Classes, enrolment, scheduling, launch / end / cancel, observation notes | **Classes & sessions** (`/classes/`) |
| s.6 Student journey (sessions, follow-up, outcome progress) | **My learning** (`/my-learning/`) |
| s.8 Outcome progression (Not started → In progress → Evidence submitted → Developing / Achieved) | automatic, from evidence and teacher-reviewed marks only |
| s.8 Score override needs reason + audit record | grading forms; shown in **Reports** |
| s.8 / s.5 Follow-up: targeted support or extension (editable suggestions) | class page / My learning |
| s.10 Guardian sees only linked learners | **My children** (`/guardian/`), link via admin `GuardianLink` |
| s.11 Lab: inventory, booking → approve → issue → return, fault log | **Lab & devices** (`/lab/`) |
| s.10 Reporting indicators, audit log | **Reports** (`/reports/`) |
| s.12 Reviewed results for the ERP | `GET /v1/erp/results` (staff / reviewer only) |

New settings: `EDUPILOT_MASTERY_PERCENT` (default 70), `EDUPILOT_REQUIRE_ALT_ROUTE` (default 0; set 1 to block publishing AR/VR lessons without an alternative route).
Run `python manage.py migrate` and then `python manage.py seed_demo` (adds a demo curriculum, class, guardian and two devices; extra login: `guardian / guardian12345`).

### Fix: `IntegrityError ... null value in column "feedback" of relation "immersive_quizattempt"`
The grading columns (`feedback`, `retry_allowed`, ...) were NOT NULL without a database default, so any code path that did not set them crashed on PostgreSQL. Migration `0005` adds DB-level defaults (`db_default`), so inserts are safe even from older code.


## UI structure (teacher portal + student portal)
One Django project serves both portals; the page you see depends on the logged-in user's role.

| File | Used for |
| --- | --- |
| `immersive/static/immersive/css/app.css` | COMMON: layout, sidebar, topbar, buttons, forms, tables, shared pages (assignments list, lessons) |
| `immersive/static/immersive/css/teacher.css` | TEACHER portal only: dashboard, book → lessons studio, curriculum, students & analytics |
| `immersive/static/immersive/css/student.css` | STUDENT portal only: dashboard, my progress, my learning |
| `templates/immersive/base.html` | loads `app.css` + `teacher.css` (teachers) or `student.css` (students/guardians) |
| `templates/immersive/dashboard_teacher.html` / `dashboard_student.html` | the two dashboards |

If the UI looks old/broken after an update: press **Ctrl+F5** (browser cache). The CSS links carry a `?v=` number in `base.html`; change it when you edit the CSS.

Run: `pip install -r requirements.txt`, `python manage.py migrate`, `python manage.py seed_demo`, `python manage.py runserver`
(for a quick local test without PostgreSQL: `DB_ENGINE=sqlite`). Logins: `teacher / teacher12345`, `student / student12345`, `admin / admin12345`.
