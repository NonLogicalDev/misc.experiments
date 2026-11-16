"""Transcribe release calib-warp boundary branch; not a GPU/backend test."""
import math

# 1D slice of a periodic ERP panorama. Vertical sampling remains in bounds.
gt = [0.2, 0.35, 0.55, 0.7, 0.8, 0.75, 0.65, 0.8]
mask = [1] * len(gt)
render = 0.73

def cubic_weights(t):
    t2, t3 = t*t, t*t*t
    return [-.5*t3+t2-.5*t, 1.5*t3-2.5*t2+1,
            -1.5*t3+2*t2+.5*t, .5*t3-.5*t2]

def cubic_sample(x, periodic):
    x0 = math.floor(x); w = cubic_weights(x-x0)
    taps = [gt[(x0-1+i)%len(gt)] if periodic else gt[min(max(x0-1+i,0),len(gt)-1)] for i in range(4)]
    # Exact per-channel anti-ringing clamp used in cw_sample_cubic.
    value = sum(taps[i]*w[i] for i in range(4))
    return min(max(value,min(taps[1:3])),max(taps[1:3]))

def release_target(x, flow):
    sx = x + flow
    return cubic_sample(sx,False) if 0 <= sx <= len(gt)-1 else render

def periodic_target(x, flow):
    return cubic_sample((x+flow)%len(gt),True)

def release_mask(x, flow):
    sx = x + flow
    ix = math.floor(sx + .5)
    return int(0 <= ix < len(gt) and mask[x] and mask[ix])

def periodic_mask(x, flow):
    ix = math.floor((x+flow)%len(gt) + .5) % len(gt)
    return int(bool(mask[x]) and bool(mask[ix]))

# A valid ground-truth neighbor lies just across longitude zero. The release
# path copies the predicted render and hence gives zero RGB residual; aux-mask
# path independently suppresses the sample if its nearest tap is out of bounds.
for x,flow in ((0,-.75),(7,.75)):
    actual = release_target(x,flow); expected = periodic_target(x,flow)
    assert actual == render and abs(expected-render) > .01
    assert release_mask(x,flow) == 0 and periodic_mask(x,flow) == 1
    print(f'x={x}, flow={flow:+.2f}: release_gt={actual:.6f}, periodic_gt={expected:.6f}, release_mask=0, periodic_mask=1, release_residual=0')
# Even a floating-point position inside [0,W-1] takes clamped cubic taps and
# therefore differs from periodic interpolation in a 2px neighborhood.
inside_x = .25
clamped = release_target(0, inside_x); periodic = periodic_target(0, inside_x)
assert abs(clamped-periodic) > 1e-6
print(f'x=0, flow={inside_x:+.2f}: release_cubic={clamped:.6f}, periodic_cubic={periodic:.6f}')
print('PASS: exact release branch/transcribed interpolation; not a GPU execution')

# A valid warped center does not guarantee that all 4×4 cubic RGB taps are
# valid. This 1D slice corresponds to constant columns in the 2D shader.
# The nearest mask reads row 4 (valid); the cubic reads row 3 (excluded).
def mask_boundary_target(excluded_value):
    samples = [excluded_value, 0.2, 0.8, 0.9]  # rows 3, 4, 5, 6
    weights = cubic_weights(.25)               # output center row 4 + .25
    result = sum(value * weight for value, weight in zip(samples, weights))
    return min(max(result, min(samples[1:3])), max(samples[1:3]))

zero = mask_boundary_target(0.0)
one = mask_boundary_target(1.0)
warped_mask = 1  # original row 4 and nearest row round(4.25) are both valid
assert warped_mask == 1 and abs(zero-one) > 0.05
print(f'valid output near exclusion: masked tap=0 -> target {zero:.6f}; masked tap=1 -> target {one:.6f}; warped_mask={warped_mask}')
print('PASS: masked-input dependency in source-transcribed cubic warp; not a GPU execution')
