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
