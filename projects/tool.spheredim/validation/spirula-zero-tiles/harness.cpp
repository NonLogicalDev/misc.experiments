#include "backend/api/BackendRuntime.h"
#include "backend/vulkan/VulkanPipelines.h"
#include <vector>
#include <cstdio>
#include <cstdint>
#include <cmath>
#include <limits>
#include <fstream>
#include <cstdlib>
#include <string>
using namespace backend;
struct P { uint64_t fp32,q16,vbounds,rgb,vout,vgrid,vrgb,indices; int N,L,H,W,h,w,has,pad; };
static_assert(sizeof(P)==96);
void* upload(const std::vector<float>& v) { void* d=device_malloc(v.size()*4); memcpy_sync(d,v.data(),v.size()*4,MemcpyKind::HostToDevice); return d; }
int benchmark(int w, int mode) {
 int h=w/2,L=8,H=16,W=16; size_t n=(size_t)w*h*3, cells=(size_t)L*H*W*9;
 std::vector<float> grid(cells,0.0f), rgb(n,0.5f), grad(n,0.0f), dg(cells,0.0f), out(n,0.0f), bounds(((cells+255)/256)*2);
 std::vector<uint32_t> q16((cells+1)/2,0x80008000u), rgb16((n+1)/2,0x38003800u);
 for(size_t i=0;i<bounds.size();i+=2){bounds[i]=-0.1f;bounds[i+1]=0.1f;}
 for(int y=0;y<h;y++)for(int x=0;x<w;x++) if(mode==2 || (mode==1 && x>=w/2)) for(int c=0;c<3;c++) grad[((size_t)y*w+x)*3+c]=0.01f;
 void *dq=device_malloc(q16.size()*4);memcpy_sync(dq,q16.data(),q16.size()*4,MemcpyKind::HostToDevice);
 void *db=upload(bounds),*drgb=device_malloc(rgb16.size()*4),*dgrad=upload(grad),*ddg=upload(dg),*dout=upload(out);
 memcpy_sync(drgb,rgb16.data(),rgb16.size()*4,MemcpyKind::HostToDevice);
 P p{(uint64_t)dq,(uint64_t)dq,(uint64_t)db,(uint64_t)drgb,(uint64_t)dgrad,(uint64_t)ddg,(uint64_t)dout,(uint64_t)dq,1,L,H,W,h,w,0,0};
 auto *start=event_create(true),*end=event_create(true);
 for(int i=0;i<13;i++) {
  memset_sync(ddg,0,cells*4);event_record(start);
  if(!vk::dispatch(kDefaultStream,"bilagrid_ppisp.bilagrid_ppisp_bwd_tile",vk::SpecList{1,0,0,0,2},(w+15)/16,(h+15)/16,1,&p,sizeof(p)))return 6;
  event_record(end);event_synchronize(end);float ms=event_elapsed_ms(start,end);if(i>=3)printf("%.6f\n",ms);
 }
 event_destroy(start);event_destroy(end);device_free(dq);device_free(db);device_free(drgb);device_free(dgrad);device_free(ddg);device_free(dout);return 0;
}
int main(int argc,char**argv) {
 if(argc==4 && std::string(argv[1])=="--bench")return benchmark(std::atoi(argv[2]),std::atoi(argv[3]));
 if(argc!=2)return 2;
 std::ofstream output(argv[1],std::ios::binary);
 for(int format=0;format<2;format++) for(int mode=0;mode<4;mode++) for(int alias=0;alias<2;alias++) {
  int w=33,h=19,L=8,H=4,W=4; size_t n=w*h*3;
  std::vector<float> grid(L*H*W*9), rgb(n), grad(n), dg(grid.size(),0), out(n,-99);
  for(size_t i=0;i<grid.size();i++)grid[i]=0.001f*float(int(i%13)-6);
  for(size_t i=0;i<n;i++){rgb[i]=0.1f+float(i%71)/100; if(mode==1 && i%3==0 && (i/3)%w>15)grad[i]=0.02f; if(mode==2)grad[i]=0.01f*float(int(i%7)-3);}
  if(mode==3)grad[n-1]=std::numeric_limits<float>::quiet_NaN();
  std::vector<uint32_t> q16((grid.size()+1)/2,0x80008000u), rgb16((n+1)/2,0x38003800u);
  std::vector<float> bounds(((grid.size()+255)/256)*2);
  for(size_t i=0;i<bounds.size();i+=2){bounds[i]=-0.1f;bounds[i+1]=0.1f;}
  void *dgrid=upload(grid),*drgb=upload(rgb),*dgrad=upload(grad),*ddg=upload(dg),*dout=alias?dgrad:upload(out),*db=upload(bounds);
  void *dq=device_malloc(q16.size()*4),*drgb16=device_malloc(rgb16.size()*4);
  memcpy_sync(dq,q16.data(),q16.size()*4,MemcpyKind::HostToDevice);memcpy_sync(drgb16,rgb16.data(),rgb16.size()*4,MemcpyKind::HostToDevice);
  P p{(uint64_t)dgrid,(uint64_t)dq,(uint64_t)db,(uint64_t)(format?drgb16:drgb),(uint64_t)dgrad,(uint64_t)ddg,(uint64_t)dout,(uint64_t)dgrid,1,L,H,W,h,w,0,0};
  bool ok=vk::dispatch(kDefaultStream,"bilagrid_ppisp.bilagrid_ppisp_bwd_tile",vk::SpecList{(uint32_t)format,0,0,0,(uint32_t)(format?2:0)},(w+15)/16,(h+15)/16,1,&p,sizeof(p));
  memcpy_sync(out.data(),dout,n*4,MemcpyKind::DeviceToHost);memcpy_sync(dg.data(),ddg,dg.size()*4,MemcpyKind::DeviceToHost);
  if(!ok || last_error()){fprintf(stderr,"dispatch error %s\n",last_error());return 1;}
  if(mode==0){for(float v:out)if(v!=0)return 3;for(float v:dg)if(v!=0)return 4;}
  output.write((char*)out.data(),out.size()*4);output.write((char*)dg.data(),dg.size()*4);
  device_free(dgrid);device_free(drgb);device_free(dq);device_free(drgb16);device_free(db);if(!alias)device_free(dout);device_free(dgrad);device_free(ddg);
 }
 return output?0:5;
}
