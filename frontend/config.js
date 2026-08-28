// Where the API lives, for deployments that serve this page and the backend
// from different hosts. Left unset, the page uses whatever origin served it,
// which is what a single-domain deployment wants.
//
// Set it when the two are split, for example a static bucket in front of an
// API on its own domain:
//
//   window.API_BASE = "https://api.example.com";
//
// Local development needs nothing here: opened from devserve.py on port 5501,
// or from a file:// URL, the page falls back to http://127.0.0.1:8000.
