# Codebase Intelligence System (v2)

This is a production-grade, zero-cost, serverless-ready codebase analysis RAG system. It is designed to index GitHub repositories entirely for free, storing persistent data in a free Postgres database, and utilizing high-performance free LLMs.

## 1. Getting Your Free Credentials

To run this project, you need three free API keys and a database url. Create a `.env` file in the project root containing:

```env
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
```

### Groq API Key
1. Go to [console.groq.com](https://console.groq.com/).
2. Sign in with Google/GitHub and click **API Keys**.
3. Create a new key. Groq provides a generous free tier for `llama-3.3-70b-versatile`.

### Gemini API Key
1. Go to [Google AI Studio](https://aistudio.google.com/).
2. Click **Get API Key** and generate one. It is completely free.
3. This is used for `gemini-2.0-flash` batch summarization.

### Supabase URL & Key (Postgres Database)
1. Go to [supabase.com](https://supabase.com/) and create a free project.
2. Once the database is provisioned, go to **Project Settings -> API**.
3. Copy the `Project URL` to `SUPABASE_URL`.
4. Copy the `anon / public` key to `SUPABASE_KEY`.
5. Go to the **SQL Editor** in the Supabase dashboard and run the exact SQL command found in `supabase/00_init.sql` to create your tables and enable `pgvector`.

## 2. Running Locally

### Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

## 3. Free Hosting Quirks

If you deploy this to free platforms (like Render/Railway for the backend, Vercel for the frontend), keep the following in mind:
- **Supabase Free Projects** will automatically pause if they receive no activity for 7 days. If your app stops working, log into Supabase and click "Restore Project".
- **Render Free Web Services** spin down to sleep after 15 minutes of inactivity. When you hit the frontend after a long break, the first request (e.g. fetching indexed repos) might take ~30-50 seconds to respond while the server wakes up.
- The Vercel frontend is statically generated and will never sleep.
