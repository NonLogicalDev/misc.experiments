#!/usr/bin/env node
// An opt-in, short-lived pairing proxy. HTTP does not encrypt traffic on the LAN.
import http from 'node:http';
import net from 'node:net';
import {randomBytes,timingSafeEqual} from 'node:crypto';
import {pathToFileURL} from 'node:url';

const COOKIE='spheredim_session';
const equal=(a,b)=>{if(typeof a!=='string'||typeof b!=='string')return false;const x=Buffer.from(a),y=Buffer.from(b);return x.length===y.length&&timingSafeEqual(x,y)};
export function createProxy({upstreamPort=5178,token=randomBytes(32).toString('hex'),session=randomBytes(32).toString('hex'),expiresAt=Date.now()+300000}={}) {
  let paired=false;
  const server=http.createServer((req,res)=>{
    res.setHeader('Cache-Control','no-store');res.setHeader('Referrer-Policy','no-referrer');res.setHeader('X-Content-Type-Options','nosniff');
    if(req.method!=='GET'&&req.method!=='HEAD'){res.writeHead(405,{Allow:'GET, HEAD'});return res.end('Method not allowed')}
    let u;try{u=new URL(req.url,'http://localhost')}catch{res.writeHead(400);return res.end('Bad request')}
    if(u.pathname==='/pair'){
      if(req.method!=='GET'||paired||Date.now()>expiresAt||u.searchParams.getAll('token').length!==1||!equal(u.searchParams.get('token'),token)){res.writeHead(401);return res.end('Pairing denied')}
      paired=true;res.writeHead(303,{'Set-Cookie':`${COOKIE}=${session}; HttpOnly; SameSite=Strict; Path=/`,'Location':'/'});return res.end();
    }
    const cookies=(req.headers.cookie||'').split(';').map(x=>x.trim().split('='));const values=cookies.filter(x=>x[0]===COOKIE).map(x=>x[1]);
    if(!paired||values.length!==1||!equal(values[0],session)){res.writeHead(401);return res.end('Pairing required')}
    const headers={};for(const name of ['range','if-range','if-none-match','if-modified-since','accept','accept-encoding'])if(req.headers[name])headers[name]=req.headers[name];
    const upstream=http.request({hostname:'127.0.0.1',port:upstreamPort,path:req.url,method:req.method,headers},response=>{
      if(response.statusCode>=300&&response.statusCode<400&&response.headers.location){response.resume();res.writeHead(502);return res.end('Redirect blocked')}
      const safe={};for(const name of ['content-type','content-length','content-range','accept-ranges','etag','last-modified','content-encoding'])if(response.headers[name])safe[name]=response.headers[name];res.writeHead(response.statusCode||502,safe);response.pipe(res);
    });upstream.on('error',()=>{if(!res.headersSent){res.writeHead(502);res.end('Viewer unavailable')}else res.destroy()});req.on('aborted',()=>upstream.destroy());upstream.end();
  });
  server.on('upgrade',(_req,socket)=>socket.destroy());server.on('connect',(_req,socket)=>socket.destroy());
  return {server,token};
}
function main(){
  const host=process.env.SPHEREDIM_LAN_HOST,port=Number(process.env.SPHEREDIM_LAN_PORT||5179);
  if(!host||net.isIP(host)!==4||host.startsWith('127.')||host==='0.0.0.0'||!Number.isSafeInteger(port)||port<1||port>65535)throw Error('Set SPHEREDIM_LAN_HOST to a specific non-loopback IPv4 address and a valid port');
  const {server,token}=createProxy();server.listen(port,host,()=>{process.stdout.write(`Pair once within five minutes: http://${host}:${port}/pair?token=${token}\n`)});
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)main();
