THE READING EDIT — LIVE FEED UPDATE

Upload index.html and articles.json to the ROOT of the existing GitHub repository.
Netlify will deploy automatically if linked to the main branch.

The app now fetches articles.json on opening and merges new articles by stable id.
Existing Save / Read / Favourite status is preserved in localStorage on the SAME origin/device.
Do not change the Netlify website address or clear browser data.

To publish more articles, edit articles.json in GitHub. Use unique stable IDs.
Each item needs id, title, publication, date, minutes, description, url.

IMPORTANT: This is NOT an automated article researcher or publisher. The 8am ChatGPT
reading automation does not currently write to GitHub. A separate publisher workflow
must be built to make editions appear without manual editing.

Your browser reading data is not synced to GitHub. Export backups in the app.
