# HOW TO SUBMIT THE PROMPT & ASSETS TO GOOGLE GEMINI
## Step-by-Step Operator Guide for 150-Second Corporate Video Generation

---

## 1. FOLDER INVENTORY & FILE MANIFEST

All necessary assets for generating the commercial have been generated and organized inside this folder:  
`d:\LAIT\LMS_ANGIGRAVITY\Video prompt\`

Below is the complete inventory of all files:

| File Name | Asset Type | Description & Purpose |
| :--- | :--- | :--- |
| **`GEMINI_TEXT_TO_VIDEO_MASTER_PROMPT.md`** | **Master Prompt** | The complete 150-second production script, scene-by-scene breakdown, voiceover, on-screen text, audio direction, and camera guidelines. |
| **`HOW_TO_USE_IN_GEMINI_GUIDE.md`** | **Instruction Guide** | This step-by-step manual explaining how to upload media and submit prompts to Gemini. |
| **`00_BRAND_LOGO.png`** | Image (PNG) | London Academy of IT emblem & LMS Console branding card for Scene 03 & Scene 11 (Outro). |
| **`01_DASHBOARD_COMMAND_CENTER.png`** | Screenshot (PNG) | Real Executive Command Center hero banner (Wise, Code WISE, Health Index 64/100) + 6-KPI command grid for Scene 04. |
| **`02_WORKFORCE_INTERVENTION_DESK.png`** | Screenshot (PNG) | Real Workforce Intervention Desk table with 5 at-risk learners and risk reasons for Scene 05. |
| **`03_TEAM_DIRECTORY.png`** | Screenshot (PNG) | Real `/team` roster showing the 4 top metrics and 7 corporate delegates for Scene 06. |
| **`04_EMPLOYEE_PROFILE_DRILLDOWN.png`** | Screenshot (PNG) | Real `/team/[id]` profile of Harika Kancham with overdue coursework warning banner for Scene 06. |
| **`05_COURSE_CATALOG.png`** | Screenshot (PNG) | Real `/courses` catalog with 29 technical courses (Python, AI, Data Science, Power BI) for Scene 07. |
| **`06_BATCHES_COHORTS.png`** | Screenshot (PNG) | Real `/batches` cohort list showing scheduled classes and active enrollments for Scene 07. |
| **`07_ATTENDANCE_REGISTERS.png`** | Screenshot (PNG) | Real `/attendance` table with 21 records and verified tutor sign-offs (*"Recorded by Moshiur Rahman"*) for Scene 08. |
| **`08_ENTERPRISE_REPORTS.png`** | Screenshot (PNG) | Real `/reports` interface showing 6 reporting tabs and the `Export CSV` action button for Scene 09. |

---

## 2. HOW TO SUBMIT TO GOOGLE GEMINI (STEP-BY-STEP)

### STEP 1: Open Google Gemini
1. Navigate to **Google Gemini** (Gemini Advanced or Google AI Studio).
2. Ensure you are in a session that supports file uploads (images and text).

### STEP 2: Upload the 9 Image Files
1. Click the **+** (Attach / Upload) button in the prompt box.
2. Select all **9 image files** located in `d:\LAIT\LMS_ANGIGRAVITY\Video prompt\`:
   - `00_BRAND_LOGO.png`
   - `01_DASHBOARD_COMMAND_CENTER.png`
   - `02_WORKFORCE_INTERVENTION_DESK.png`
   - `03_TEAM_DIRECTORY.png`
   - `04_EMPLOYEE_PROFILE_DRILLDOWN.png`
   - `05_COURSE_CATALOG.png`
   - `06_BATCHES_COHORTS.png`
   - `07_ATTENDANCE_REGISTERS.png`
   - `08_ENTERPRISE_REPORTS.png`
3. Wait 2–3 seconds for the thumbnails of all 9 images to appear in Gemini's prompt area.

### STEP 3: Copy and Paste the Master Prompt
1. Open [`GEMINI_TEXT_TO_VIDEO_MASTER_PROMPT.md`](file:///d:/LAIT/LMS_ANGIGRAVITY/Video%20prompt/GEMINI_TEXT_TO_VIDEO_MASTER_PROMPT.md).
2. Select the entire text from **SECTION 1 through SECTION 3** (or the prompt block in Section 13).
3. Paste it directly into the Gemini chat box below the attached images.
4. Press **Enter / Send**.

---

## 3. WHAT TO DO IF GENERATING VIDEO DIRECTLY IN AN AI VIDEO TOOL (VEO / RUNWAY / KLING)

If you are using Gemini to produce the final video shots or feeding prompts into **Google Veo**, **Runway Gen-3**, or **Kling**:

1. **For Software UI Scenes (Scenes 04–09)**:
   - Always use **Image-to-Video** mode.
   - Upload the corresponding screenshot (e.g., `01_DASHBOARD_COMMAND_CENTER.png`).
   - Use a prompt that moves the camera **around the existing image**:
     > *"Slow cinematic push-in on this enterprise software dashboard, soft studio lighting pass across the KPI cards, shallow depth of field, 4k ultra realistic, zero distortion of text or numbers."*
2. **For Corporate B-Roll Scenes (Scenes 01, 02, 10)**:
   - Use standard **Text-to-Video** mode using the prompt descriptions provided in Section 7 of the master audit report.
3. **For the Voiceover (Audio)**:
   - You can copy the timestamped text from `GEMINI_TEXT_TO_VIDEO_MASTER_PROMPT.md` and paste it into an AI voice generator like **ElevenLabs** (select an articulate British corporate voice like *"Adam"* or *"Brian"* or *"George"*).

---

## 4. CRITICAL RULES & ANTI-HALLUCINATION SAFEGUARDS

1. **Never ask Gemini to "design a similar dashboard"**: That would trigger AI hallucinations with fake buttons and cartoon graphics.
2. **Always reference the uploaded images by name**: Referencing `01_DASHBOARD_COMMAND_CENTER.png` instructs the model to use the real captured software frame.
3. **Keep the real names and numbers intact**: The authentic figures (Wise, 7 employees, 63.2% attendance, tutor Moshiur Rahman) give the commercial genuine enterprise credibility.

