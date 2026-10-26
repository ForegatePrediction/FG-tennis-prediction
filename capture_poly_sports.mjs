// Bounded, public, read-only Polymarket sports feed probe. Node.js 22+.
import fs from 'node:fs';
import path from 'node:path';

const requestedSeconds=Number(process.argv[2] || 30);
if(!Number.isFinite(requestedSeconds)||requestedSeconds<1||requestedSeconds>55)throw new Error('Duration must be 1..55 seconds');
const seconds=requestedSeconds;
const target = process.argv[3] || 'reports/poly-sports-probe.json';
const report = {url:'wss://sports-api.polymarket.com/ws',started_at:new Date().toISOString(),
  requested_seconds:seconds,connected:false,messages:0,pings:0,tennis:[],schema_samples:[],errors:[]};
const ws = new WebSocket(report.url);
let finished=false;
function done(){
  if(finished)return;finished=true;report.finished_at=new Date().toISOString();
  fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,JSON.stringify(report,null,2));
  console.log(JSON.stringify({connected:report.connected,messages:report.messages,pings:report.pings,
    tennis_messages:report.tennis.length,errors:report.errors,output:target}));
  try{ws.close();}catch{};setTimeout(()=>process.exit(report.connected&&report.errors.length===0?0:1),100);
}
ws.addEventListener('open',()=>{report.connected=true;report.connected_at=new Date().toISOString();});
ws.addEventListener('message',event=>{
  const raw=String(event.data);report.messages++;
  if(raw.toLowerCase()==='ping'){report.pings++;ws.send('pong');return;}
  let value;try{value=JSON.parse(raw);}catch{return;}
  for(const item of Array.isArray(value)?value:[value]){
    if(report.schema_samples.length<3)report.schema_samples.push(item);
    const slug=String(item.slug||item.payload?.slug||'');
    const league=String(item.leagueAbbreviation||item.sport||item.league||'');
    if(/^(atp|wta|itf|wimbledon|daviscup|bjkcup)(-|$)/i.test(slug)||/^(atp|wta|itf|tennis|wimbledon|daviscup|bjkcup)(-|$)/i.test(league)){
      const received_at=new Date().toISOString();
      const update=item.last_update||item.payload?.last_update;
      report.tennis.push({received_at,source_age_ms:update?Date.now()-Date.parse(update):null,value:item});
    }
  }
});
ws.addEventListener('error',event=>{report.errors.push(event.message||'WebSocket connection error');done();});
ws.addEventListener('close',event=>{report.close_code=event.code;done();});
setTimeout(done,seconds*1000);
