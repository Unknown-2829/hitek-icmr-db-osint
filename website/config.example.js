/**
 * HiTek + ICMR DB OSINT — Frontend Configuration (v2)
 *
 * HOW TO USE:
 * 1. Copy this file to 'config.js' in the same folder.
 * 2. Set API_BASE to your deployed API URL (no trailing slash).
 *    - Use "" (empty string) to auto-target the same origin that serves
 *      the frontend (useful when the static UI is served by the API host).
 * 3. config.js is gitignored and will never be committed.
 */
window.APP_CONFIG = {
    // URL of your FastAPI backend instance
    API_BASE: "http://localhost:8000"
};
