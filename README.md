# SmartStudyInstructor — Unified AI-Powered Tutoring & Lecture Generator

> An advanced final-year project (FYP) featuring role-based classroom management, a PDF-to-lecture RAG pipeline, real-time Playwright-rendered lecture videos, and remote GPU-accelerated talking-head avatars (Wav2Lip / OmniAvatar).

---

## 📸 Overview & Key Features
`SmartStudyInstructor` is a comprehensive educational suite designed to automate lecture preparation, deliver highly interactive learning material, and monitor student engagement.

*   **Intelligent Pedagogical Engine:** Generates highly structured **Scene DNA** scripts (Intro, Topic Concept, Bullet Points, Diagram Zoom, Worked Example, Interactive Quiz, Outro) from uploaded PDF textbooks using Gemini 2.0 Flash / Groq LLaMA 3.
*   **Audio-Visual Synced Lecture Player:** Headless Chromium captures virtual-time HTML/JS animations (using GSAP and Canvas) and composites them with TTS audio using an exact-duration FFmpeg rendering pipeline.
*   **Vector RAG Q&A System:** Chunk-based PDF parsing with ChromaDB vector storage and Sentence-Transformers embeddings for real-time, context-grounded student queries.
*   **Classroom Vision System:** YOLOv8-based live webcam feed monitoring to detect student phone usage/cheating, logging timestamps and snapshots to the teacher dashboard.
*   **Remote GPU Lip-Sync Integration:** Offloads computationally intensive talking-head video generation (Wav2Lip on Kaggle, OmniAvatar on Google Colab) to free cloud runtimes, linking them dynamically via secure Ngrok tunnels.

---

## 🛠️ System Architecture

```
                       ┌──────────────────────────────────────────────┐
                       │           PDF Ingestion & RAG Layer          │
                       │   PDF Upload ➔ ChromaDB Vector Indexing      │
                       └──────────────────────┬───────────────────────┘
                                              │
                                              ▼
                       ┌──────────────────────────────────────────────┐
                       │          Pedagogical Script Engine           │
                       │    LLM Script Generation (Scene DNA JSON)    │
                       └──────────────────────┬───────────────────────┘
                                              │
                                              ▼
                       ┌──────────────────────────────────────────────┐
                       │              Audio & TTS Layer               │
                       │    Edge-TTS (per-word Millisecond Timings)   │
                       └──────────────────────┬───────────────────────┘
                                              │
                                              ▼
                       ┌──────────────────────────────────────────────┐
                       │          GPU Talking-Head Rendering          │
                       │  Kaggle (Wav2Lip) or Colab (OmniAvatar 1.3B) │
                       └──────────────────────┬───────────────────────┘
                                              │
                                              ▼
                       ┌──────────────────────────────────────────────┐
                       │          Playwright Capture & Sync           │
                       │ Virtual Time Frame Capture ➔ WebM Recording   │
                       └──────────────────────┬───────────────────────┘
                                              │
                                              ▼
                       ┌──────────────────────────────────────────────┐
                       │             FFmpeg Composition               │
                       │   Combines WebM + Lipsync AV + Subtitles     │
                       └──────────────────────────────────────────────┘
```

---

## 📋 Comprehensive Tech Stack

| Layer | Technologies | Role / Feature |
| :--- | :--- | :--- |
| **Backend Framework** | FastAPI 0.104, SQLAlchemy 2.0, Pydantic v2, SQLite3 | Core server REST endpoints, database access, configuration, and JSON parsing. |
| **AI Models (LLM)** | Gemini 2.0 Flash, Groq LLaMA 3.3/4 | Core scripting engine, quiz generators, and general Q&A pipeline. |
| **Vector DB & RAG** | ChromaDB, Sentence-Transformers (MiniLM) | PDF text chunking, storage, and contextual document search. |
| **TTS & Timing** | Edge-TTS, PyTTSx3, Google TTS | Natural voice generation with precise word-level millisecond alignment. |
| **Video Capture** | Playwright (Headless Chromium), GSAP, JS Audio Clock | High-speed, frame-perfect virtual rendering of canvas-based scenes. |
| **Composition** | FFmpeg | Video assembly, audio layering, subtitles, and final MP4 encoding. |
| **Cloud GPU Avatar** | Wav2Lip (Kaggle Cloud), OmniAvatar 1.3B (Colab) | Lipsync talking-head generation using external GPU hardware. |
| **Vision System** | YOLOv8n (Ultralytics) | Real-time object detection for mobile phones in camera feed. |
| **Frontend UI** | HTML5, Vanilla JavaScript, CSS3 | Teacher dashboard, Student RAG Q&A interface, and Lecture player. |

---

## 📂 Project Structure

```
SmartStudyInstructor/
├── backend/                  # FastAPI Web Backend
│   ├── app/
│   │   ├── auth/            # JWT authentication & user accounts
│   │   ├── database/        # SQLite/SQLAlchemy schema configuration
│   │   ├── rag/             # Document extraction, ingestion, and vector search
│   │   ├── routes/          # API route definitions
│   │   ├── services/        # Core processing logic
│   │   │   ├── blueprint_pipeline.py # Orchestrates RAG -> Video pipeline
│   │   │   └── kaggle_client.py      # Cloud API connector for Wav2Lip
│   │   └── utils/           # Shared utility tools & logs
│   ├── core/
│   │   ├── timeline_builder.py # Computes timing triggers for HTML scenes
│   │   └── tts_engine.py       # Manages TTS synthesis and timestamp mapping
│   ├── rendering/
│   │   ├── ffmpeg_pipeline.py  # Assembles, overlays, and encodes final MP4s
│   │   ├── playwright_capture.py # Operates headless capture instances
│   │   ├── scene_router.py     # Serves Jinja2 templates for capture
│   │   └── templates/          # Jinja2 HTML slides (diagram zoom, example, etc.)
│   ├── static/               # Assets, uploads, processed video/audio
│   ├── scripts/              # Setup, debug, and population scripts
│   ├── run.py                # Local startup runner
│   ├── requirements.txt      # Production package dependencies
│   └── .env.example          # Template configuration
├── frontend/                 # Client UI Files (Vanilla HTML/CSS/JS)
│   ├── index.html            # Gateway Login screen
│   ├── dashboard.html        # Interactive teacher management console
│   ├── classroom.html        # Smart projector/LED student screen
│   └── student_tuition.html  # Student-facing personalized study screen
├── Kaggle_Cloud_Engine.ipynb # Jupyter notebook for Kaggle Wav2Lip server
└── README.md                 # Project Documentation
```

---

## 🚀 Local Installation & Setup

### 1. Prerequisite Installations
*   **Python:** Install Python (v3.9 or v3.10 recommended).
*   **FFmpeg:** Ensure FFmpeg is installed and added to your system's environment variable path (so that `ffmpeg` commands can run globally in terminals).
*   **Chrome/Playwright:** Playwright handles headless browser capture.

### 2. Setup Virtual Environment
Run the following commands in the project directory to configure your virtual environment:
```bash
# Navigate to the backend directory
cd backend

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate
```

### 3. Install Dependencies
Install all package requirements inside the active virtual environment:
```bash
pip install -r requirements.txt
playwright install chromium
```

### 4. Set Environment Configuration
Create a `.env` file in the `backend/` directory using the provided template:
```bash
cp .env.example .env
```
Open `.env` and fill in your keys:
*   `GEMINI_API_KEY`: Needed for automatic PDF lecture scripting.
*   `GROQ_API_KEY`: Required for diagram content analysis and LLaMA 4 Scout features.
*   `CLOUD_RENDER_URL`: Leave empty initially (will be filled once the Kaggle server is running).

### 5. Initialize the Database and Seed Demo Users
Run the seeder script to populate default accounts for Admin, Teacher, and Student roles:
```bash
python scripts/seed_demo.py
```

### 6. Start the Backend API Server
Launch the local development server:
```bash
python run.py
```
The backend API documentation is now live at: `http://localhost:8000/docs`

---

## ☁️ Setting Up Cloud GPU Render Servers

Since rendering video and computing lipsync lip movements require high-performance hardware, the project features integrations with free GPU-based Jupyter environments (Kaggle & Google Colab).

---

### 1. Kaggle Wav2Lip Server Setup (Recommended for Full Video Overlays)
This notebook configures a Flask-based API running inside a Kaggle instance with a T4 GPU, exposing the GPU service using `pyngrok`.

#### Setup Steps:
1.  **Register/Login to Kaggle:** Go to [Kaggle](https://www.kaggle.com).
2.  **Upload the Notebook:** Create a new Jupyter notebook on Kaggle and import/upload the file [Kaggle_Cloud_Engine.ipynb](file:///c:/Users/PMLS/Desktop/Prototype/SmartStudyInstructor/Kaggle_Cloud_Engine.ipynb) found in the root directory of this project.
3.  **Configure Notebook Environment:**
    *   Set **Accelerator** to **GPU T4 x2** or **GPU T4** in the right-hand panel settings.
    *   Enable **Internet** access (Crucial: Kaggle requires phone number verification to enable internet access. Ensure your account is verified).
4.  **Add Ngrok Token:**
    *   Sign up at [ngrok](https://ngrok.com) for a free account and copy your Auth Token.
    *   In **Cell 2** of the Kaggle notebook, replace the placeholder token in `NGROK_TOKEN` with your personal ngrok token:
        ```python
        NGROK_TOKEN = "your_personal_ngrok_token"
        ```
5.  **Run All Cells:** Run the notebook cells sequentially.
    *   **Cell 1:** Downloads model checkpoints (`wav2lip_gan.pth`, `s3fd.pth`), pulls official repositories, and patches dependencies.
    *   **Cell 2:** Initializes the Flask application, loads the model into GPU memory, connects to the Ngrok tunnel, and launches the server.
6.  **Connect Local API to Cloud:**
    *   Copy the public address printed at the end of the Kaggle notebook output (e.g., `https://xxxx-xx-xx-xxx.ngrok-free.app`).
    *   Open your local `backend/.env` file and set it as `CLOUD_RENDER_URL`:
        ```ini
        CLOUD_RENDER_URL=https://xxxx-xx-xx-xxx.ngrok-free.app
        ```
    *   The backend pipeline will now automatically forward TTS voice clips to Kaggle to generate highly synced 280px circular talking-head videos overlaying the slideshows.

---

### 2. OmniAvatar Colab GPU Setup (Alternative Model)
Used for rendering high-fidelity interactive talking avatars using Google Colab.

#### Setup Steps:
1.  **Open Google Colab:** Locate `OmniAvatar_SmartStudy_Colab.ipynb` (or create a new notebook) and load it into Google Colab.
2.  **Hardware Check:** Navigate to **Runtime ➔ Change runtime type** and select **T4 GPU**.
3.  **Execute the Cells:** Run cells 1 through 5 to fetch weights and run the host script.
4.  **Environment Link:**
    *   Once loaded, copy the ngrok URL generated inside the output logs.
    *   Put the URL into your local environment:
        ```ini
        COLAB_AVATAR_URL=https://xxxx-xx-xx-xxx.ngrok-free.app
        ```
    *   Or open `http://localhost:8000/lecture-player` in your browser and paste the URL directly into the GPU connection field.

---

## 👥 Demo Logins

Use these default accounts to access the application after seeding:

| Role | Username | Password |
| :--- | :--- | :--- |
| **Admin** | `admin01` | `Admin@123` |
| **Teacher** | `teacher01` | `Teacher@123` |
| **Student** | `student01` | `Student@123` |

---

## 🧪 Testing the Pipeline
You can trigger verification scripts to validate the API and rendering operations:

*   **Endpoint Smoke Tests:**
    ```bash
    python scripts/test_demo_endpoints.py
    ```
*   **Comprehensive E2E Pipeline Verification:** Checks RAG extraction, TTS, Playwright Capture, and FFmpeg assembly locally:
    ```bash
    python test_awaited.py
    ```

---

## 🎥 Sample Demo & Output Preview

Here is a preview of the sample assets and the generated talking-head lecture output:

### 📥 Input Assets
*   **Teacher Avatar:**  
    <img src="backend/static/demo_assets/teacher_avatar.png" width="150" alt="Teacher Avatar">
*   **Input Textbook Document:**  
    [📄 Download test_lecture.pdf](https://github.com/adanmalik7909/PDF-fully-synced-lecture-video/raw/main/backend/static/demo_assets/test_lecture.pdf)

### 📤 Generated Lecture Output Video
You can watch the fully lipsynced animated lecture video generated by the system directly below:

[🎥 Download/Play lecture_video.mp4](https://github.com/adanmalik7909/PDF-fully-synced-lecture-video/raw/main/backend/static/demo_assets/lecture_video.mp4?v=2)


