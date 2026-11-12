import {
  Component,
  StrictMode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react'
import { createRoot } from 'react-dom/client'
import { Canvas, useThree, type ThreeEvent } from '@react-three/fiber'
import { GizmoHelper, GizmoViewport, Line, OrbitControls } from '@react-three/drei'
import { LevaPanel, useControls, useCreateStore, folder, button } from 'leva'
import * as THREE from 'three'
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js'
import { CertifiedWires, certifiedEdges, wireShaderSupported, type WireFace } from './TopologyWires'
import './style.css'

// Meshes are display artifacts. CAD identity and exact measurements remain in the core.
type ParameterValue = string | number | boolean
type Parameter = {
  name: string
  default: ParameterValue
  value: ParameterValue
  description: string
  unit: string | null
  minimum: number | null
  maximum: number | null
  step: number | null
  options: ParameterValue[] | null
}
type Values = Record<string, ParameterValue>
type Preset = Values | { output: string; values: Values }
type Presets = Record<string, Preset>

type LoadedMesh = { name: string; object: THREE.Group; bounds: THREE.Box3; frame: boolean }
type Point = [number, number, number]
type TopologyFace = WireFace
type TopologyEdge = { index: number; points: Point[] }
type Topology = { faces: TopologyFace[]; edges: TopologyEdge[] }
type Highlights = { faces: TopologyFace[]; edges: TopologyEdge[] }
type Selection = { faces: number[]; edges: number[] }
type Inspection = { faces: Record<string, unknown>[]; edges: Record<string, unknown>[] }
type TopologyState = {
  session: string
  revision: number
  selectionRevision: number
  topology: Topology
  highlights: Highlights
  inspection: Inspection
  name: string
  output: string
  values: Values
}
type SelectionMode = 'face' | 'edge'

/** A failed certified-wire allocation or malformed mapping must not remove the model. */
class WireErrorBoundary extends Component<
  { onFailure: () => void; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch() {
    this.props.onFailure()
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}

type ControlProps = {
  parameters: Parameter[]
  values: Values
  outputs: string[]
  output: string
  topology: TopologyState | null
  mode: SelectionMode
  hashes: Record<string, string>
  presets: Presets
  presetName: string
  selectedPreset: string
  status: string
  change: (name: string, value: ParameterValue) => void
  chooseOutput: (name: string) => void
  setMode: (mode: SelectionMode) => void
  copy: () => void
  clear: () => void
  apply: () => void
  setPresetName: (name: string) => void
  setSelectedPreset: (name: string) => void
  save: () => void
  load: () => void
  open: () => void
}

// Leva identifies controls globally by their leaf key, even inside folders. Encode
// authored names so no parameter can collide with one of our own control keys.
function parameterKey(name: string): string {
  return `parameter:${encodeURIComponent(name).replaceAll('.', '%2E')}`
}

/** One native Leva panel owns selection, modeling and presets. */
function Controls(props: ControlProps) {
  const store = useCreateStore()
  const callback = useRef(props)
  const syncing = useRef(false)
  callback.current = props
  const specKey = JSON.stringify([
    props.parameters.map(({ value: _value, ...spec }) => spec),
    props.outputs,
    Object.keys(props.presets).sort(),
  ])
  const changed = (fn: () => void, initial: boolean) => {
    if (!initial && !syncing.current) fn()
  }
  const [, setControls] = useControls(
    () => {
      const model = Object.fromEntries(
        props.parameters.map((parameter) => {
          const config: Record<string, unknown> = {
            value: props.values[parameter.name] ?? parameter.value,
            label: `${parameter.description || parameter.name}${parameter.unit ? ` (${parameter.unit})` : ''}`,
            onChange: (value: ParameterValue, _path: string, context: { initial: boolean }) => {
              changed(() => callback.current.change(parameter.name, value), context.initial)
            },
          }
          if (parameter.options) config.options = parameter.options
          else if (typeof parameter.default === 'number') {
            if (parameter.minimum !== null) config.min = parameter.minimum
            if (parameter.maximum !== null) config.max = parameter.maximum
            if (parameter.step !== null) config.step = parameter.step
          }
          return [parameterKey(parameter.name), config]
        }),
      )
      if (props.outputs.length > 1)
        model['system:output'] = {
          label: 'Output',
          value: props.output,
          options: props.outputs,
          onChange: (value: string, _path: string, context: { initial: boolean }) =>
            changed(() => callback.current.chooseOutput(value), context.initial),
        }
      model['system:apply'] = { ...button(() => callback.current.apply()), label: 'Apply' }
      const selection = {
        'system:mode': {
          label: 'Mode',
          value: props.mode,
          options: { Edges: 'edge', Faces: 'face' },
          onChange: (value: SelectionMode, _path: string, context: { initial: boolean }) =>
            changed(() => callback.current.setMode(value), context.initial),
        },
        'system:faces': {
          label: 'Faces',
          value: props.topology?.highlights.faces.map((item) => item.index).join(', ') || 'none',
          disabled: true,
        },
        'system:edges': {
          label: 'Edges',
          value: props.topology?.highlights.edges.map((item) => item.index).join(', ') || 'none',
          disabled: true,
        },
        'system:copy': { ...button(() => callback.current.copy()), label: 'Copy Python' },
        'system:clear': { ...button(() => callback.current.clear()), label: 'Clear' },
        'Snapshot SHA-256 (not identity)': folder(
          {
            'system:hashes': { label: 'Records', value: 'none', disabled: true },
          },
          { collapsed: true },
        ),
      }
      return {
        Selection: folder(selection),
        Model: folder(model as never),
        Presets: folder(
          {
            'system:preset-name': {
              label: 'Name',
              value: props.presetName,
              onChange: (value: string, _path: string, context: { initial: boolean }) =>
                changed(() => callback.current.setPresetName(value), context.initial),
            },
            'system:preset-saved': {
              label: 'Saved',
              value: props.selectedPreset,
              options: ['', ...Object.keys(props.presets).sort()],
              onChange: (value: string, _path: string, context: { initial: boolean }) =>
                changed(() => callback.current.setSelectedPreset(value), context.initial),
            },
            'system:save': { ...button(() => callback.current.save()), label: 'Save' },
            'system:load': { ...button(() => callback.current.load()), label: 'Load' },
          },
          { collapsed: true },
        ),
        'system:open': { ...button(() => callback.current.open()), label: 'Open OBJ' },
        'system:status': { label: 'Status', value: props.status, disabled: true },
      } as never
    },
    { store },
    [specKey],
  )
  useEffect(() => {
    syncing.current = true
    setControls(
      Object.fromEntries(
        props.parameters
          .filter((parameter) => parameter.name in props.values)
          .map((parameter) => [parameterKey(parameter.name), props.values[parameter.name]]),
      ),
    )
    syncing.current = false
  }, [props.values, props.parameters, setControls])
  useEffect(() => {
    setControls({ 'system:status': props.status })
  }, [props.status, setControls])
  useEffect(() => {
    const hashes = (['faces', 'edges'] as const).flatMap((kind) =>
      (props.topology?.highlights[kind] ?? []).map(
        (item) =>
          `${kind} ${item.index}: ${props.hashes[`${kind}:${item.index}`] ?? 'calculating'}`,
      ),
    )
    syncing.current = true
    setControls({
      'system:faces':
        props.topology?.highlights.faces.map((item) => item.index).join(', ') || 'none',
      'system:edges':
        props.topology?.highlights.edges.map((item) => item.index).join(', ') || 'none',
      'system:hashes': hashes.join(' | ') || 'none',
      'system:mode': props.mode,
      'system:preset-name': props.presetName,
      'system:preset-saved': props.selectedPreset,
      ...(props.outputs.length > 1 ? { 'system:output': props.output } : {}),
    })
    syncing.current = false
  }, [
    props.topology,
    props.hashes,
    props.mode,
    props.presetName,
    props.selectedPreset,
    props.outputs,
    props.output,
    setControls,
  ])
  return (
    <div className="leva-position">
      <LevaPanel store={store} titleBar={{ title: 'solidrecipe', drag: false, filter: false }} />
    </div>
  )
}

// Canonicalize object keys recursively before hashing the inspection record. The digest
// describes this snapshot's record, not a stable identity or a geometric proof.
function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  const object = value as Record<string, unknown>
  return `{${Object.keys(object)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(object[key])}`)
    .join(',')}}`
}

function pythonLiteral(value: unknown): string {
  if (value === null) return 'None'
  if (value === true) return 'True'
  if (value === false) return 'False'
  if (Array.isArray(value)) return `[${value.map(pythonLiteral).join(', ')}]`
  if (typeof value === 'object')
    return `{${Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${pythonLiteral(key)}: ${pythonLiteral(item)}`)
      .join(', ')}}`
  return JSON.stringify(value)
}

async function recordHash(record: Record<string, unknown>): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(record))
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

/** The overlay uses the server's tessellation of the same B-rep, not OBJ triangle guesses. */
function FaceOverlay({
  face,
  selected,
  pickable,
  onPick,
}: {
  face: TopologyFace
  selected: boolean
  pickable: boolean
  onPick: (index: number) => void
}) {
  const geometry = useMemo(() => {
    const result = new THREE.BufferGeometry()
    result.setAttribute('position', new THREE.Float32BufferAttribute(face.triangles.flat(2), 3))
    result.computeVertexNormals()
    return result
  }, [face])
  useEffect(() => () => geometry.dispose(), [geometry])
  if (!selected && !pickable) return null
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: this is a Three.js canvas object, not an HTML element.
    <mesh
      geometry={geometry}
      onClick={
        pickable
          ? (event: ThreeEvent<MouseEvent>) => {
              event.stopPropagation()
              onPick(face.index)
            }
          : undefined
      }
      raycast={pickable ? undefined : () => null}
    >
      <meshBasicMaterial
        color="#ffcf54"
        side={THREE.DoubleSide}
        transparent
        opacity={selected ? 0.55 : 0}
        depthWrite={false}
      />
    </mesh>
  )
}

function TopologyOverlay({
  state,
  mode,
  model,
  onPick,
  onWireFailure,
}: {
  state: TopologyState
  mode: SelectionMode
  model: LoadedMesh
  onPick: (kind: SelectionMode, index: number) => void
  onWireFailure: () => void
}) {
  const [hoveredEdge, setHoveredEdge] = useState<number | null>(null)
  const [wireFailed, setWireFailed] = useState(false)
  const failWire = useCallback(() => {
    setWireFailed(true)
    onWireFailure()
  }, [onWireFailure])
  const { gl, size } = useThree()
  useEffect(() => {
    gl.domElement.style.cursor = hoveredEdge === null ? '' : 'pointer'
    return () => {
      gl.domElement.style.cursor = ''
    }
  }, [gl, hoveredEdge])
  const faces = useMemo(
    () => new Set(state.highlights.faces.map((face) => face.index)),
    [state.highlights],
  )
  const edges = useMemo(
    () => new Set(state.highlights.edges.map((edge) => edge.index)),
    [state.highlights],
  )
  const shaderSupported = useMemo(wireShaderSupported, [])
  // Bound the color+depth target to roughly 128 MiB before driver overhead.
  // Use single resolution when 2× exceeds the budget; fall back entirely if 1× cannot fit.
  const targetWidth = Math.ceil(size.width * gl.getPixelRatio())
  const targetHeight = Math.ceil(size.height * gl.getPixelRatio())
  const maxTexture = gl.capabilities.maxTextureSize
  const fits = (factor: number) =>
    targetWidth > 0 &&
    targetHeight > 0 &&
    targetWidth * factor <= maxTexture &&
    targetHeight * factor <= maxTexture &&
    targetWidth * targetHeight * factor * factor <= 16_777_216
  const targetScale = fits(2) ? 2 : fits(1) ? 1 : 0
  const eligibility = useMemo(() => {
    try {
      return {
        edges:
          !wireFailed && targetScale > 0 && shaderSupported
            ? certifiedEdges(state.topology, state.inspection)
            : new Set<number>(),
        failed: false,
      }
    } catch {
      return { edges: new Set<number>(), failed: true }
    }
  }, [shaderSupported, wireFailed, targetScale, state.topology, state.inspection])
  const eligible = eligibility.edges
  useEffect(() => {
    if (
      eligibility.failed ||
      !shaderSupported ||
      (targetWidth > 0 && targetHeight > 0 && targetScale === 0)
    )
      failWire()
  }, [eligibility.failed, shaderSupported, targetWidth, targetHeight, targetScale, failWire])
  function edgeIsVisible(event: ThreeEvent<MouseEvent | PointerEvent>) {
    // Line2 raycasts provide the closest point on the actual line. Test visibility
    // toward that point, not toward the mouse: the generous screen-space hit area
    // often places the mouse over a neighboring face rather than exactly on an edge.
    const point = (event as unknown as { pointOnLine?: THREE.Vector3 }).pointOnLine
    if (!point) return false
    const direction = point.clone().sub(event.ray.origin)
    const distance = direction.length()
    const raycaster = new THREE.Raycaster(event.ray.origin, direction.normalize())
    const front = raycaster.intersectObject(model.object, true)[0]
    const size = model.bounds.getSize(new THREE.Vector3()).length()
    return !front || front.distance >= distance - Math.max(size * 0.0003, 0.02)
  }
  return (
    <>
      {eligible.size > 0 && (
        <WireErrorBoundary onFailure={failWire}>
          <CertifiedWires
            topology={state.topology}
            inspection={state.inspection}
            eligible={eligible}
            selected={edges}
            hovered={hoveredEdge}
            scale={targetScale}
            onFailure={failWire}
          />
        </WireErrorBoundary>
      )}
      {state.topology.faces.map((face) => (
        <FaceOverlay
          key={face.index}
          face={face}
          selected={faces.has(face.index)}
          pickable={mode === 'face'}
          onPick={(index) => onPick('face', index)}
        />
      ))}
      {state.topology.edges
        .filter((edge) => edge.points.length >= 2)
        .map((edge) => (
          <group key={edge.index}>
            {!eligible.has(edge.index) && (
              <Line
                points={edge.points}
                color={
                  edges.has(edge.index)
                    ? '#ffd15c'
                    : hoveredEdge === edge.index
                      ? '#6cd4ff'
                      : '#343744'
                }
                // Line2 uses CSS-pixel widths, so outlines stay legible as the camera zooms.
                lineWidth={edges.has(edge.index) || hoveredEdge === edge.index ? 3 : 1.5}
                depthTest
                depthWrite={false}
                renderOrder={2}
                alphaToCoverage
                raycast={() => null}
              />
            )}
            {mode === 'edge' && (
              <Line
                points={edge.points}
                lineWidth={18}
                transparent
                opacity={0}
                depthWrite={false}
                onClick={(event: ThreeEvent<MouseEvent>) => {
                  if (edgeIsVisible(event)) {
                    event.stopPropagation()
                    onPick('edge', edge.index)
                  }
                }}
                onPointerMove={(event: ThreeEvent<PointerEvent>) => {
                  if (edgeIsVisible(event)) {
                    event.stopPropagation()
                    setHoveredEdge(edge.index)
                  }
                }}
                onPointerOut={() => setHoveredEdge((old) => (old === edge.index ? null : old))}
              />
            )}
          </group>
        ))}
    </>
  )
}

function disposeObject(object: THREE.Object3D) {
  object.traverse((child) => {
    if (
      child instanceof THREE.Mesh ||
      child instanceof THREE.Line ||
      child instanceof THREE.Points
    ) {
      child.geometry.dispose()
      const materials = Array.isArray(child.material) ? child.material : [child.material]
      materials.forEach((material) => {
        material.dispose()
      })
    }
  })
}

/** Parse a preview before replacing the visible model, so a bad file leaves it intact. */
function parseMesh(name: string, text: string, frame = true): LoadedMesh {
  const object = new OBJLoader().parse(text)
  try {
    let meshCount = 0
    object.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        meshCount++
        const materials = Array.isArray(child.material) ? child.material : [child.material]
        materials.forEach((material) => {
          material.dispose()
        })
        child.material = new THREE.MeshStandardMaterial({
          color: '#a990ec',
          roughness: 0.68,
          metalness: 0.05,
          side: THREE.DoubleSide,
          // Separate coplanar B-rep outlines and selected-face overlays from the
          // display surface while keeping depth testing for hidden geometry.
          polygonOffset: true,
          polygonOffsetFactor: 1,
          polygonOffsetUnits: 1,
        })
      }
    })
    const bounds = new THREE.Box3().setFromObject(object)
    if (!meshCount || bounds.isEmpty())
      throw new Error('No renderable faces were found in this OBJ file.')
    return { name, object, bounds, frame }
  } catch (error) {
    disposeObject(object)
    throw error
  }
}

function Model({
  model,
  topology,
  mode,
  onPick,
  onWireFailure,
}: {
  model: LoadedMesh
  topology: TopologyState | null
  mode: SelectionMode
  onPick: (kind: SelectionMode, index: number) => void
  onWireFailure: () => void
}) {
  const { camera, invalidate } = useThree()
  const center = useMemo(() => model.bounds.getCenter(new THREE.Vector3()), [model])
  useEffect(() => {
    // Later rebuilds preserve the user's camera; manual loads and the first live model frame it.
    if (!model.frame) {
      invalidate()
      return
    }
    const size = model.bounds.getSize(new THREE.Vector3())
    const extent = Math.max(size.x, size.y, size.z, 1)
    camera.position.copy(center).add(new THREE.Vector3(-extent * 1.3, -extent * 1.7, extent * 1.2))
    if (camera instanceof THREE.PerspectiveCamera) {
      camera.near = Math.max(extent / 1000, 0.001)
      camera.far = extent * 100
      camera.updateProjectionMatrix()
    }
    invalidate()
  }, [camera, center, invalidate, model])
  return (
    <>
      <primitive object={model.object} dispose={null} />
      {topology && (
        <TopologyOverlay
          state={topology}
          mode={mode}
          model={model}
          onPick={onPick}
          onWireFailure={onWireFailure}
        />
      )}
      <OrbitControls makeDefault target={center} />
    </>
  )
}

function Viewport({
  model,
  topology,
  mode,
  onPick,
  onWireFailure,
}: {
  model: LoadedMesh | null
  topology: TopologyState | null
  mode: SelectionMode
  onPick: (kind: SelectionMode, index: number) => void
  onWireFailure: () => void
}) {
  return (
    <section className="viewport" aria-label="3D mesh viewport">
      <Canvas
        frameloop="demand"
        dpr={[1, 2]}
        gl={{ antialias: true }}
        camera={{ position: [45, -60, 45], up: [0, 0, 1], fov: 45, near: 0.01, far: 100000 }}
      >
        <color attach="background" args={['#151a22']} />
        <hemisphereLight args={[0xf6f1ff, 0x303644, 2]} />
        <directionalLight position={[25, -40, 70]} intensity={2} />
        <gridHelper
          args={[200, 20, 0x667080, 0x313945]}
          rotation={[Math.PI / 2, 0, 0]}
          position={[
            0,
            0,
            model
              ? model.bounds.min.z -
                Math.max(model.bounds.getSize(new THREE.Vector3()).length() * 0.02, 0.1)
              : 0,
          ]}
        />
        {model ? (
          <Model
            model={model}
            topology={topology}
            mode={mode}
            onPick={onPick}
            onWireFailure={onWireFailure}
          />
        ) : (
          <OrbitControls makeDefault />
        )}
        <GizmoHelper alignment="bottom-left" margin={[70, 70]}>
          <GizmoViewport axisColors={['#ed6d6d', '#80c879', '#72aaf2']} labelColor="#ffffff" />
        </GizmoHelper>
      </Canvas>
    </section>
  )
}

function App() {
  const fileInput = useRef<HTMLInputElement>(null)
  const [model, setModel] = useState<LoadedMesh | null>(null)
  const [topology, setTopology] = useState<TopologyState | null>(null)
  const [selectionMode, setSelectionMode] = useState<SelectionMode>('edge')
  const [selectionMessage, setSelectionMessage] = useState('')
  const [topologyError, setTopologyError] = useState('')
  const [wireError, setWireError] = useState('')
  const reportWireFailure = useCallback(() => {
    setWireError('Certified wire rendering unavailable; showing ordinary outlines.')
  }, [])
  const [hashResult, setHashResult] = useState<{
    scope: string
    values: Record<string, string>
  } | null>(null)
  const selectionPending = useRef<{
    session: string
    revision: number
    acknowledgedRevision: number | null
  } | null>(null)
  const selectionQueue = useRef<
    Array<{ session: string; revision: number; kind: SelectionMode | 'clear'; index?: number }>
  >([])
  const [queueTick, setQueueTick] = useState(0)
  const manualMesh = useRef(false)
  const [status, setStatus] = useState('Open an OBJ mesh generated by the CLI to begin.')
  const [errorDetails, setErrorDetails] = useState<string | null>(null)
  const revision = useRef(0)
  const session = useRef('')
  const parameterKey = useRef('')
  const editingParameters = useRef(false)
  const [parameters, setParameters] = useState<Parameter[]>([])
  const [outputs, setOutputs] = useState<string[]>([])
  const [selectedOutput, setSelectedOutput] = useState('')
  const [values, setValues] = useState<Values>({})
  const [presets, setPresets] = useState<Presets>({})
  const [presetName, setPresetName] = useState('')
  const [selectedPreset, setSelectedPreset] = useState('')
  const [parameterMessage, setParameterMessage] = useState('')
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const controller = new AbortController()
    // The CLI serves this optional endpoint. Standalone Vite has no preview server, so stop
    // polling if its fallback page is returned instead of JSON.
    async function poll() {
      let shouldContinue = true
      try {
        const response = await fetch('/api/preview', {
          cache: 'no-store',
          signal: controller.signal,
        })
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
          shouldContinue = false
          return
        }
        const data: {
          session: string
          revision: number
          name: string
          mesh: string | null
          error: string | null
          building: boolean
          parameters: Parameter[]
          outputs: string[]
          output: string | null
          topology?: Topology | null
          highlights?: Highlights | null
          inspection?: Inspection | null
          selection_revision?: number
          selection_error?: string | null
        } = await response.json()
        if (stopped) return
        const sessionChanged = data.session !== session.current
        if (sessionChanged) {
          session.current = data.session
          selectionPending.current = null
          selectionQueue.current = []
          setTopology(null)
        }
        setTopologyError(data.selection_error ?? '')
        const specs = data.parameters ?? []
        const key = JSON.stringify([data.output, specs.map(({ value: _value, ...spec }) => spec)])
        if (key !== parameterKey.current) {
          parameterKey.current = key
          setValues(Object.fromEntries(specs.map((p) => [p.name, p.value])))
        }
        setParameters(specs)
        setOutputs(data.outputs ?? [])
        if (data.mesh && (sessionChanged || data.revision !== revision.current)) {
          selectionPending.current = null
          selectionQueue.current = []
          const loaded = parseMesh(data.name, data.mesh, revision.current === 0)
          setModel(loaded)
          revision.current = data.revision
          manualMesh.current = false
          setTopology(null)
          // A different client or a server restart can change values. Preserve an
          // unfinished local edit, but otherwise keep controls aligned with the mesh.
          if (!editingParameters.current) {
            setValues(Object.fromEntries(specs.map((p) => [p.name, p.value])))
          }
          setSelectedOutput(data.output ?? '')
        }
        if (
          data.mesh &&
          data.revision === revision.current &&
          !manualMesh.current &&
          data.topology &&
          data.highlights &&
          data.inspection
        ) {
          const pending = selectionPending.current
          if (
            pending &&
            (pending.session !== data.session ||
              pending.revision !== data.revision ||
              (pending.acknowledgedRevision !== null &&
                (data.selection_revision ?? 0) >= pending.acknowledgedRevision))
          ) {
            selectionPending.current = null
            setQueueTick((value) => value + 1)
          }
          setTopology((old) =>
            old?.session === data.session &&
            old.revision === data.revision &&
            old.selectionRevision === data.selection_revision
              ? old
              : {
                  session: data.session,
                  revision: data.revision,
                  selectionRevision: data.selection_revision ?? 0,
                  topology: data.topology as Topology,
                  highlights: data.highlights as Highlights,
                  inspection: data.inspection as Inspection,
                  name: data.name,
                  output: data.output ?? '',
                  values: Object.fromEntries(specs.map((p) => [p.name, p.value])),
                },
          )
        }
        if (data.error) {
          setErrorDetails(data.error)
          setStatus('Rebuild failed · showing last successful model')
        } else if (data.building) {
          setErrorDetails(null)
          setStatus(`Rebuilding ${data.name}…`)
        } else if (data.mesh) {
          setParameterMessage((old) => (old === 'Updating preview…' ? '' : old))
          setErrorDetails(null)
          setStatus(`${data.name} · live preview`)
        }
      } catch (error) {
        if (!stopped)
          setStatus(
            error instanceof Error
              ? `Preview unavailable: ${error.message}`
              : 'Preview unavailable.',
          )
      } finally {
        if (!stopped && shouldContinue) timer = setTimeout(poll, 250)
      }
    }
    void poll()
    return () => {
      stopped = true
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [])
  const hashScope = topology
    ? `${topology.session}:${topology.revision}:${topology.selectionRevision}`
    : ''
  const hashes = hashResult?.scope === hashScope ? hashResult.values : {}
  useEffect(() => {
    let cancelled = false
    setHashResult(null)
    if (!topology)
      return () => {
        cancelled = true
      }
    const entries = (['faces', 'edges'] as const).flatMap((kind) =>
      topology.highlights[kind].map((item) => {
        const record = topology.inspection[kind][item.index]
        return record
          ? recordHash(record).then((hash) => [`${kind}:${item.index}`, hash] as const)
          : Promise.reject(new Error('Missing inspection record'))
      }),
    )
    Promise.all(entries)
      .then((result) => {
        if (!cancelled) setHashResult({ scope: hashScope, values: Object.fromEntries(result) })
      })
      .catch(() => {
        if (!cancelled) setSelectionMessage('Inspection hashes are unavailable.')
      })
    return () => {
      cancelled = true
    }
  }, [topology, hashScope])
  useEffect(
    () => () => {
      if (model) disposeObject(model.object)
    },
    [model],
  )
  useEffect(() => {
    fetch('/api/presets')
      .then((response) => (response.ok ? response.json() : {}))
      .then((data: Presets) => setPresets(data))
      .catch(() => setParameterMessage('Could not load presets.'))
  }, [])

  async function post(path: string, body: unknown) {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) throw new Error(`Request failed (${response.status}).`)
    return response.json()
  }

  async function updateSelection(selection: Selection) {
    if (!topology || selectionPending.current) return
    const pending = {
      session: topology.session,
      revision: topology.revision,
      acknowledgedRevision: null as number | null,
    }
    selectionPending.current = pending
    try {
      const result: { selection_revision: number } = await post('/api/highlights', {
        session: topology.session,
        revision: topology.revision,
        ...selection,
      })
      if (selectionPending.current === pending)
        pending.acknowledgedRevision = result.selection_revision
      setSelectionMessage('Selection updated.')
    } catch (error) {
      if (selectionPending.current === pending) {
        selectionPending.current = null
        selectionQueue.current = []
      }
      setSelectionMessage(error instanceof Error ? error.message : 'Could not update selection.')
    }
  }

  function enqueueSelection(kind: SelectionMode | 'clear', index?: number) {
    if (!topology) return
    selectionQueue.current.push({
      session: topology.session,
      revision: topology.revision,
      kind,
      index,
    })
    setSelectionMessage('Updating selection…')
    setQueueTick((value) => value + 1)
  }

  function pick(kind: SelectionMode, index: number) {
    enqueueSelection(kind, index)
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: the queue is deliberately drained on snapshot or queue changes, not on every render.
  useEffect(() => {
    void queueTick
    if (!topology || selectionPending.current || selectionQueue.current.length === 0) return
    const action = selectionQueue.current.shift()
    if (!action || action.session !== topology.session || action.revision !== topology.revision)
      return
    const selected: Selection =
      action.kind === 'clear'
        ? { faces: [], edges: [] }
        : {
            faces: topology.highlights.faces.map((item) => item.index),
            edges: topology.highlights.edges.map((item) => item.index),
          }
    if (action.kind !== 'clear' && action.index !== undefined) {
      const key = action.kind === 'face' ? 'faces' : 'edges'
      selected[key] = selected[key].includes(action.index)
        ? selected[key].filter((item) => item !== action.index)
        : [...selected[key], action.index]
    }
    void updateSelection(selected)
  }, [topology, queueTick])

  async function copySelection() {
    if (!topology) return
    if (selectionPending.current || selectionQueue.current.length > 0) {
      setSelectionMessage('Selection is still updating; try again shortly.')
      return
    }
    const faces = topology.highlights.faces.map((item) => ({
      index: item.index,
      sha256: hashes[`faces:${item.index}`] ?? null,
    }))
    const edges = topology.highlights.edges.map((item) => ({
      index: item.index,
      sha256: hashes[`edges:${item.index}`] ?? null,
    }))
    try {
      // JSON is also a Python literal for these strings, arrays, integers and dictionaries.
      // Omit pending hashes rather than emit JSON null, which is not a Python literal.
      const withoutMissing = (items: typeof faces) =>
        items.map(({ index, sha256 }) => (sha256 ? { index, sha256 } : { index }))
      if ([...faces, ...edges].some((item) => !item.sha256)) {
        setSelectionMessage('Hashes are still calculating or unavailable; try again shortly.')
        return
      }
      const payload = {
        session: topology.session,
        model: topology.name,
        output: topology.output,
        revision: topology.revision,
        parameters: topology.values,
        faces: withoutMissing(faces),
        edges: withoutMissing(edges),
      }
      const python = pythonLiteral(payload)
      await navigator.clipboard.writeText(
        `# Revision-scoped inspection records; SHA-256 hashes are not persistent identities.\nselection = ${python}`,
      )
      setSelectionMessage('Copied Python selection.')
    } catch {
      setSelectionMessage('Could not copy selection. Check clipboard permissions.')
    }
  }

  async function applyValues(nextValues: Values, output?: string) {
    try {
      await post('/api/parameters', { values: nextValues, output })
      editingParameters.current = false
      setParameterMessage('Updating preview…')
    } catch (error) {
      setParameterMessage(error instanceof Error ? error.message : 'Could not update parameters.')
    }
  }

  async function chooseOutput(name: string) {
    setSelectedOutput(name)
    try {
      await post('/api/output', { name })
      editingParameters.current = false
      setParameterMessage('Updating preview…')
    } catch (error) {
      setParameterMessage(error instanceof Error ? error.message : 'Could not select output.')
    }
  }

  function changeParameter(name: string, value: ParameterValue) {
    editingParameters.current = true
    setValues((old) => ({ ...old, [name]: value }))
  }

  async function savePreset() {
    try {
      const saved: Presets = await post('/api/presets', {
        name: presetName,
        values,
        output: selectedOutput,
      })
      setPresets(saved)
      setSelectedPreset(presetName.trim())
      setParameterMessage('Preset saved beside the model.')
    } catch (error) {
      setParameterMessage(error instanceof Error ? error.message : 'Could not save preset.')
    }
  }

  async function openFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    try {
      const loaded = parseMesh(file.name, await file.text())
      setModel(loaded)
      setTopology(null)
      manualMesh.current = true
      setErrorDetails(null)
      setStatus(`${loaded.name} · display mesh loaded`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Could not read the selected file.')
    }
  }
  function loadPreset() {
    const saved = presets[selectedPreset]
    if (!saved) return
    const modern =
      typeof saved.output === 'string' && typeof saved.values === 'object' && saved.values !== null
    const savedValues = modern ? (saved.values as Values) : (saved as Values)
    const savedOutput = modern ? (saved.output as string) : undefined
    setValues(savedValues)
    if (savedOutput) setSelectedOutput(savedOutput)
    void applyValues(savedValues, savedOutput)
  }
  return (
    <main>
      <input ref={fileInput} type="file" accept=".obj" onChange={openFile} aria-label="Open OBJ" />
      <section className="workspace">
        <Viewport
          model={model}
          topology={topology}
          mode={selectionMode}
          onPick={pick}
          onWireFailure={reportWireFailure}
        />
        <Controls
          parameters={parameters}
          values={values}
          outputs={outputs}
          output={selectedOutput}
          topology={topology}
          mode={selectionMode}
          hashes={hashes}
          presets={presets}
          presetName={presetName}
          selectedPreset={selectedPreset}
          status={wireError || topologyError || selectionMessage || parameterMessage || status}
          change={changeParameter}
          chooseOutput={(name) => void chooseOutput(name)}
          setMode={setSelectionMode}
          copy={() => void copySelection()}
          clear={() => enqueueSelection('clear')}
          apply={() => void applyValues(values)}
          setPresetName={setPresetName}
          setSelectedPreset={setSelectedPreset}
          save={() => void savePreset()}
          load={loadPreset}
          open={() => fileInput.current?.click()}
        />
        {errorDetails && (
          <aside className="error-panel" role="alert">
            <strong>Rebuild failed</strong>
            <pre>{errorDetails}</pre>
          </aside>
        )}
        {!model && (
          <div className="empty">
            Open a model to inspect it.
            <small>Generate an OBJ with the solidrecipe CLI, then open it here.</small>
          </div>
        )}
      </section>
    </main>
  )
}

const root = document.getElementById('root')
if (!root) throw new Error('Missing root element')
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
