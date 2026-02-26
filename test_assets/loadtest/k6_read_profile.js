import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';

const latList = new Trend('lat_list');
const latSemantic = new Trend('lat_semantic');
const latGraph = new Trend('lat_graph');
const latPreview = new Trend('lat_preview');
const errList = new Rate('err_list');
const errSemantic = new Rate('err_semantic');
const errGraph = new Rate('err_graph');
const errPreview = new Rate('err_preview');
const totalReq = new Counter('req_total');

export const options = {
  stages: [
    { duration: '1m', target: 20 },
    { duration: '2m', target: 20 },
    { duration: '1m', target: 50 },
    { duration: '2m', target: 50 },
    { duration: '1m', target: 100 },
    { duration: '2m', target: 100 },
    { duration: '1m', target: 150 },
    { duration: '2m', target: 150 },
    { duration: '1m', target: 100 },
    { duration: '30m', target: 100 },
    { duration: '1m', target: 0 },
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
    lat_list: ['p(95)<500'],
    lat_semantic: ['p(95)<500'],
    lat_graph: ['p(95)<500'],
    lat_preview: ['p(95)<500'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

const baseUrl = __ENV.BASE_URL || 'http://host.docker.internal:8000';
const token = __ENV.TOKEN || '';
const workspaceId = __ENV.WORKSPACE_ID || '2';
const previewResourceId = __ENV.PREVIEW_RESOURCE_ID || '27';

const authHeaders = { Authorization: `Bearer ${token}` };

const listUrls = [
  '/api/resources?all=true',
  '/api/resources?all=true&status=approved',
  '/api/resources?all=true&file_format=pdf',
  '/api/resources?all=true&resource_kind=tutorial&difficulty=基础',
  '/api/resources?all=true&q=行星运动',
];

const semanticQueries = ['行星运动', '机械能守恒', '平抛运动', '电磁感应', '牛顿第二定律', '圆周运动'];

function hitList() {
  const url = `${baseUrl}${listUrls[Math.floor(Math.random() * listUrls.length)]}`;
  const res = http.get(url, { headers: authHeaders, tags: { endpoint: 'list' } });
  totalReq.add(1);
  latList.add(res.timings.duration);
  const ok = check(res, { 'list status 200': (r) => r.status === 200 });
  errList.add(!ok);
}

function hitSemantic() {
  const q = semanticQueries[Math.floor(Math.random() * semanticQueries.length)];
  const res = http.post(`${baseUrl}/api/resources/semantic-search`, JSON.stringify({ query: q }), {
    headers: { ...authHeaders, 'Content-Type': 'application/json' },
    tags: { endpoint: 'semantic' },
  });
  totalReq.add(1);
  latSemantic.add(res.timings.duration);
  const ok = check(res, { 'semantic status 200': (r) => r.status === 200 });
  errSemantic.add(!ok);
}

function hitGraph() {
  const scope = Math.random() < 0.7 ? 'public' : 'mixed';
  const res = http.get(`${baseUrl}/api/rag/workspaces/${workspaceId}/graph?scope=${scope}&include_format_nodes=true`, {
    headers: authHeaders,
    tags: { endpoint: 'graph', scope },
  });
  totalReq.add(1);
  latGraph.add(res.timings.duration);
  const ok = check(res, { 'graph status 200': (r) => r.status === 200 });
  errGraph.add(!ok);
}

function hitPreview() {
  const res = http.get(`${baseUrl}/api/resources/${previewResourceId}/preview`, {
    headers: authHeaders,
    tags: { endpoint: 'preview' },
  });
  totalReq.add(1);
  latPreview.add(res.timings.duration);
  const ok = check(res, { 'preview status 200': (r) => r.status === 200 });
  errPreview.add(!ok);
}

export default function () {
  const r = Math.random();
  if (r < 0.50) hitList();
  else if (r < 0.80) hitSemantic();
  else if (r < 0.95) hitGraph();
  else hitPreview();
  sleep(Math.random() * 0.35 + 0.05);
}
