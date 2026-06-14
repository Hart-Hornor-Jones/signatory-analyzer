# Deploying the Signatory Explorer to GitHub Pages

The publishable site is the **`docs/`** folder — Vite now builds straight into it.
Everything GitHub Pages needs is there: `index.html`, `assets/`, `data/data.json`,
and `.nojekyll`. Your `src/`, `public/`, and `node_modules/` folders are **not**
published.

## One-time setup
1. Put this project folder in a GitHub repo (this folder = the repo root).
2. Commit and push it to GitHub (or use github.com → "Add file → Upload files").
3. On github.com: **Settings → Pages → Build and deployment →
   Source: "Deploy from a branch" → Branch: `main`, Folder: `/docs` → Save.**
4. Wait ~1 minute. Your site will be live at:
   **`https://<your-username>.github.io/<repo-name>/`**

`vite.config.js` sets `base: './'`, so the relative asset paths work from that
subfolder automatically — no other configuration needed.

## Updating it later (new signatures, or any code change)
```bash
python build_data.py     # only if the signatory table or crosswalk changed
npm install              # first time only
npm run build            # rebuilds docs/
git add -A && git commit -m "Update" && git push
```
Pages redeploys automatically on push.

## Good to know
- `.nojekyll` lives in `public/` and is copied into `docs/` on every build. It stops
  GitHub running Jekyll, which would otherwise ignore the `assets/` folder.
- The old `dist/` folder is no longer used (the build outputs to `docs/` now); you
  can delete it.
- To change how departments are classified, edit `department_crosswalk.csv`,
  re-run `python build_data.py`, then rebuild.
