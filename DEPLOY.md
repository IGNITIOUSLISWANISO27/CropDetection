# Putting the FieldPriority dashboard online for the team

The dashboard runs on **Streamlit Community Cloud** (free) and reads its data from **Firebase**.
The pipeline keeps running on this PC: after each run, `sync_firebase.bat` updates Firebase and the
online dashboard shows the new results within about 2 minutes (or press "Reload data").

```
This PC: run_pipeline / validate_kobo  ->  sync_firebase  ->  Firebase  ->  online dashboard (team)
```

## One-time setup (about 20 minutes)

1. **GitHub repository (private).** Sign in at github.com, click **New repository**, name it
   `fieldpriority-dashboard`, choose **Private**, create it.
2. **Upload the code.** Unzip `deploy\fieldpriority_dashboard.zip`. In the new repository click
   **Add file > Upload files**, drag in everything from the unzipped folder (the folders `app`, `src`,
   `config`, `.streamlit` and the files `requirements.txt`, `.gitignore`, `README.md`, `DEPLOY.md`), then
   **Commit changes**. The zip contains no keys, tokens or data.
   - If `.streamlit` or `.gitignore` do not upload (Windows hides files starting with a dot), create them
     with **Add file > Create new file** and paste their content.
3. **Streamlit app.** Go to share.streamlit.io, sign in with GitHub, click **Create app >
   Deploy a public app from GitHub**, then choose:
   - Repository: `<your-account>/fieldpriority-dashboard`, Branch: `main`
   - Main file path: `app/Home.py`
   - Advanced settings: Python **3.12**
4. **Firebase key as a secret.** On this PC double-click `make_streamlit_secrets.bat`. Notepad opens
   `.streamlit\secrets.toml`. Copy **all** of it into **Advanced settings > Secrets** (or later: app menu >
   Settings > Secrets). Save, then **Deploy**. The first start takes 3-5 minutes.
5. **Who can see it.** In the app's **Share** menu keep the app **private** and add each team member's
   email under "Invite viewers" (they sign in with that email). Only invited people can open it.

## Every update after that

**`monthly_update.bat`** does everything once a month (district layers, Solwezi field data and assessment, Kobo
check, Firebase sync); `setup_monthly_task.bat` schedules it. For a quick refresh after field visits:
`validate_kobo.bat`, then **`sync_firebase.bat`** (it also uploads the district layers).
Code changes on this PC are not online until the changed files are uploaded to the GitHub repository again.

## Never upload
`firebase-key.json`, `.env` (Kobo token), `.streamlit/secrets.toml`, `outputs/`, `backup_*` folders.

## Same-office alternative (no internet setup)
`run_dashboard_lan.bat` opens the dashboard to computers on the same Wi-Fi: they go to
`http://<this PC's IPv4 address>:8501`. This PC must stay on with that window open, and Windows may ask to
allow Python through the firewall (allow on **private** networks only).
