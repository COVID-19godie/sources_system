import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const latList = new Trend('lat_list');
const latSemantic = new Trend('lat_semantic');
const latGraph = new Trend('lat_graph');
const latPreview = new Trend('lat_preview');
const errAll = new Rate('err_all');

export const options = {
  vus: 100,
  duration: '10m',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

const baseUrl = __ENV.BASE_URL;
const token = __ENV.TOKEN;
const authHeaders = { Authorization: `Bearer ${token}` };
const ws = __ENV.WORKSPACE_ID || '2';
const rid = __ENV.PREVIEW_RESOURCE_ID || '27';

function reqList() {
  const res = http.get(`${baseUrl}/api/resources?all=true&status=approved`, { headers: authHeaders });
  latList.add(res.timings.duration);
  return res;
}
function reqSemantic() {
  const res = http.post(`${baseUrl}/api/resources/semantic-search`, JSON.stringify({ query: '牛顿第二定律' }), {
    headers: { ...authHeaders, 'Content-Type': 'application/json' },
  });
  latSemantic.add(res.timings.duration);
  return res;
}
function reqGraph() {
  const scope = Math.random() < 0.7 ? 'public' : 'mixed';
  const res = http.get(`${baseUrl}/api/rag/workspaces/${ws}/graph?scope=${scope}&include_format_nodes=true`, { headers: authHeaders });
  latGraph.add(res.timings.duration);
  return res;
}
function reqPreview() {
  const res = http.get(`${baseUrl}/api/resources/${rid}/preview`, { headers: authHeaders });
  latPreview.add(res.timings.duration);
  return res;
}

export default function () {
  let res;
  const r = Math.random();
  if (r < 0.50) res = reqList();
  else if (r < 0.80) res = reqSemantic();
  else if (r < 0.95) res = reqGraph();
  else res = reqPreview();
  const ok = check(res, { 'status 200': (x) => x.status === 200 });
  errAll.add(!ok);
  sleep(Math.random() * 0.2 + 0.05);
}
