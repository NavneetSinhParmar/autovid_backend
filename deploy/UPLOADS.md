# 60 MB uploads from Netlify

Multipart uploads now go directly from the browser to the backend. Netlify only
handles the small authenticated `/api/uploads/config` request; its function
payload limit cannot be increased with an Nginx setting.

Deploy the revised frontend AND backend. In Netlify, set `UPLOAD_API_URL` to the
public HTTPS backend base URL (for example `https://api.your-domain.com`). It must
point to the API server, not the Netlify site or localhost. If omitted, the existing
`BACKEND_API_URL`, `DATA_API_PROFILE`, or `NEXT_PUBLIC_DATA_API_PROFILE` is used.

In the backend's active environment, set:

```dotenv
MAX_IMAGE_UPLOAD_MB=60
MAX_VIDEO_UPLOAD_MB=60
MAX_AUDIO_UPLOAD_MB=60
CORS_ORIGINS=https://super-lolly-559e09.netlify.app
```

Keep other required CORS origins in the comma-separated list. Restart the backend
after updating its environment. The API caps each file at 60 * 1024 * 1024 bytes;
existing format, duration and image dimension validation still applies.

In the HTTPS backend's active Nginx `server` block (or upload `location`), add:

```nginx
client_max_body_size 65M;
```

The extra space allows multipart form overhead. Check for lower limits in nested
locations and any other proxy in front of the API. Validate and reload:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

After deployment, inspect the browser Network panel: the multipart POST must
target the public backend origin, not `/api/backend/...` on Netlify. Test valid
image, video and music files below and at 60 MB, and confirm files above 60 MB
are rejected. An OPTIONS request should allow the Netlify origin and Authorization
header. If OPTIONS fails, check CORS and that Nginx forwards it to the API.

For the public template upload, verify the deployed preflight directly:

```bash
curl -i -X OPTIONS \
  'https://api.triaangle.co.in/public/templates/6acb9b7ccf6eaa3fb466d1cf/media' \
  -H 'Origin: https://super-lolly-559e09.netlify.app' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type'
```

Expect HTTP 200 and
`Access-Control-Allow-Origin: https://super-lolly-559e09.netlify.app`.
`CORS_ORIGINS` in the running process overrides `.env.local`, which overrides
`.env`; any of these values overrides the defaults in `app/core/settings.py`.
Use the exact origin with no trailing slash, and restart all API processes after
changing it. A 400 response containing `Disallowed CORS origin` indicates the
active allowlist is missing this origin. A redirect, proxy error, or response
without CORS headers should also be checked at the proxy: forward OPTIONS to
FastAPI without authentication or redirects.
