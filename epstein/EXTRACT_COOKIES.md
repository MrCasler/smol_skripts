# How to Extract ALL Cookies from DevTools

## Cookie Editor → JSON (recommended)

1. Install [Cookie-Editor](https://cookie-editor.cgagnier.ca/) (browser extension).
2. Go to https://www.justice.gov/epstein/ and complete age verification.
3. Open Cookie-Editor → select **justice.gov** (or filter by that domain).
4. **Export** → choose **JSON** format → copy.
5. Save the pasted content as **`cookies.json`** in the script directory.
6. Run `python download_epstein_files.py`; it will load `cookies.json` automatically (and prefers it over `cookies.txt`).

---

The Cookie-Editor extension might not export all cookies (especially session cookies). If you still get 403, try getting cookies from DevTools:

## Method 1: Copy All Cookies from DevTools

1. **Open DevTools in Brave:**
   - Visit https://www.justice.gov/epstein/
   - Complete age verification
   - Press `F12` or `Cmd+Option+I` to open DevTools

2. **Go to Application/Storage Tab:**
   - Click "Application" tab (or "Storage" in some browsers)
   - In the left sidebar, expand "Cookies"
   - Click on `https://www.justice.gov`

3. **Copy All Cookies:**
   - You'll see a table with all cookies
   - **Right-click on the table** → "Copy" → "Copy table"
   - Or manually copy each cookie row

4. **Use the Cookie Loader Script:**
   ```bash
   python load_cookies_from_browser.py
   ```
   - Paste the cookies (one per line as `name=value`)
   - Or paste as JSON if you copied that format
   - Press Ctrl+D when done

## Method 2: Export via JavaScript Console

1. **Open Console Tab in DevTools**

2. **Run this JavaScript:**
   ```javascript
   // Copy this into the console and press Enter
   document.cookie.split(';').forEach(c => {
       const [name, value] = c.trim().split('=');
       console.log(`${name}=${value}`);
   });
   ```

3. **Copy the output** and paste into `load_cookies_from_browser.py`

## Method 3: Get Cookies via Network Tab

1. **Open Network Tab in DevTools**
2. **Reload the page** (F5)
3. **Click on any request** to justice.gov
4. **Go to "Headers" tab**
5. **Find "Cookie:" header**
6. **Copy the entire cookie string**

Then format it as `name=value` pairs separated by semicolons, and use the loader script.

## Important Cookies to Look For

Make sure you have these types of cookies:
- Session cookies (no expiration date)
- Authentication cookies
- CSRF tokens
- Age verification cookies
- Any cookies with "justice.gov" or "epstein" in the name

## After Extracting

The script will create:
- `cookies.json` - JSON format
- `cookies.txt` - Netscape format

Both will be automatically loaded by the download script.
