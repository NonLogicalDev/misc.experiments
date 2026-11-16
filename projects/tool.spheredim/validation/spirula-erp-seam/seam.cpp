// Compare native ERP alpha and gradients with a periodic CPU reference.
#include <engine/Engine.h>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <vector>

int W = 256, H = 128;
const char* camera_model="EQUIRECTANGULAR";
constexpr double pi = 3.14159265358979323846;
using V3 = std::array<double, 3>;
using M3 = std::array<V3, 3>;
TorchTensorView tensor(const void* p, std::vector<int64_t> shape) {
    return std::make_tuple((uint64_t)p, uint32_t(4), std::move(shape));
}
TorchTensorView empty() { return tensor(nullptr, {0}); }
struct Scene {
    V3 mean{.137, .081, 2};
    std::array<double,4> quat{1,0,0,0};
    V3 log_scale{std::log(.2),std::log(.2),std::log(.2)};
    double opacity=2;
};
struct Result {
    std::vector<float> alpha;
    V3 mean_grad{}, scale_grad{};
    double opacity_grad=0;
};
double dot(V3 a, V3 b) { double r=0; for(int i=0;i<3;i++) r+=a[i]*b[i]; return r; }
M3 rotation(const Scene& s) {
    auto [w,x,y,z]=s.quat;
    return {{{1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)},
             {2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)},
             {2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)}}};
}
Scene half_turn(Scene s) {
    s.mean[0]=-s.mean[0]; s.mean[2]=-s.mean[2];
    auto [w,x,y,z]=s.quat; s.quat={-y,z,w,-x};
    return s;
}
std::vector<float> weights() {
    std::vector<float> w(W*H);
    for(int y=0;y<H;y++) for(int x=0;x<W;x++)
        w[y*W+x]=1+.2*std::sin(2*pi*(x+.5)/W)+.1*std::cos(pi*(y+.5)/H);
    return w;
}
Result render(const Scene& s, const char* primitive, bool packed, const std::vector<float>* backward_weights=nullptr) {
    // Uploads persist on device, so independent fixtures need independent scenes.
    engine_reset();
    std::vector<float> means(s.mean.begin(),s.mean.end()), quat(s.quat.begin(),s.quat.end());
    std::vector<float> scales(s.log_scale.begin(),s.log_scale.end()), opacity{float(s.opacity)}, dc(3,1), sh;
    set_data_3dgs(1,tensor(means.data(),{1,3}),tensor(quat.data(),{1,4}),
        tensor(scales.data(),{1,3}),tensor(opacity.data(),{1,1}),
        tensor(dc.data(),{1,3}),tensor(sh.data(),{1,0,3}),0);
    std::vector<float> view{1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1};
    bool erp=std::strcmp(camera_model,"EQUIRECTANGULAR")==0;
    std::vector<float> intr{erp?float(W/(2*pi)):96.f,erp?float(H/pi):96.f,W/2.f,H/2.f};
    std::vector<float> distortion(kCameraDistortionParams,0);
    set_camera_params(W,H,camera_model,"NONE",tensor(view.data(),{1,4,4}),
        tensor(intr.data(),{1,4}),tensor(distortion.data(),{1,kCameraDistortionParams}));
    const float black[3]={0,0,0}; engine_init_background_color(black,0,false);
    forward_3dgs(primitive,0,packed,false,0);
    backend::device_synchronize();
    if(const char* e=backend::last_error()) throw std::runtime_error(e);
    Result r; r.alpha.resize(W*H);
    engine_copy_render_to_host(empty(),empty(),tensor(r.alpha.data(),{1,H,W,1}),empty(),empty());
    for(float& a:r.alpha) a=1-a;
    if(backward_weights) {
        auto seed=*backward_weights; for(float& w:seed) w=-w;
        std::vector<float> zero_rgb(W*H*3,0), zero_depth(W*H,0);
        engine_backward_from_render_grad(tensor(zero_rgb.data(),{1,H,W,3}),
            tensor(zero_depth.data(),{1,H,W,1}),tensor(seed.data(),{1,H,W,1}));
        std::vector<float> mg(3),sg(3),og(1);
        engine_copy_grads_to_host(tensor(mg.data(),{1,3}),empty(),tensor(sg.data(),{1,3}),
            tensor(og.data(),{1,1}),empty(),empty());
        for(int i=0;i<3;i++) { r.mean_grad[i]=mg[i]; r.scale_grad[i]=sg[i]; }
        r.opacity_grad=og[0];
    }
    return r;
}
std::vector<float> reference(const Scene& s, bool gut) {
    M3 rot=rotation(s), cov{};
    for(int i=0;i<3;i++) for(int j=0;j<3;j++) for(int k=0;k<3;k++)
        cov[i][j]+=rot[i][k]*std::exp(2*s.log_scale[k])*rot[j][k];
    auto [mx,my,mz]=s.mean;
    double horizontal=std::hypot(mx,mz), r2=dot(s.mean,s.mean), f=W/(2*pi);
    V3 ju{f*mz/(horizontal*horizontal),0,-f*mx/(horizontal*horizontal)};
    V3 jv{-f*mx*my/(r2*horizontal),f*horizontal/r2,-f*mz*my/(r2*horizontal)};
    double c00=.3,c01=0,c11=.3;
    for(int i=0;i<3;i++) for(int j=0;j<3;j++) {
        c00+=ju[i]*cov[i][j]*ju[j]; c01+=ju[i]*cov[i][j]*jv[j]; c11+=jv[i]*cov[i][j]*jv[j];
    }
    double det=c00*c11-c01*c01, a=c11/det,b=-c01/det,c=c00/det;
    double u=f*std::atan2(mx,mz)+W/2.,v=f*std::atan2(my,horizontal)+H/2.;
    double opacity=1/(1+std::exp(-s.opacity));
    std::vector<float> out(W*H);
    for(int y=0;y<H;y++) for(int x=0;x<W;x++) {
        double sigma;
        if(!gut) {
            double dx=u-(x+.5),dy=v-(y+.5);
            // Choose one periodic representative minimizing the full conic.
            dx-=W*std::round((dx+(b/a)*dy)/W);
            sigma=.5*(a*dx*dx+2*b*dx*dy+c*dy*dy);
        } else {
            double lon=(x+.5-W/2.)/f,lat=(y+.5-H/2.)/f;
            V3 ray{std::cos(lat)*std::sin(lon),std::sin(lat),std::cos(lat)*std::cos(lon)};
            V3 origin{},direction{};
            for(int i=0;i<3;i++) for(int j=0;j<3;j++) {
                double inv=rot[j][i]*std::exp(-s.log_scale[i]);
                origin[i]-=inv*s.mean[j]; direction[i]+=inv*ray[j];
            }
            double t=-dot(origin,direction)/dot(direction,direction);
            if(t<=0) continue; // The native ray evaluator rejects negative closest depth.
            V3 closest{}; for(int i=0;i<3;i++) closest[i]=origin[i]+t*direction[i];
            sigma=.5*dot(closest,closest);
        }
        double alpha=std::min(.999,opacity*std::exp(-sigma));
        if(alpha>1./255) out[y*W+x]=float(alpha);
    }
    return out;
}
double relative(const std::vector<float>& actual,const std::vector<float>& expected,int shift=0) {
    double mass=0,error=0;
    for(int y=0;y<H;y++) for(int x=0;x<W;x++) {
        double a=actual[y*W+x],b=expected[y*W+(x+shift)%W];
        if(!std::isfinite(a)||!std::isfinite(b)) return INFINITY;
        mass+=b; error+=std::abs(a-b);
    }
    return mass>1e-6?error/mass:INFINITY;
}
double loss(const Result& r, const std::vector<float>& w) { double sum=0; for(int i=0;i<W*H;i++) sum+=w[i]*double(r.alpha[i]); return sum; }
int main(int argc,char** argv) {
    std::setvbuf(stdout,nullptr,_IOLBF,0);
    bool gradients=argc>1&&std::strcmp(argv[1],"--gradients")==0, failed=false;
    Scene ordinary,small,tilted,wide;
    small.log_scale={std::log(.025),std::log(.025),std::log(.025)};
    tilted.log_scale={std::log(.7),std::log(.1),std::log(.2)};
    tilted.quat={std::cos(pi/12),0,0,std::sin(pi/12)};
    wide.log_scale={std::log(4.),std::log(.1),std::log(.2)};
    if(argc==3&&std::strcmp(argv[1],"--pinhole")==0) {
        W=192;H=120;camera_model="PINHOLE";
        FILE* file=std::fopen(argv[2],"wbx");
        if(!file) throw std::runtime_error("Pinhole output must be a new writable file");
        for(const char* primitive:{"3dgs","3dgut"}) for(bool packed:{false,true}) {
            for(const Scene& scene:{ordinary,tilted}) {
                auto w=weights();auto result=render(scene,primitive,packed,&w);
                std::vector<float> values=result.alpha;
                for(double v:result.mean_grad) values.push_back(float(v));
                for(double v:result.scale_grad) values.push_back(float(v));
                values.push_back(float(result.opacity_grad));
                for(float v:values) if(!std::isfinite(v)) throw std::runtime_error("Nonfinite pinhole output");
                if(std::fwrite(values.data(),sizeof(float),values.size(),file)!=values.size()) throw std::runtime_error("Pinhole write failed");
            }
        }
        std::fclose(file);std::puts("PINHOLE 192x120: saved eight alpha/gradient controls");return 0;
    }
    for(const char* primitive:{"3dgs","3dgut"}) for(bool packed:{false,true}) {
        int index=0;
        for(const Scene& scene:{small,ordinary,tilted,wide}) {
            auto front=render(scene,primitive,packed), back=render(half_turn(scene),primitive,packed);
            bool gut=std::strcmp(primitive,"3dgut")==0;
            double wrap=relative(back.alpha,front.alpha,W/2);
            double cpu=relative(back.alpha,reference(half_turn(scene),gut));
            bool ok=wrap<=.01&&cpu<=.01;
            std::printf("%s packed=%d case=%d wrap_L1=%.9g cpu_L1=%.9g %s\n",primitive,packed,index++,wrap,cpu,ok?"PASS":"FAIL");
            failed|=!ok;
        }
        if(gradients) {
            Scene s=half_turn(ordinary);
            auto base=render(s,primitive,packed); auto w=weights();
            // Exclude the discontinuous alpha cutoff from the derivative oracle.
            // This fixed cotangent is shared by the analytic and perturbed calls.
            for(int i=0;i<W*H;i++) if(base.alpha[i]<.02f) w[i]=0;
            auto analytic=render(s,primitive,packed,&w);
            for(int parameter=0;parameter<7;parameter++) {
                Scene plus=s,minus=s; double step=.0005;
                double gpu;
                if(parameter<3) { plus.mean[parameter]+=step; minus.mean[parameter]-=step; gpu=analytic.mean_grad[parameter]; }
                else if(parameter<6) { plus.log_scale[parameter-3]+=step; minus.log_scale[parameter-3]-=step; gpu=analytic.scale_grad[parameter-3]; }
                else { plus.opacity+=step;minus.opacity-=step;gpu=analytic.opacity_grad; }
                auto rp=render(plus,primitive,packed),rm=render(minus,primitive,packed);
                int flips=0;for(int i=0;i<W*H;i++) flips+=w[i]!=0&&((rp.alpha[i]>0)!=(rm.alpha[i]>0));
                double numeric=(loss(rp,w)-loss(rm,w))/(2*step);
                bool ok=std::isfinite(gpu)&&std::isfinite(numeric)&&flips==0&&std::abs(gpu-numeric)<=.015+.02*std::abs(numeric);
                std::printf("%s packed=%d grad=%d analytic=%.9g numeric=%.9g cutoff_changes=%d %s\n",primitive,packed,parameter,gpu,numeric,flips,ok?"PASS":"FAIL");
                failed|=!ok;
            }
        }
    }
    return failed?1:0;
}
