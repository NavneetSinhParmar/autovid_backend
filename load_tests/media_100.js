import http from "k6/http";
import { check } from "k6";

const base = __ENV.BASE_URL || "http://localhost:8000";
const image = __ENV.IMAGE_TEMPLATE_ID;
const video = __ENV.VIDEO_TEMPLATE_ID;
if (!image || !video) throw new Error("Set IMAGE_TEMPLATE_ID and VIDEO_TEMPLATE_ID to active public templates");
const upload = __ENV.UPLOAD_FILE ? open(__ENV.UPLOAD_FILE, "b") : null;
export const options = {
  scenarios: {
    renders: { executor: "shared-iterations", vus: 100, iterations: 100, maxDuration: "60s", exec: "render" },
    ...(upload ? { uploads: { executor: "shared-iterations", vus: 100, iterations: 100, maxDuration: "120s", startTime: "10s", exec: "uploadMedia" } } : {}),
  },
  thresholds: {
    checks: ["rate==1"],
    http_req_failed: ["rate<0.01"],
    "http_req_duration{operation:render}": ["p(95)<2000"],
  },
};

export function render() {
  const template = __VU % 2 ? image : video;
  const response = http.post(`${base}/public/templates/${template}/preview`, JSON.stringify({ fields: {} }), {
    headers: { "Content-Type": "application/json" }, tags: { operation: "render" },
  });
  check(response, { "queued with job ID": r => r.status === 202 && Boolean(r.json("job_id")) });
}

export function uploadMedia() {
  const response = http.post(`${base}/public/templates/${image}/media`, {
    file: http.file(upload, __ENV.UPLOAD_FILENAME || "upload.png", __ENV.UPLOAD_MIME || "image/png"),
  }, { tags: { operation: "upload" } });
  check(response, { "upload stored": r => r.status === 200 && Boolean(r.json("media.file_url")) });
}
