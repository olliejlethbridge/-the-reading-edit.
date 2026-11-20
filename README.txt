THE READING EDIT — FIRST VERSION

WHAT WORKS
- Mobile-friendly reading list with real tappable Save, Read and Favourite buttons.
- Four collections: The Edit, Saved, Read, Favourites.
- Selections persist using browser localStorage on the same device/browser.
- Export and import your library as a JSON backup.
- Import additional articles from a JSON file (see articles.json).

HOW TO PUT IT ON YOUR IPHONE
1. Upload index.html to a static web host such as Netlify Drop or GitHub Pages.
2. Open the resulting HTTPS address in Safari on your iPhone.
3. Tap Share > Add to Home Screen.

IMPORTANT LIMITATIONS
- The library is local to the browser/device; it does not sync across devices.
- Clearing Safari site data can erase it; export backups.
- The existing ChatGPT daily automation does NOT publish into this app yet.
- Articles included are the four foundational recommendations discussed in chat; their external links may change.
- The app is not yet hosted or connected to a database.

JSON ARTICLE FORMAT
An array of objects with fields:
id, title, publication, date, minutes, description, url.
Use the 'Add articles (JSON)' control to import.

FUTURE VERSION
Connect an automated publishing feed and cloud storage so new articles appear daily and your library syncs across devices.
