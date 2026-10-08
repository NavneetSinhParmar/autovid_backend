import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  scenarios: {
    submit_100: { executor: "constant-vus", vus: 100, duration: "30s", startTime: "0s" },
    submit_250: { executor: "constant-vus", vus: 250, duration: "30s", startTime: "40s" },
    submit_500: { executor: "constant-vus", vus: 500, duration: "30s", startTime: "80s" },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://localhost:8000";
const token = __ENV.ACCESS_TOKEN;
const templateId = __ENV.TEMPLATE_ID;
const customerId = __ENV.CUSTOMER_ID;

export default function () {
  const response = http.post(
    `${baseUrl}/tasks/generate?template_id=${templateId}&customer_id=${customerId}`,
    null,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  check(response, {
    "accepted immediately": (result) => result.status === 202 && Boolean(result.json("job_id")),
  });
  sleep(1);
}
