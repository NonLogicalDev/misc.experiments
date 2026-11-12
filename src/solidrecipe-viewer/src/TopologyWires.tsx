import { useEffect, useLayoutEffect, useMemo } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { Line2 } from 'three/addons/lines/Line2.js'
import { LineGeometry } from 'three/addons/lines/LineGeometry.js'
import { LineMaterial } from 'three/addons/lines/LineMaterial.js'

type Point = [number, number, number]
type SideIds = [number | null, number | null, number | null]
export type WireFace = {
  index: number
  triangles: [Point, Point, Point][]
  boundary_complete?: boolean
  edge_ids?: SideIds[]
  segment_ids?: SideIds[]
}
export type WireEdge = { index: number; points: Point[] }
type WireInspection = { edges: Record<string, unknown>[] }
type WireTopology = { faces: WireFace[]; edges: WireEdge[] }

/** Refuse the experimental path if the library's shader no longer has our known anchors. */
export function wireShaderSupported(): boolean {
  try {
    const material = new LineMaterial()
    try {
      const matchesOnce = (source: string, anchor: string) => source.split(anchor).length === 2
      return (
        matchesOnce(material.vertexShader, 'uniform float linewidth;') &&
        matchesOnce(material.vertexShader, 'vec3 ndcEnd = clipEnd.xyz / clipEnd.w;') &&
        matchesOnce(material.fragmentShader, 'uniform float opacity;') &&
        matchesOnce(material.fragmentShader, 'float alpha = opacity;')
      )
    } finally {
      material.dispose()
    }
  } catch {
    return false
  }
}

/** Fail closed: an edge is eligible only if both distinct incident face uses certify every segment. */
export function certifiedEdges(topology: WireTopology, inspection: WireInspection): Set<number> {
  const result = new Set<number>()
  // Zero is background; each displayed triangle needs a distinct 24-bit ID.
  if (topology.faces.reduce((sum, face) => sum + face.triangles.length, 0) > 0xffffff) return result
  const faces = new Map(topology.faces.map((face) => [face.index, face]))
  for (const edge of topology.edges) {
    const record = inspection.edges[edge.index]
    const incident = record?.adjacent_faces
    const count = edge.points.length - 1
    if (
      !Array.isArray(incident) ||
      incident.length !== 2 ||
      incident[0] === incident[1] ||
      count < 1
    )
      continue
    let complete = true
    for (const id of incident) {
      const face = faces.get(id as number)
      if (
        !face?.boundary_complete ||
        !face.edge_ids ||
        !face.segment_ids ||
        face.edge_ids.length !== face.triangles.length ||
        face.segment_ids.length !== face.triangles.length
      ) {
        complete = false
        break
      }
      const found = new Set<number>()
      for (let triangle = 0; triangle < face.triangles.length; triangle++) {
        if (
          !Array.isArray(face.edge_ids[triangle]) ||
          face.edge_ids[triangle].length !== 3 ||
          !Array.isArray(face.segment_ids[triangle]) ||
          face.segment_ids[triangle].length !== 3
        ) {
          complete = false
          break
        }
        for (let side = 0; side < 3; side++) {
          if (face.edge_ids[triangle][side] !== edge.index) continue
          const ordinal = face.segment_ids[triangle][side]
          if (
            ordinal === null ||
            !Number.isInteger(ordinal) ||
            ordinal < 0 ||
            ordinal >= count ||
            found.has(ordinal)
          ) {
            complete = false
            break
          }
          found.add(ordinal)
        }
      }
      if (found.size !== count) complete = false
    }
    if (complete) result.add(edge.index)
  }
  return result
}

function edgeGeometry(
  face: WireFace,
  eligible: Set<number>,
  selected: Set<number>,
  hovered: number | null,
): THREE.BufferGeometry {
  const positions: number[] = [],
    bary: number[] = [],
    flags: number[] = []
  for (let i = 0; i < face.triangles.length; i++) {
    const ids = face.edge_ids?.[i] ?? [null, null, null]
    const sideFlags = ids.map((id) =>
      id === null || !eligible.has(id) ? -1 : selected.has(id) ? 2 : hovered === id ? 1 : 0,
    )
    for (let j = 0; j < 3; j++) {
      positions.push(...face.triangles[i][j])
      bary.push(
        ...[
          [1, 0, 0],
          [0, 1, 0],
          [0, 0, 1],
        ][j],
      )
      flags.push(...sideFlags)
    }
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  geometry.setAttribute('bary', new THREE.Float32BufferAttribute(bary, 3))
  geometry.setAttribute('sideFlags', new THREE.Float32BufferAttribute(flags, 3))
  return geometry
}

/** Draw only certified B-rep boundary sides, never arbitrary mesh diagonals. */
function BoundaryFace({
  face,
  eligible,
  selected,
  hovered,
}: {
  face: WireFace
  eligible: Set<number>
  selected: Set<number>
  hovered: number | null
}) {
  const { gl } = useThree()
  const geometry = useMemo(
    () => edgeGeometry(face, eligible, selected, hovered),
    [face, eligible, selected, hovered],
  )
  useEffect(() => () => geometry.dispose(), [geometry])
  return (
    <mesh geometry={geometry} renderOrder={2} raycast={() => null}>
      <shaderMaterial
        transparent
        depthWrite={false}
        side={THREE.DoubleSide}
        uniforms={{ pixelRatio: { value: gl.getPixelRatio() } }}
        vertexShader={`attribute vec3 bary; attribute vec3 sideFlags; varying vec3 baryW; varying vec3 flags; void main(){vec4 p=projectionMatrix*modelViewMatrix*vec4(position,1.); baryW=bary*p.w; flags=sideFlags; gl_Position=p;}`}
        fragmentShader={`uniform float pixelRatio; varying vec3 baryW; varying vec3 flags; void main(){vec3 b=baryW*gl_FragCoord.w; vec3 d=abs(b)/max(fwidth(b),vec3(.000001)); vec3 sd=vec3(d.z,d.x,d.y); float a=0.; float selected=0.; float hovered=0.; for(int i=0;i<3;i++){float flag=flags[i]; if(flag>=0.){float hi=step(.5,flag); float isSelected=step(1.5,flag); float halfWidth=mix(.75,1.5,hi)*pixelRatio; float coverage=1.-smoothstep(max(0.,halfWidth-.5*pixelRatio),halfWidth+.5*pixelRatio,sd[i]); a=max(a,coverage); selected=max(selected,coverage*isSelected); hovered=max(hovered,coverage*(hi-isSelected));}} if(a<=.001) discard; vec3 c=mix(vec3(.20,.21,.27),vec3(.36,.82,1.),hovered/max(a,.001)); c=mix(c,vec3(1.,.82,.36),selected/max(a,.001)); gl_FragColor=vec4(c,a);}`}
      />
    </mesh>
  )
}

function idColor(id: number): THREE.Vector3 {
  return new THREE.Vector3((id & 255) / 255, ((id >> 8) & 255) / 255, ((id >> 16) & 255) / 255)
}
type SegmentTriangle = { triangleId: number; opposite: Point }

type IdResources = {
  scene: THREE.Scene
  target: THREE.WebGLRenderTarget
  geometries: THREE.BufferGeometry[]
  materials: THREE.Material[]
  segments: Map<string, SegmentTriangle>
}
function makeIdResources(topology: WireTopology): IdResources {
  const scene = new THREE.Scene(),
    geometries: THREE.BufferGeometry[] = [],
    materials: THREE.Material[] = [],
    segments = new Map<string, SegmentTriangle>()
  let nextTriangleId = 1
  const material = new THREE.ShaderMaterial({
    side: THREE.DoubleSide,
    vertexShader:
      'attribute vec3 triangleId; varying vec3 id; void main(){id=triangleId;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader: 'varying vec3 id; void main(){gl_FragColor=vec4(id,1.);}',
  })
  materials.push(material)
  for (const face of topology.faces) {
    const geometry = new THREE.BufferGeometry(),
      colors: number[] = []
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(face.triangles.flat(2), 3))
    for (let triangle = 0; triangle < face.triangles.length; triangle++) {
      const triangleId = nextTriangleId++,
        color = idColor(triangleId)
      for (let vertex = 0; vertex < 3; vertex++) colors.push(color.x, color.y, color.z)
      for (let side = 0; side < 3; side++) {
        const edge = face.edge_ids?.[triangle]?.[side],
          segment = face.segment_ids?.[triangle]?.[side]
        if (edge !== null && edge !== undefined && segment !== null && segment !== undefined)
          segments.set(`${face.index}:${edge}:${segment}`, {
            triangleId,
            opposite: face.triangles[triangle][(side + 2) % 3],
          })
      }
    }
    geometry.setAttribute('triangleId', new THREE.Float32BufferAttribute(colors, 3))
    geometries.push(geometry)
    scene.add(new THREE.Mesh(geometry, material))
  }
  const target = new THREE.WebGLRenderTarget(1, 1, {
    minFilter: THREE.NearestFilter,
    magFilter: THREE.NearestFilter,
    depthBuffer: true,
  })
  target.texture.colorSpace = THREE.NoColorSpace
  target.depthTexture = new THREE.DepthTexture(1, 1, THREE.UnsignedIntType)
  return { scene, target, geometries, materials, segments }
}

/** Render the nearest triangle ID and depth without modifying the user's visible scene. */
function VisibilityTarget({
  resources,
  scale,
  onFailure,
}: {
  resources: IdResources
  scale: number
  onFailure: () => void
}) {
  useFrame(({ gl, camera }) => {
    const size = gl.getDrawingBufferSize(new THREE.Vector2())
    const old = gl.getRenderTarget(),
      color = gl.getClearColor(new THREE.Color()).clone(),
      alpha = gl.getClearAlpha()
    try {
      if (resources.target.width !== size.x * scale || resources.target.height !== size.y * scale)
        resources.target.setSize(size.x * scale, size.y * scale)
      gl.setRenderTarget(resources.target)
      const context = gl.getContext()
      if (
        context.isContextLost() ||
        context.checkFramebufferStatus(context.FRAMEBUFFER) !== context.FRAMEBUFFER_COMPLETE
      )
        throw new Error('Topology ID framebuffer unavailable')
      gl.setClearColor(0, 0)
      gl.clear(true, true, true)
      gl.render(resources.scene, camera)
    } catch {
      onFailure()
    } finally {
      gl.setRenderTarget(old)
      gl.setClearColor(color, alpha)
    }
    // Drei OrbitControls updates at -1; capture the same camera used by the main frame.
  }, -0.5)
  return null
}

/**
 * Exterior coverage uses snapshot triangle IDs and unbiased depth, not a line offset.
 * Coverage is estimated from single-sampled ID buffers (optionally at 2× dimensions),
 * so subpixel occlusion transitions and very close geometry remain approximations.
 * Ambiguous planes/probes use an unbiased local depth approximation rather than
 * hiding the whole edge; that local fallback may have the older width artifacts.
 */
function ExteriorEdge({
  edge,
  incident,
  resources,
  selected,
  hovered,
  scale,
}: {
  edge: WireEdge
  incident: number[]
  resources: IdResources
  selected: boolean
  hovered: boolean
  scale: number
}) {
  const { gl, camera } = useThree()
  const line = useMemo(() => {
    const geometry = new LineGeometry()
    geometry.setPositions(edge.points.flat())
    const idsA: number[] = [],
      idsB: number[] = [],
      pointsA: number[] = [],
      pointsB: number[] = []
    for (let ordinal = 0; ordinal < edge.points.length - 1; ordinal++) {
      const first = resources.segments.get(`${incident[0]}:${edge.index}:${ordinal}`)
      const second = resources.segments.get(`${incident[1]}:${edge.index}:${ordinal}`)
      // Eligibility and the segment map are derived from the same snapshot.
      if (!first || !second) throw new Error('Certified edge segment mapping disappeared')
      idsA.push(...idColor(first.triangleId).toArray())
      idsB.push(...idColor(second.triangleId).toArray())
      pointsA.push(...first.opposite)
      pointsB.push(...second.opposite)
    }
    geometry.setAttribute(
      'wireTriangleA',
      new THREE.InstancedBufferAttribute(new Float32Array(idsA), 3),
    )
    geometry.setAttribute(
      'wireTriangleB',
      new THREE.InstancedBufferAttribute(new Float32Array(idsB), 3),
    )
    geometry.setAttribute(
      'wireOppositeA',
      new THREE.InstancedBufferAttribute(new Float32Array(pointsA), 3),
    )
    geometry.setAttribute(
      'wireOppositeB',
      new THREE.InstancedBufferAttribute(new Float32Array(pointsB), 3),
    )
    const material = new LineMaterial({
      color: '#343744',
      linewidth: 1.5,
      depthTest: false,
      depthWrite: false,
      alphaToCoverage: true,
    })
    material.onBeforeCompile = (shader) => {
      shader.uniforms.triangleIds = { value: resources.target.texture }
      shader.uniforms.sceneDepth = { value: resources.target.depthTexture }
      shader.uniforms.screenSize = { value: gl.getDrawingBufferSize(new THREE.Vector2()) }
      shader.uniforms.nearDistance = { value: camera.near }
      shader.uniforms.deviceRatio = { value: gl.getPixelRatio() }
      shader.uniforms.idScale = { value: scale }
      material.userData.shader = shader
      shader.vertexShader = shader.vertexShader
        .replace(
          'uniform float linewidth;',
          `attribute vec3 wireTriangleA; attribute vec3 wireTriangleB; attribute vec3 wireOppositeA; attribute vec3 wireOppositeB; varying vec3 wireIdA; varying vec3 wireIdB; varying vec3 wireStart; varying vec3 wireEnd; varying vec3 wireThirdA; varying vec3 wireThirdB; varying float wireValid; uniform float nearDistance; uniform float linewidth;`,
        )
        .replace(
          'vec3 ndcEnd = clipEnd.xyz / clipEnd.w;',
          `vec3 ndcEnd = clipEnd.xyz / clipEnd.w; wireIdA=wireTriangleA; wireIdB=wireTriangleB; vec4 ws=start; vec4 we=end; wireValid=1.; if(ws.z>=-nearDistance && we.z>=-nearDistance){wireValid=0.;}else{if(ws.z > -nearDistance) ws=mix(ws,we,clamp((-nearDistance-ws.z)/(we.z-ws.z),0.,1.)); if(we.z > -nearDistance) we=mix(we,ws,clamp((-nearDistance-we.z)/(ws.z-we.z),0.,1.));} vec4 cs=projectionMatrix*ws; vec4 ce=projectionMatrix*we; vec4 ca=projectionMatrix*modelViewMatrix*vec4(wireOppositeA,1.); vec4 cb=projectionMatrix*modelViewMatrix*vec4(wireOppositeB,1.); if(cs.w<=0.||ce.w<=0.||ca.w<=0.||cb.w<=0.){wireValid=0.;wireStart=vec3(0.);wireEnd=vec3(0.);wireThirdA=vec3(0.);wireThirdB=vec3(0.);}else{wireStart=cs.xyz/cs.w;wireEnd=ce.xyz/ce.w;wireThirdA=ca.xyz/ca.w;wireThirdB=cb.xyz/cb.w;}`,
        )
      shader.fragmentShader = shader.fragmentShader
        .replace(
          'uniform float opacity;',
          `uniform float opacity; uniform sampler2D triangleIds; uniform sampler2D sceneDepth; uniform vec2 screenSize; uniform float deviceRatio; uniform float idScale; varying vec3 wireIdA; varying vec3 wireIdB; varying vec3 wireStart; varying vec3 wireEnd; varying vec3 wireThirdA; varying vec3 wireThirdB; varying float wireValid; float wireOwned(vec3 id){return 1.-step(.001,min(distance(id,wireIdA),distance(id,wireIdB)));}`,
        )
        .replace(
          'float alpha = opacity;',
          `vec2 uv=gl_FragCoord.xy/screenSize;
float own=wireOwned(texture2D(triangleIds,uv).rgb);
if(idScale>1.5){
  vec2 q=vec2(.25)/screenSize;
  own=.25*(wireOwned(texture2D(triangleIds,uv+vec2(-q.x,-q.y)).rgb)+wireOwned(texture2D(triangleIds,uv+vec2(q.x,-q.y)).rgb)+wireOwned(texture2D(triangleIds,uv+vec2(-q.x,q.y)).rgb)+wireOwned(texture2D(triangleIds,uv+vec2(q.x,q.y)).rgb));
}
if(own>.999) discard;
float fragmentDepth=texture2D(sceneDepth,uv).r;
bool wireFallback=wireValid<.5;
if(!wireFallback){
  vec2 ws=(wireStart.xy*.5+.5)*screenSize; vec2 we=(wireEnd.xy*.5+.5)*screenSize;
  vec2 delta=we-ws; float lengthSquared=dot(delta,delta);
  if(lengthSquared<1e-12){wireFallback=true;} else {
    float t=clamp(dot(gl_FragCoord.xy-ws,delta)/lengthSquared,0.,1.);
    float centerDepth=mix(wireStart.z,wireEnd.z,t)*.5+.5;
    if(centerDepth>texture2D(sceneDepth,mix(ws,we,t)/screenSize).r) discard;
    vec2 aa=wireStart.xy; vec2 bb=wireEnd.xy; vec2 cc=wireThirdA.xy; float cz=wireThirdA.z;
    vec2 pp=uv*2.-1.; vec2 dd=wireThirdB.xy;
    float fragmentSide=(bb.x-aa.x)*(pp.y-aa.y)-(bb.y-aa.y)*(pp.x-aa.x);
    float sideA=(bb.x-aa.x)*(cc.y-aa.y)-(bb.y-aa.y)*(cc.x-aa.x);
    float sideB=(bb.x-aa.x)*(dd.y-aa.y)-(bb.y-aa.y)*(dd.x-aa.x);
    if(sideA*sideB>=0.){
      vec2 normal=normalize(vec2(-delta.y,delta.x));
      vec2 inside=(mix(ws,we,t)+normal*sign(sideA)*2.*deviceRatio)/screenSize;
      vec3 visibleId=texture2D(triangleIds,inside).rgb;
      if(distance(visibleId,wireIdA)<.001){}
      else if(distance(visibleId,wireIdB)<.001){cc=dd;cz=wireThirdB.z;}
      else wireFallback=true;
    }else if(fragmentSide*sideB>0.){cc=dd;cz=wireThirdB.z;}
    float det=(bb.x-aa.x)*(cc.y-aa.y)-(bb.y-aa.y)*(cc.x-aa.x);
    if(abs(det)<1e-10){wireFallback=true;} else if(!wireFallback){
      float u=((pp.x-aa.x)*(cc.y-aa.y)-(pp.y-aa.y)*(cc.x-aa.x))/det;
      float v=((bb.x-aa.x)*(pp.y-aa.y)-(bb.y-aa.y)*(pp.x-aa.x))/det;
      float planeDepth=(wireStart.z+u*(wireEnd.z-wireStart.z)+v*(cz-wireStart.z))*.5+.5;
      if(planeDepth>fragmentDepth) discard;
    }
  }
}
// Ambiguous fragments use an unbiased per-pixel depth approximation. The ID
// target is not the offset display buffer, so this is not identical to fallback.
if(wireFallback && gl_FragCoord.z>fragmentDepth) discard;
float alpha=opacity*(1.-own);
`,
        )
    }
    const object = new Line2(geometry, material)
    object.computeLineDistances()
    object.renderOrder = 3
    object.raycast = () => undefined
    return object
  }, [edge, incident, resources, gl, camera, scale])
  useEffect(
    () => () => {
      line.geometry.dispose()
      line.material.dispose()
    },
    [line],
  )
  useFrame(() => {
    const shader = line.material.userData.shader as
      | {
          uniforms: {
            screenSize: { value: THREE.Vector2 }
            nearDistance: { value: number }
            deviceRatio: { value: number }
          }
        }
      | undefined
    if (!shader) return
    shader.uniforms.screenSize.value.copy(gl.getDrawingBufferSize(new THREE.Vector2()))
    shader.uniforms.nearDistance.value = camera.near
    shader.uniforms.deviceRatio.value = gl.getPixelRatio()
  })
  line.material.linewidth = selected || hovered ? 3 : 1.5
  line.material.color.set(selected ? '#ffd15c' : hovered ? '#6cd4ff' : '#343744')
  return <primitive object={line} dispose={null} />
}

export function CertifiedWires({
  topology,
  inspection,
  eligible,
  selected,
  hovered,
  scale,
  onFailure,
}: {
  topology: WireTopology
  inspection: WireInspection
  eligible: Set<number>
  selected: Set<number>
  hovered: number | null
  scale: number
  onFailure: () => void
}) {
  const { gl } = useThree()
  const resources = useMemo(() => makeIdResources(topology), [topology])
  // Register before the browser's first paint/R3F frame so a shader compile error
  // cannot normally occur before the fallback handler is installed.
  useLayoutEffect(() => {
    const previous = gl.debug.onShaderError
    const previousCheck = gl.debug.checkShaderErrors
    gl.debug.checkShaderErrors = true
    const handler: NonNullable<typeof gl.debug.onShaderError> = (
      context,
      program,
      vertex,
      fragment,
    ) => {
      const sources = `${context.getShaderSource(vertex) ?? ''}\n${context.getShaderSource(fragment) ?? ''}`
      if (
        sources.includes('wireOwned') ||
        sources.includes('triangleId') ||
        sources.includes('sideFlags')
      )
        queueMicrotask(onFailure)
      if (previous) previous(context, program, vertex, fragment)
      else
        console.error(
          'WebGL shader failed:',
          context.getProgramInfoLog(program),
          context.getShaderInfoLog(vertex),
          context.getShaderInfoLog(fragment),
        )
    }
    const lost = () => onFailure()
    gl.debug.onShaderError = handler
    gl.domElement.addEventListener('webglcontextlost', lost)
    return () => {
      if (gl.debug.onShaderError === handler) gl.debug.onShaderError = previous
      gl.debug.checkShaderErrors = previousCheck
      gl.domElement.removeEventListener('webglcontextlost', lost)
    }
  }, [gl, onFailure])
  useEffect(
    () => () => {
      resources.target.dispose()
      resources.geometries.forEach((g) => {
        g.dispose()
      })
      resources.materials.forEach((m) => {
        m.dispose()
      })
    },
    [resources],
  )
  return (
    <>
      <VisibilityTarget resources={resources} scale={scale} onFailure={onFailure} />
      {topology.faces
        .filter((f) => f.boundary_complete)
        .map((face) => (
          <BoundaryFace
            key={face.index}
            face={face}
            eligible={eligible}
            selected={selected}
            hovered={hovered}
          />
        ))}
      {topology.edges
        .filter((e) => eligible.has(e.index))
        .map((edge) => (
          <ExteriorEdge
            key={edge.index}
            edge={edge}
            incident={inspection.edges[edge.index].adjacent_faces as number[]}
            resources={resources}
            selected={selected.has(edge.index)}
            hovered={hovered === edge.index}
            scale={scale}
          />
        ))}
    </>
  )
}
