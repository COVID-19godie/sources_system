import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';
const latList=new Trend('lat_list');
const latSemantic=new Trend('lat_semantic');
const latGraph=new Trend('lat_graph');
const latPreview=new Trend('lat_preview');
const errAll=new Rate('err_all');
export const options={vus:20,duration:'5m',thresholds:{http_req_failed:['rate<0.01'],http_req_duration:['p(95)<500']},summaryTrendStats:['avg','med','p(90)','p(95)','p(99)','max']};
const base=__ENV.BASE_URL, token=__ENV.TOKEN, ws=__ENV.WORKSPACE_ID||'2', rid=__ENV.PREVIEW_RESOURCE_ID||'27';
const h={Authorization:`Bearer ${token}`};
export default function(){
  let r,res;
  const p=Math.random();
  if(p<0.5){res=http.get(`${base}/api/resources?all=true&status=approved`,{headers:h});latList.add(res.timings.duration);}
  else if(p<0.8){res=http.post(`${base}/api/resources/semantic-search`,JSON.stringify({query:'行星运动'}),{headers:{...h,'Content-Type':'application/json'}});latSemantic.add(res.timings.duration);}
  else if(p<0.95){res=http.get(`${base}/api/rag/workspaces/${ws}/graph?scope=public&include_format_nodes=true`,{headers:h});latGraph.add(res.timings.duration);}
  else {res=http.get(`${base}/api/resources/${rid}/preview`,{headers:h});latPreview.add(res.timings.duration);} 
  r=check(res,{'status 200':x=>x.status===200}); errAll.add(!r); sleep(Math.random()*0.2+0.05);
}
